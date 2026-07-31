"""Pestaña Wetlands (.pnd): tabla compilada de solo lectura, filas =
parámetro de humedal, columnas = subcuenca, para ver el panorama general
de un vistazo. El encabezado de cada columna es clickeable y abre
WetlandEditorWindow preseleccionada en esa subcuenca; al cerrarse esa
ventana, la tabla se refresca desde los .pnd reales.

También soporta modificación masiva vía CSV: "Load CSV" parsea y valida un
CSV con la misma estructura que wetland_summary.csv (ver
scenarios.wetland_import) y lo carga a un staging en memoria -- no toca
ningún .pnd. Las celdas en staging se muestran marcadas (" *") sobre el
valor real hasta que "Materialize to SWAT" las escribe de verdad (o se
pierden si se cierra la ventana sin materializar).

Cualquier celda de la tabla también se puede editar directo con doble
clic: se superpone un Entry sobre la celda (ttk.Treeview no soporta edición
inline nativa), valida contra el mismo rango declarado en
wetland_params.yaml que usa WetlandEditorWindow, y el resultado va al mismo
staging que "Load CSV" -- tampoco escribe al .pnd hasta Materialize.

Deshabilitada (vía TabBar.set_enabled) hasta que haya un proyecto abierto.
"""
from __future__ import annotations

from pathlib import Path
from tkinter import Entry, filedialog, ttk

import customtkinter as ctk

from config.settings import ConfigManager
from scenarios.validation import validate_field_value
from scenarios.wetland_draft import build_wetland_draft, save_wetland_draft
from scenarios.wetland_import import parse_wetland_import_csv
from swat_io.discovery import discover_subbasins
from swat_io.pnd_parser import _FIELD_TO_CODE, write_wetland_params

from .dialog_confirm import ConfirmDialog
from .wetland_editor_window import WetlandEditorWindow
from .widgets import palette

_ROW_HEIGHT = 26
_ACRONYM_COLUMN_WIDTH = 130
_SUBBASIN_COLUMN_WIDTH = 90
_STAGED_MARKER = " *"


class WetlandsTab(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, config: ConfigManager, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._config = config
        self._colors = palette(config)
        self._layout = config.load_layout("wetland_params")
        self._project_dir: Path | None = None
        self._staged: dict[int, dict[str, float]] = {}

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
            text=self._config.text("wetlands_tab.title"),
            text_color=self._colors.get("accent"),
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        )
        title.grid(row=0, column=0, sticky="w")

        self._subbasin_selector = ctk.CTkOptionMenu(header, values=[])
        self._subbasin_selector.grid(row=0, column=1, sticky="e", padx=(0, 8))

        self._edit_button = ctk.CTkButton(
            header, text=self._config.text("wetlands_tab.edit_button"), command=self._on_edit_clicked
        )
        self._edit_button.grid(row=0, column=2, sticky="e", padx=(0, 8))

        self._import_button = ctk.CTkButton(
            header, text=self._config.text("wetland.import_csv"), command=self._on_import_clicked
        )
        self._import_button.grid(row=0, column=3, sticky="e", padx=(0, 8))

        self._materialize_button = ctk.CTkButton(
            header, text=self._config.text("wetland.materialize"), command=self._on_materialize_clicked, state="disabled"
        )
        self._materialize_button.grid(row=0, column=4, sticky="e")

        self._status_label = ctk.CTkLabel(frame, text="", anchor="w", justify="left", wraplength=760)
        self._status_label.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        self._style_ttk()

        table_container = ctk.CTkFrame(frame, fg_color="transparent")
        table_container.grid(row=2, column=0, sticky="nsew")
        frame.rowconfigure(2, weight=1)
        table_container.rowconfigure(0, weight=1)
        table_container.columnconfigure(0, weight=1)

        self._tree = ttk.Treeview(table_container, style="Wetlands.Treeview", show="tree headings")
        self._tree.grid(row=0, column=0, sticky="nsew")
        self._tree.bind("<Double-1>", self._on_cell_double_click)

        v_scroll = ttk.Scrollbar(
            table_container, orient="vertical", style="Wetlands.Vertical.TScrollbar", command=self._tree.yview
        )
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll = ttk.Scrollbar(
            table_container, orient="horizontal", style="Wetlands.Horizontal.TScrollbar", command=self._tree.xview
        )
        h_scroll.grid(row=1, column=0, sticky="ew")
        self._tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        return frame

    def _style_ttk(self) -> None:
        """El look nativo de ttk (tema "default") dibuja las scrollbars con
        relieve 3D y flechas — no sigue la estética plana/moderna del resto
        de la app. "clam" es el tema ttk más reestilizable (permite quitar
        flechas y bordes), y coloreamos con los mismos tonos que ya usa la
        CTkScrollbar nativa en otras pestañas (idle=border, hover=accent)
        para que se vea consistente."""
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(
            "Wetlands.Treeview",
            background=self._colors.get("surface"),
            fieldbackground=self._colors.get("surface"),
            foreground=self._colors.get("text_primary"),
            rowheight=_ROW_HEIGHT,
            borderwidth=0,
        )
        style.configure(
            "Wetlands.Treeview.Heading",
            background=self._colors.get("window_bg"),
            foreground=self._colors.get("text_primary"),
            relief="flat",
            borderwidth=0,
        )
        style.map("Wetlands.Treeview.Heading", background=[("active", self._colors.get("window_bg"))])

        for orientation, layout_name in (("Vertical", "ns"), ("Horizontal", "ew")):
            style_name = f"Wetlands.{orientation}.TScrollbar"
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
        self._refresh_table()

    def _refresh_table(self) -> None:
        if self._project_dir is None:
            return
        draft = build_wetland_draft(self._project_dir / "TxtInOut")  # index=subbasin_id, columns=field_id
        self._draft = draft
        subbasin_ids = list(draft.index)

        subbasin_labels = [str(s) for s in subbasin_ids]
        self._subbasin_selector.configure(values=subbasin_labels)
        if subbasin_labels:
            self._subbasin_selector.set(subbasin_labels[0])

        self._tree.delete(*self._tree.get_children())
        self._tree["columns"] = subbasin_labels

        self._tree.heading("#0", text="")
        self._tree.column("#0", width=_ACRONYM_COLUMN_WIDTH, stretch=False, anchor="w")

        for subbasin_id in subbasin_ids:
            column_id = str(subbasin_id)
            self._tree.heading(column_id, text=column_id, command=lambda s=subbasin_id: self._open_editor(s))
            self._tree.column(column_id, width=_SUBBASIN_COLUMN_WIDTH, stretch=False, anchor="e")

        for field_id, code in _FIELD_TO_CODE.items():
            values = []
            for subbasin_id in subbasin_ids:
                staged_value = self._staged.get(subbasin_id, {}).get(field_id)
                if staged_value is not None:
                    values.append(f"{staged_value:.3f}{_STAGED_MARKER}")
                else:
                    values.append(f"{draft.loc[subbasin_id, field_id]:.3f}")
            self._tree.insert("", "end", iid=field_id, text=code, values=values)

        self._materialize_button.configure(state="normal" if self._staged else "disabled")

    def _on_edit_clicked(self) -> None:
        selected = self._subbasin_selector.get()
        if not selected:
            return
        self._open_editor(int(selected))

    def _open_editor(self, subbasin_id: int) -> None:
        if self._project_dir is None:
            return
        editor = WetlandEditorWindow(self, self._config, self._project_dir, initial_subbasin=subbasin_id)
        self.wait_window(editor)
        self._refresh_table()

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
            parsed = parse_wetland_import_csv(Path(path), known_subbasin_ids, self._layout)
        except ValueError as error:
            self._set_status(self._config.text("wetland.import_error").format(error=str(error)), error=True)
            return

        cell_count = sum(len(values) for values in parsed.values())
        message = self._config.text("wetland.import_confirm").format(count=cell_count, subbasins=len(parsed))
        ConfirmDialog(self, self._config, message=message, on_confirm=lambda: self._apply_import(parsed))

    def _apply_import(self, parsed: dict[int, dict[str, float]]) -> None:
        for subbasin_id, values in parsed.items():
            self._staged.setdefault(subbasin_id, {}).update(values)
        self._refresh_table()
        self._set_status(self._config.text("wetland.import_success"))

    # -- materializar staging en los .pnd reales -----------------------------

    def _on_materialize_clicked(self) -> None:
        if not self._staged:
            return
        cell_count = sum(len(values) for values in self._staged.values())
        message = self._config.text("wetland.materialize_confirm").format(
            count=cell_count, subbasins=len(self._staged)
        )
        ConfirmDialog(self, self._config, message=message, on_confirm=self._apply_materialize)

    def _apply_materialize(self) -> None:
        txtinout_dir = self._project_dir / "TxtInOut"
        pnd_by_subbasin = {s.subbasin_id: s.pnd_file for s in discover_subbasins(txtinout_dir)}

        errors: list[str] = []
        written_subbasins: list[int] = []
        for subbasin_id, values in self._staged.items():
            try:
                write_wetland_params(pnd_by_subbasin[subbasin_id], values)
            except OSError as error:
                errors.append(f"{subbasin_id}: {error}")
                continue
            written_subbasins.append(subbasin_id)

        for subbasin_id in written_subbasins:
            del self._staged[subbasin_id]

        save_wetland_draft(self._project_dir, build_wetland_draft(txtinout_dir))
        self._refresh_table()

        if errors:
            self._set_status(self._config.text("wetland.materialize_error").format(error="; ".join(errors)), error=True)
        else:
            self._set_status(self._config.text("wetland.materialize_success"))

    def _set_status(self, text: str, *, error: bool = False) -> None:
        color_key = "error" if error else "success"
        self._status_label.configure(text=text, text_color=self._colors.get(color_key))

    # -- edición inline de celdas (mismo staging que Load CSV) --------------

    def _on_cell_double_click(self, event) -> None:
        if self._project_dir is None:
            return
        if self._tree.identify_region(event.x, event.y) != "cell":
            return

        field_id = self._tree.identify_row(event.y)
        column_id = self._tree.identify_column(event.x)
        if not field_id or column_id == "#0":
            return

        subbasin_columns = self._tree["columns"]
        column_index = int(column_id[1:]) - 1
        if column_index < 0 or column_index >= len(subbasin_columns):
            return
        subbasin_id = int(subbasin_columns[column_index])

        bbox = self._tree.bbox(field_id, column_id)
        if not bbox:
            return
        x, y, width, height = bbox

        current = self._staged.get(subbasin_id, {}).get(field_id)
        if current is None:
            current = self._draft.loc[subbasin_id, field_id]

        entry = Entry(self._tree)
        entry.insert(0, f"{current:.3f}")
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
                validate_field_value(field_id, value, self._layout)
            except ValueError as error:
                self._set_status(str(error), error=True)
                return
            self._staged.setdefault(subbasin_id, {})[field_id] = value
            self._set_status("")
            self._refresh_table()

        def cancel(_event=None) -> None:
            if entry.winfo_exists():
                entry.destroy()

        entry.bind("<Return>", commit)
        entry.bind("<Escape>", cancel)
        entry.bind("<FocusOut>", commit)
