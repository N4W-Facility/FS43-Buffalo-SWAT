"""Pestaña HRUs (.hru): a diferencia de Wetlands (una fila por parámetro,
una columna por subcuenca -- porque cada subcuenca tiene exactamente un
.pnd), aquí una subcuenca tiene N archivos .hru, así que la tabla está
acotada a la subcuenca elegida en el selector: filas = HRU, columnas =
parámetro. Solo se parsean los .hru de la subcuenca seleccionada (nunca la
cuenca completa) -- con miles de HRU en total, escanear todo de una vez
violaría la regla de operaciones largas de CLAUDE.md; una subcuenca sola
es lo bastante chica para hacerse de forma síncrona, igual que ya hace
WetlandEditorWindow con discover_subbasins.

Tabla de solo lectura salvo edición inline: doble clic sobre el id de HRU
(columna #0) abre HRUEditorWindow preseleccionada en esa HRU (al cerrarse,
la tabla se refresca desde los .hru reales); doble clic sobre cualquier
otra celda (un parámetro) la edita inline igual que Wetlands -- overlay de
Entry, sin rango declarado (solo valida que sea numérico, igual que Load
CSV) -- y el resultado va al mismo staging en memoria que el import
masivo, marcado con " *" hasta Materialize.

"Export CSV" vuelca la tabla de la subcuenca visible (subbasin, hru, y
cada parámetro real) a un CSV listo para editar y reimportar -- sin lista
curada de parámetros (a diferencia de Wetlands), es la única forma de que
el usuario sepa de antemano qué columnas/HRU son válidas para el import
masivo (ver scenarios.hru_draft.export_hru_table_csv). No es un respaldo
como wetland_params_draft.csv, es una plantilla bajo demanda.

También soporta modificación masiva vía CSV: "Load CSV" parsea y valida un
CSV indexado por (subbasin, hru) -- ver scenarios.hru_import -- y lo carga
a un staging en memoria (dict {(subbasin_id, hru_id): {parametro: valor}})
-- no toca ningún .hru. Las celdas en staging se muestran marcadas (" *")
sobre la tabla de solo lectura, solo para la subcuenca actualmente
visible (el staging de otras subcuencas persiste igual, solo no se dibuja
hasta volver a seleccionarlas). El botón "Materialize to SWAT" es el único
paso que escribe de verdad. A diferencia del Materialize de Wetlands
(síncrono: como mucho una escritura por subcuenca, acotado por el número
de subcuencas), este SÍ corre en hilo de fondo (ui.tasks.run_in_background)
y bloquea navegación mientras corre: un CSV de HRUs puede tocar muchas más
filas que uno de Wetlands (una por HRU, no por subcuenca), y CLAUDE.md
exige hilo de fondo para cualquier operación que pueda escalar a "miles de
.hru".

Deshabilitada (vía TabBar.set_enabled) hasta que haya un proyecto abierto.
"""
from __future__ import annotations

import math
from pathlib import Path
from tkinter import Entry, filedialog, ttk
from typing import Callable

import customtkinter as ctk
import pandas as pd

from config.settings import ConfigManager
from scenarios.hru_draft import (
    HRU_FR_SUM_TOLERANCE,
    HRU_FR_TARGET_SUM,
    build_hru_table,
    effective_hru_fr_sum,
    export_hru_table_csv,
    load_subbasin_hru_files,
    subbasin_hru_fr_sum,
    write_hru_values,
)
from scenarios.hru_import import parse_hru_import_csv
from swat_io.discovery import discover_subbasins
from swat_io.hru.exceptions import HRUModificationError

from .dialog_confirm import ConfirmDialog
from .hru_editor_window import HRUEditorWindow
from .tasks import run_in_background
from .widgets import bind_responsive_wraplength, palette, style_combobox

_ROW_HEIGHT = 26
_HRU_COLUMN_WIDTH = 70
_PARAM_COLUMN_WIDTH = 110
_STAGED_MARKER = " *"


def _format_cell(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


class HRUsTab(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        config: ConfigManager,
        *,
        on_run_state_changed: Callable[[bool], None] = lambda running: None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._config = config
        self._colors = palette(config)
        self._on_run_state_changed = on_run_state_changed
        self._project_dir: Path | None = None
        self._hru_files: dict[int, object] = {}
        self._table: pd.DataFrame = pd.DataFrame()
        self._staged: dict[tuple[int, int], dict[str, float]] = {}

        self._disabled_state = self._build_disabled_state()
        self._enabled_state = self._build_enabled_state()
        self._disabled_state.pack(fill="both", expand=True)

    # -- construcción -------------------------------------------------------

    def _build_disabled_state(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        hint = ctk.CTkLabel(
            frame,
            text=self._config.text("summary.disabled_hint"),
            text_color=self._colors.get("text_secondary"),
        )
        hint.place(relx=0.5, rely=0.4, anchor="center")
        return frame

    def _build_enabled_state(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.columnconfigure(0, weight=1)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            header,
            text=self._config.text("hru_tab.title"),
            text_color=self._colors.get("accent"),
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        )
        title.grid(row=0, column=0, sticky="w")

        subbasin_label = ctk.CTkLabel(
            header,
            text=self._config.text("hru_tab.subbasin_label"),
            text_color=self._colors.get("text_secondary"),
        )
        subbasin_label.grid(row=0, column=1, sticky="e", padx=(0, 4))

        self._subbasin_selector = ttk.Combobox(
            header, style=style_combobox(self._config), state="readonly", values=[], width=8
        )
        self._subbasin_selector.grid(row=0, column=2, sticky="e", padx=(0, 8))
        self._subbasin_selector.bind("<<ComboboxSelected>>", self._on_subbasin_selected)

        self._edit_button = ctk.CTkButton(
            header, text=self._config.text("hru_tab.edit_button"), command=self._on_edit_clicked
        )
        self._edit_button.grid(row=0, column=3, sticky="e", padx=(0, 8))

        self._export_button = ctk.CTkButton(
            header, text=self._config.text("hru_tab.export_csv"), command=self._on_export_clicked
        )
        self._export_button.grid(row=0, column=4, sticky="e", padx=(0, 8))

        self._import_button = ctk.CTkButton(
            header, text=self._config.text("hru_tab.import_csv"), command=self._on_import_clicked
        )
        self._import_button.grid(row=0, column=5, sticky="e", padx=(0, 8))

        self._materialize_button = ctk.CTkButton(
            header,
            text=self._config.text("hru_tab.materialize"),
            command=self._on_materialize_clicked,
            state="disabled",
        )
        self._materialize_button.grid(row=0, column=6, sticky="e")

        self._hru_fr_sum_label = ctk.CTkLabel(frame, text="", anchor="w")
        self._hru_fr_sum_label.grid(row=1, column=0, sticky="ew", pady=(0, 4))

        self._status_label = ctk.CTkLabel(frame, text="", anchor="w", justify="left")
        self._status_label.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        bind_responsive_wraplength(self._status_label)

        instructions_label = ctk.CTkLabel(
            frame,
            text=self._config.text("hru_tab.instructions"),
            text_color=self._colors.get("text_secondary"),
            anchor="w",
            justify="left",
        )
        instructions_label.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        bind_responsive_wraplength(instructions_label)

        self._style_ttk()

        table_container = ctk.CTkFrame(frame, fg_color="transparent")
        table_container.grid(row=4, column=0, sticky="nsew")
        frame.rowconfigure(4, weight=1)
        table_container.rowconfigure(0, weight=1)
        table_container.columnconfigure(0, weight=1)

        self._tree = ttk.Treeview(table_container, style="HRU.Treeview", show="tree headings")
        self._tree.grid(row=0, column=0, sticky="nsew")
        self._tree.bind("<Double-1>", self._on_row_double_click)

        v_scroll = ttk.Scrollbar(
            table_container, orient="vertical", style="HRU.Vertical.TScrollbar", command=self._tree.yview
        )
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll = ttk.Scrollbar(
            table_container, orient="horizontal", style="HRU.Horizontal.TScrollbar", command=self._tree.xview
        )
        h_scroll.grid(row=1, column=0, sticky="ew")
        self._tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        return frame

    def _style_ttk(self) -> None:
        """Ver WetlandsTab._style_ttk: mismo motivo (tema ttk "clam" para
        poder recolorear scrollbars/encabezados y que no desentonen con el
        resto de la UI plana)."""
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(
            "HRU.Treeview",
            background=self._colors.get("surface"),
            fieldbackground=self._colors.get("surface"),
            foreground=self._colors.get("text_primary"),
            rowheight=_ROW_HEIGHT,
            borderwidth=0,
        )
        style.configure(
            "HRU.Treeview.Heading",
            background=self._colors.get("window_bg"),
            foreground=self._colors.get("text_primary"),
            relief="flat",
            borderwidth=0,
        )
        style.map("HRU.Treeview.Heading", background=[("active", self._colors.get("window_bg"))])

        for orientation, layout_name in (("Vertical", "ns"), ("Horizontal", "ew")):
            style_name = f"HRU.{orientation}.TScrollbar"
            style.layout(
                style_name,
                [
                    (
                        f"{orientation}.Scrollbar.trough",
                        {
                            "children": [
                                (f"{orientation}.Scrollbar.thumb", {"expand": 1, "sticky": layout_name})
                            ],
                            "sticky": layout_name,
                        },
                    )
                ],
            )
            style.configure(
                style_name,
                background=self._colors.get("border"),
                troughcolor=self._colors.get("window_bg"),
                borderwidth=0,
                relief="flat",
            )
            style.map(style_name, background=[("active", self._colors.get("accent"))])

    # -- estado del proyecto -------------------------------------------------

    def set_project(self, project_dir: Path) -> None:
        self._project_dir = project_dir
        self._staged = {}
        self._enabled_state.pack(fill="both", expand=True)
        self._disabled_state.pack_forget()

        subbasins = discover_subbasins(project_dir / "TxtInOut")
        subbasin_labels = [str(s.subbasin_id) for s in subbasins]
        self._subbasin_selector.configure(values=subbasin_labels)
        if subbasin_labels:
            self._subbasin_selector.set(subbasin_labels[0])
        self._refresh_table()

    def _on_subbasin_selected(self, _event=None) -> None:
        self._refresh_table()

    def _refresh_table(self) -> None:
        if self._project_dir is None:
            return
        selected = self._subbasin_selector.get()
        self._tree.delete(*self._tree.get_children())
        self._tree["columns"] = []

        if not selected:
            self._edit_button.configure(state="disabled")
            self._export_button.configure(state="disabled")
            self._materialize_button.configure(state="normal" if self._staged else "disabled")
            self._hru_fr_sum_label.configure(text="")
            return

        subbasin_id = int(selected)
        self._hru_files = load_subbasin_hru_files(self._project_dir / "TxtInOut", subbasin_id)
        table = build_hru_table(self._hru_files)
        self._table = table
        self._update_hru_fr_sum_label(subbasin_id, table)

        self._tree.heading("#0", text=self._config.text("hru_tab.hru_column"))
        self._tree.column("#0", width=_HRU_COLUMN_WIDTH, stretch=False, anchor="e")

        columns = list(table.columns)
        self._tree["columns"] = columns
        for column in columns:
            self._tree.heading(column, text=column)
            self._tree.column(column, width=_PARAM_COLUMN_WIDTH, stretch=False, anchor="e")

        for hru_id in table.index:
            row_staged = self._staged.get((subbasin_id, hru_id), {})
            values = []
            for column in columns:
                if column in row_staged:
                    values.append(f"{row_staged[column]:g}{_STAGED_MARKER}")
                else:
                    values.append(_format_cell(table.loc[hru_id, column]))
            self._tree.insert("", "end", iid=str(hru_id), text=str(hru_id), values=values)

        self._edit_button.configure(state="normal" if self._hru_files else "disabled")
        self._export_button.configure(state="normal" if self._hru_files else "disabled")
        self._materialize_button.configure(state="normal" if self._staged else "disabled")
        if not self._hru_files:
            self._set_status(self._config.text("hru_tab.no_hrus"))
        else:
            self._set_status("")

    def _update_hru_fr_sum_label(self, subbasin_id: int, table: pd.DataFrame) -> None:
        """Aviso indicativo (nunca bloqueante, ver CLAUDE.md): HRU_FR sumado
        entre las HRU visibles de esta subcuenca debería dar ~1.0. Usa el
        staging en memoria cuando hay una celda editada, igual que la tabla
        misma, para que el aviso refleje lo que se ve, no solo lo ya
        guardado en disco."""
        subbasin_staged = {
            hru_id: values for (sub_id, hru_id), values in self._staged.items() if sub_id == subbasin_id
        }
        total = effective_hru_fr_sum(table, subbasin_staged)
        if total is None:
            self._hru_fr_sum_label.configure(text="")
            return

        on_target = abs(total - HRU_FR_TARGET_SUM) <= HRU_FR_SUM_TOLERANCE
        color_key = "text_secondary" if on_target else "warning"
        self._hru_fr_sum_label.configure(
            text=self._config.text("hru_tab.hru_fr_sum_label").format(
                sum=f"{total:.3f}", target=f"{HRU_FR_TARGET_SUM:g}"
            ),
            text_color=self._colors.get(color_key),
        )

    def _on_edit_clicked(self) -> None:
        selected_subbasin = self._subbasin_selector.get()
        if not selected_subbasin or not self._hru_files:
            return
        selection = self._tree.selection()
        hru_id = int(selection[0]) if selection else min(self._hru_files)
        self._open_editor(int(selected_subbasin), hru_id)

    def _on_row_double_click(self, event) -> None:
        if self._tree.identify_region(event.x, event.y) not in ("tree", "cell"):
            return
        row_id = self._tree.identify_row(event.y)
        if not row_id:
            return
        selected_subbasin = self._subbasin_selector.get()
        if not selected_subbasin:
            return

        column_id = self._tree.identify_column(event.x)
        if column_id == "#0":
            self._open_editor(int(selected_subbasin), int(row_id))
            return
        self._start_inline_edit(int(selected_subbasin), int(row_id), column_id)

    def _open_editor(self, subbasin_id: int, hru_id: int) -> None:
        if self._project_dir is None:
            return
        editor = HRUEditorWindow(
            self, self._config, self._project_dir, initial_subbasin=subbasin_id, initial_hru=hru_id
        )
        self.wait_window(editor)
        self._refresh_table()

    # -- edición inline de celdas (mismo staging que Load CSV) ---------------

    def _start_inline_edit(self, subbasin_id: int, hru_id: int, column_id: str) -> None:
        columns = list(self._table.columns)
        column_index = int(column_id[1:]) - 1
        if column_index < 0 or column_index >= len(columns):
            return
        parameter_name = columns[column_index]

        bbox = self._tree.bbox(str(hru_id), column_id)
        if not bbox:
            return
        x, y, width, height = bbox

        staged_value = self._staged.get((subbasin_id, hru_id), {}).get(parameter_name)
        current = staged_value if staged_value is not None else self._table.loc[hru_id, parameter_name]

        entry = Entry(self._tree)
        entry.insert(0, _format_cell(current))
        entry.select_range(0, "end")
        entry.place(x=x, y=y, width=width, height=height)
        entry.focus_set()

        def commit(_event=None) -> None:
            if not entry.winfo_exists():
                return
            raw = entry.get()
            entry.destroy()
            try:
                value = float(raw)
            except ValueError:
                self._set_status(
                    self._config.text("hru_tab.inline_edit_error").format(value=raw), error=True
                )
                return
            self._staged.setdefault((subbasin_id, hru_id), {})[parameter_name] = value
            self._set_status("")
            self._refresh_table()

        def cancel(_event=None) -> None:
            if entry.winfo_exists():
                entry.destroy()

        entry.bind("<Return>", commit)
        entry.bind("<Escape>", cancel)
        entry.bind("<FocusOut>", commit)

    # -- export CSV de referencia (plantilla para el import) -----------------

    def _on_export_clicked(self) -> None:
        selected_subbasin = self._subbasin_selector.get()
        if self._project_dir is None or not selected_subbasin or not self._hru_files:
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile=f"hru_subbasin_{selected_subbasin}.csv",
        )
        if not path:
            return

        try:
            export_hru_table_csv(int(selected_subbasin), self._table, Path(path))
        except OSError as error:
            self._set_status(self._config.text("hru_tab.export_error").format(error=str(error)), error=True)
            return

        self._set_status(self._config.text("hru_tab.export_success").format(path=path))

    # -- import CSV masivo (staging en memoria) ------------------------------

    def _on_import_clicked(self) -> None:
        if self._project_dir is None:
            return
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
        if not path:
            return

        txtinout_dir = self._project_dir / "TxtInOut"
        known_subbasin_ids = [s.subbasin_id for s in discover_subbasins(txtinout_dir)]

        try:
            parsed = parse_hru_import_csv(Path(path), txtinout_dir, known_subbasin_ids)
        except ValueError as error:
            self._set_status(self._config.text("hru_tab.import_error").format(error=str(error)), error=True)
            return

        cell_count = sum(len(values) for values in parsed.values())
        message = self._config.text("hru_tab.import_confirm").format(count=cell_count, hrus=len(parsed))
        ConfirmDialog(self, self._config, message=message, on_confirm=lambda: self._apply_import(parsed))

    def _apply_import(self, parsed: dict[tuple[int, int], dict[str, float]]) -> None:
        for key, values in parsed.items():
            self._staged.setdefault(key, {}).update(values)
        self._refresh_table()
        self._set_status(self._config.text("hru_tab.import_success"))

    # -- materializar staging en los .hru reales (hilo de fondo) -------------

    def _on_materialize_clicked(self) -> None:
        if not self._staged:
            return
        cell_count = sum(len(values) for values in self._staged.values())
        message = self._config.text("hru_tab.materialize_confirm").format(
            count=cell_count, hrus=len(self._staged)
        )
        ConfirmDialog(self, self._config, message=message, on_confirm=self._start_materialize)

    def _start_materialize(self) -> None:
        txtinout_dir = self._project_dir / "TxtInOut"
        staged = dict(self._staged)

        self._set_controls_enabled(False)
        self._set_status(self._config.text("hru_tab.materializing"))
        self._on_run_state_changed(True)

        def work(report_progress):
            files_by_subbasin: dict[int, dict[int, object]] = {}
            written_keys: list[tuple[int, int]] = []
            errors: list[str] = []

            for index, ((subbasin_id, hru_id), values) in enumerate(staged.items(), start=1):
                report_progress(f"{index}/{len(staged)}")
                hru_files = files_by_subbasin.get(subbasin_id)
                if hru_files is None:
                    hru_files = load_subbasin_hru_files(txtinout_dir, subbasin_id)
                    files_by_subbasin[subbasin_id] = hru_files

                hru_file = hru_files.get(hru_id)
                if hru_file is None:
                    errors.append(f"{subbasin_id}/{hru_id}: ya no existe.")
                    continue
                try:
                    write_hru_values(hru_file, values)
                except (HRUModificationError, OSError) as error:
                    errors.append(f"{subbasin_id}/{hru_id}: {error}")
                    continue
                written_keys.append((subbasin_id, hru_id))

            hru_fr_warnings: dict[int, float] = {}
            for subbasin_id, hru_files in files_by_subbasin.items():
                total = subbasin_hru_fr_sum(hru_files)
                if total is not None and abs(total - HRU_FR_TARGET_SUM) > HRU_FR_SUM_TOLERANCE:
                    hru_fr_warnings[subbasin_id] = total

            return {"written": written_keys, "errors": errors, "hru_fr_warnings": hru_fr_warnings}

        run_in_background(
            self,
            work,
            on_progress=lambda message: self._set_status(
                self._config.text("hru_tab.materializing_progress").format(progress=message)
            ),
            on_done=self._on_materialize_done,
            on_error=self._on_materialize_error,
        )

    def _on_materialize_done(self, result: dict) -> None:
        for key in result["written"]:
            del self._staged[key]

        self._refresh_table()
        self._finish_materialize()

        if result["errors"]:
            self._set_status(
                self._config.text("hru_tab.materialize_error").format(error="; ".join(result["errors"])),
                error=True,
            )
            return

        message = self._config.text("hru_tab.materialize_success")
        warnings = result.get("hru_fr_warnings") or {}
        if warnings:
            details = "; ".join(f"{sub}: {total:.3f}" for sub, total in sorted(warnings.items()))
            message += " " + self._config.text("hru_tab.materialize_hru_fr_warning").format(
                target=f"{HRU_FR_TARGET_SUM:g}", details=details
            )
        self._set_status(message)

    def _on_materialize_error(self, error: Exception) -> None:
        self._finish_materialize()
        self._set_status(self._config.text("hru_tab.materialize_error").format(error=str(error)), error=True)

    def _finish_materialize(self) -> None:
        self._set_controls_enabled(True)
        self._on_run_state_changed(False)

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self._subbasin_selector.configure(state="readonly" if enabled else "disabled")
        self._edit_button.configure(state=state if enabled and self._hru_files else "disabled")
        self._export_button.configure(state=state if enabled and self._hru_files else "disabled")
        self._import_button.configure(state=state)
        self._materialize_button.configure(state=state if enabled and self._staged else "disabled")

    def _set_status(self, text: str, *, error: bool = False) -> None:
        color_key = "error" if error else "text_secondary"
        self._status_label.configure(text=text, text_color=self._colors.get(color_key))
