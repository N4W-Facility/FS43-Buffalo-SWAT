"""Ventana modal "Compare scenarios" (pestaña Batch Scenarios, pedido
explícito del usuario 2026-08-04): exportación comparativa entre los
escenarios de un batch, sin tener que abrir cada scenario_<pct>pct/ como
proyecto y exportar uno por uno.

Opera sobre cualquier carpeta de batch vía Browse (desacoplado de si el
batch se acaba de correr en esta sesión o es uno anterior) -- toda la
lógica de descubrimiento/lectura/agregación vive en
scenarios/comparison_export.py; esta ventana solo arma la configuración
(fuente RCH/HRU, variables, selección de HRU puntual o agrupada) y dispara
la exportación en hilo de fondo (ui.tasks.run_in_background), porque puede
implicar leer varias bases hru_timeseries.db completas.

Es de solo lectura sobre TxtInOut (nunca escribe ahí, solo lee lo que
Organize ya dejó en cada escenario y escribe CSV nuevos en
<batch>/comparison_exports/), así que -- igual que "Organize .rch"/"Organize
.hru output" -- no pide confirmación antes de exportar.
"""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, ttk
from typing import Callable

import customtkinter as ctk

from config.settings import ConfigManager
from scenarios.comparison_export import (
    ComparisonExportError,
    HRUGroupFilter,
    comparison_exports_dir,
    discover_hru_group_options,
    discover_hru_selection_options,
    discover_scenario_dirs,
    export_hru_group_comparison,
    export_hru_point_comparison,
    export_rch_comparison,
)
from swat_io.hru_output_parser import HRU_OUTPUT_VARIABLE_COLUMNS
from swat_io.rch_parser import RCH_VARIABLE_COLUMNS

from .tasks import run_in_background
from .variable_checklist import VariableChecklist
from .widgets import ReadOnlyField, palette, style_combobox

_SOURCE_RCH = "rch"
_SOURCE_HRU = "hru"
_HRU_MODE_POINT = "point"
_HRU_MODE_GROUP = "group"
_SCOPE_BASIN = "basin"
_SCOPE_SUBBASINS = "subbasins"

_CHECKLIST_HEIGHT_LARGE = 200
_CHECKLIST_HEIGHT_SMALL = 90


class ScenarioComparisonWindow(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        config: ConfigManager,
        *,
        initial_batch_dir: Path | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self._config = config
        self._colors = palette(config)

        self._batch_dir: Path | None = None
        self._scenario_dirs: list[Path] = []
        self._subbasins: list[int] = []
        self._hrus_by_sub: dict[int, list[int]] = {}

        self.title(config.text("scenario_comparison_window.title"))
        self.configure(fg_color=self._colors.get("window_bg"))
        self.transient(master)
        self.geometry("640x760")

        self._build()

        if initial_batch_dir is not None:
            self._batch_dir = Path(initial_batch_dir)
            self._folder_field.set_value(str(self._batch_dir))
            self._refresh_batch_info()

        self.grab_set()

    # -- construcción ------------------------------------------------------

    def _build(self) -> None:
        config = self._config
        colors = self._colors

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=16)
        body.columnconfigure(0, weight=1)
        row = 0

        # -- carpeta de batch ------------------------------------------------
        folder_row = ctk.CTkFrame(body, fg_color="transparent")
        folder_row.grid(row=row, column=0, sticky="ew", pady=(0, 4))
        folder_row.columnconfigure(0, weight=1)
        row += 1

        self._folder_field = ReadOnlyField(folder_row, config, "scenario_comparison_window.batch_folder_label")
        self._folder_field.grid(row=0, column=0, sticky="ew")
        self._folder_field.set_value(config.text("scenario_comparison_window.batch_folder_not_set"))

        browse_button = ctk.CTkButton(
            folder_row, text=config.text("config.browse"), command=self._on_browse_clicked, width=90
        )
        browse_button.grid(row=0, column=1, sticky="ne", padx=(12, 0))

        self._status_label = ctk.CTkLabel(
            body, text="", text_color=colors.get("text_secondary"), anchor="w", justify="left", wraplength=580
        )
        self._status_label.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        row += 1

        separator_1 = ctk.CTkFrame(body, height=1, fg_color=colors.get("border"))
        separator_1.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        row += 1

        # -- fuente RCH/HRU ---------------------------------------------------
        source_label = ctk.CTkLabel(
            body,
            text=config.text("scenario_comparison_window.source_label").upper(),
            text_color=colors.get("text_secondary"),
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        )
        source_label.grid(row=row, column=0, sticky="w")
        row += 1

        self._source_label_to_key = {
            config.text("scenario_comparison_window.source_rch"): _SOURCE_RCH,
            config.text("scenario_comparison_window.source_hru"): _SOURCE_HRU,
        }
        self._source_selector = ctk.CTkSegmentedButton(
            body, values=list(self._source_label_to_key), command=lambda _value: self._refresh_source_panels()
        )
        self._source_selector.set(config.text("scenario_comparison_window.source_rch"))
        self._source_selector.grid(row=row, column=0, sticky="w", pady=(4, 12))
        row += 1

        self._panels_row = row
        row += 1

        self._rch_panel = self._build_rch_panel(body)
        self._hru_panel = self._build_hru_panel(body)

        separator_2 = ctk.CTkFrame(body, height=1, fg_color=colors.get("border"))
        separator_2.grid(row=row, column=0, sticky="ew", pady=12)
        row += 1

        self._export_button = ctk.CTkButton(
            body, text=config.text("scenario_comparison_window.export_button"), command=self._on_export_clicked
        )
        self._export_button.grid(row=row, column=0, sticky="e")

        self._refresh_source_panels()

    def _build_rch_panel(self, master: ctk.CTkBaseClass) -> ctk.CTkFrame:
        config = self._config
        colors = self._colors
        panel = ctk.CTkFrame(master, fg_color="transparent")

        label = ctk.CTkLabel(
            panel,
            text=config.text("scenario_comparison_window.rch_variables_label"),
            text_color=colors.get("text_primary"),
            anchor="w",
        )
        label.pack(anchor="w", pady=(0, 4))

        rch_options = [(code, config.text(f"rch_var.{code}")) for code in RCH_VARIABLE_COLUMNS]
        self._rch_checklist = VariableChecklist(panel, config, rch_options, height=_CHECKLIST_HEIGHT_LARGE)
        self._rch_checklist.pack(fill="x")
        self._add_select_all_clear(panel, self._rch_checklist)

        return panel

    def _build_hru_panel(self, master: ctk.CTkBaseClass) -> ctk.CTkFrame:
        config = self._config
        colors = self._colors
        panel = ctk.CTkFrame(master, fg_color="transparent")
        panel.columnconfigure(0, weight=1)
        row = 0

        mode_label = ctk.CTkLabel(
            panel,
            text=config.text("scenario_comparison_window.hru_mode_label").upper(),
            text_color=colors.get("text_secondary"),
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        )
        mode_label.grid(row=row, column=0, sticky="w")
        row += 1

        self._hru_mode_label_to_key = {
            config.text("scenario_comparison_window.hru_mode_point"): _HRU_MODE_POINT,
            config.text("scenario_comparison_window.hru_mode_group"): _HRU_MODE_GROUP,
        }
        self._hru_mode_selector = ctk.CTkSegmentedButton(
            panel, values=list(self._hru_mode_label_to_key), command=lambda _value: self._refresh_hru_mode_panels()
        )
        self._hru_mode_selector.set(config.text("scenario_comparison_window.hru_mode_point"))
        self._hru_mode_selector.grid(row=row, column=0, sticky="w", pady=(4, 12))
        row += 1

        self._hru_mode_panels_row = row
        row += 1

        self._point_panel = self._build_point_panel(panel)
        self._group_panel = self._build_group_panel(panel)

        variables_label = ctk.CTkLabel(
            panel,
            text=config.text("scenario_comparison_window.hru_variables_label"),
            text_color=colors.get("text_primary"),
            anchor="w",
        )
        variables_label.grid(row=row, column=0, sticky="w", pady=(12, 4))
        row += 1

        hru_options = [(code, config.text(f"hru_out_var.{code}")) for code in HRU_OUTPUT_VARIABLE_COLUMNS]
        self._hru_checklist = VariableChecklist(panel, config, hru_options, height=_CHECKLIST_HEIGHT_LARGE)
        self._hru_checklist.grid(row=row, column=0, sticky="ew")
        row += 1
        self._add_select_all_clear(panel, self._hru_checklist, grid_row=row)

        self._refresh_hru_mode_panels()
        return panel

    def _build_point_panel(self, master: ctk.CTkBaseClass) -> ctk.CTkFrame:
        config = self._config
        colors = self._colors
        panel = ctk.CTkFrame(master, fg_color="transparent")

        selectors = ctk.CTkFrame(panel, fg_color="transparent")
        selectors.pack(anchor="w")

        sub_label = ctk.CTkLabel(
            selectors,
            text=config.text("scenario_comparison_window.point_subbasin_label").upper(),
            text_color=colors.get("text_secondary"),
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        sub_label.grid(row=0, column=0, sticky="w")
        self._point_subbasin_selector = ttk.Combobox(
            selectors, style=style_combobox(config), state="readonly", values=[], width=8
        )
        self._point_subbasin_selector.grid(row=1, column=0, sticky="w", padx=(0, 16))
        self._point_subbasin_selector.bind("<<ComboboxSelected>>", lambda _e: self._refresh_point_hru_selector())

        hru_label = ctk.CTkLabel(
            selectors,
            text=config.text("scenario_comparison_window.point_hru_label").upper(),
            text_color=colors.get("text_secondary"),
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        hru_label.grid(row=0, column=1, sticky="w")
        self._point_hru_selector = ttk.Combobox(
            selectors, style=style_combobox(config), state="readonly", values=[], width=8
        )
        self._point_hru_selector.grid(row=1, column=1, sticky="w")

        return panel

    def _build_group_panel(self, master: ctk.CTkBaseClass) -> ctk.CTkFrame:
        config = self._config
        colors = self._colors
        panel = ctk.CTkFrame(master, fg_color="transparent")
        panel.columnconfigure((0, 1, 2), weight=1)

        self._land_use_holder, self._land_use_checklist = self._build_group_filter_column(
            panel, "scenario_comparison_window.group_land_use_label", column=0
        )
        self._slope_holder, self._slope_checklist = self._build_group_filter_column(
            panel, "scenario_comparison_window.group_slope_label", column=1
        )
        self._soil_holder, self._soil_checklist = self._build_group_filter_column(
            panel, "scenario_comparison_window.group_soil_label", column=2
        )

        scope_label = ctk.CTkLabel(
            panel,
            text=config.text("scenario_comparison_window.group_scope_label").upper(),
            text_color=colors.get("text_secondary"),
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        )
        scope_label.grid(row=2, column=0, columnspan=3, sticky="w", pady=(12, 0))

        self._scope_label_to_key = {
            config.text("scenario_comparison_window.group_scope_basin"): _SCOPE_BASIN,
            config.text("scenario_comparison_window.group_scope_subbasins"): _SCOPE_SUBBASINS,
        }
        self._scope_selector = ctk.CTkSegmentedButton(
            panel, values=list(self._scope_label_to_key), command=lambda _value: self._refresh_scope_panel()
        )
        self._scope_selector.set(config.text("scenario_comparison_window.group_scope_basin"))
        self._scope_selector.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 8))

        self._subbasins_scope_panel = ctk.CTkFrame(panel, fg_color="transparent")
        self._subbasins_scope_panel.grid(row=4, column=0, columnspan=3, sticky="ew")

        subbasins_label = ctk.CTkLabel(
            self._subbasins_scope_panel,
            text=config.text("scenario_comparison_window.group_subbasins_label"),
            text_color=colors.get("text_primary"),
            anchor="w",
        )
        subbasins_label.pack(anchor="w", pady=(0, 4))

        self._subbasins_checklist = VariableChecklist(self._subbasins_scope_panel, config, [], height=_CHECKLIST_HEIGHT_SMALL)
        self._subbasins_checklist.pack(fill="x")

        return panel

    def _build_group_filter_column(
        self, master: ctk.CTkBaseClass, label_key: str, *, column: int
    ) -> tuple[ctk.CTkFrame, VariableChecklist]:
        config = self._config
        colors = self._colors
        holder = ctk.CTkFrame(master, fg_color="transparent")
        holder.grid(row=1, column=column, sticky="new", padx=(0 if column == 0 else 8, 0))

        label = ctk.CTkLabel(
            holder, text=config.text(label_key), text_color=colors.get("text_primary"), anchor="w", wraplength=170
        )
        label.pack(anchor="w", pady=(0, 4))

        checklist = VariableChecklist(holder, config, [], height=_CHECKLIST_HEIGHT_SMALL)
        checklist.pack(fill="x")
        return holder, checklist

    def _add_select_all_clear(self, master: ctk.CTkBaseClass, checklist: VariableChecklist, *, grid_row: int | None = None) -> None:
        config = self._config
        colors = self._colors
        row = ctk.CTkFrame(master, fg_color="transparent")
        if grid_row is None:
            row.pack(anchor="w", pady=(4, 0))
        else:
            row.grid(row=grid_row, column=0, sticky="w", pady=(4, 0))

        select_all_button = ctk.CTkButton(
            row,
            text=config.text("variable_selection_window.select_all"),
            fg_color="transparent",
            border_width=1,
            border_color=colors.get("border"),
            text_color=colors.get("text_primary"),
            hover_color=colors.get("window_bg"),
            width=90,
            command=checklist.select_all,
        )
        select_all_button.pack(side="left")

        clear_button = ctk.CTkButton(
            row,
            text=config.text("variable_selection_window.clear"),
            fg_color="transparent",
            border_width=1,
            border_color=colors.get("border"),
            text_color=colors.get("text_primary"),
            hover_color=colors.get("window_bg"),
            width=90,
            command=checklist.select_none,
        )
        clear_button.pack(side="left", padx=(8, 0))

    # -- toggles de panel ---------------------------------------------------

    def _refresh_source_panels(self) -> None:
        source_key = self._source_label_to_key[self._source_selector.get()]
        if source_key == _SOURCE_RCH:
            self._hru_panel.grid_forget()
            self._rch_panel.grid(row=self._panels_row, column=0, sticky="ew")
        else:
            self._rch_panel.grid_forget()
            self._hru_panel.grid(row=self._panels_row, column=0, sticky="ew")

    def _refresh_hru_mode_panels(self) -> None:
        mode_key = self._hru_mode_label_to_key[self._hru_mode_selector.get()]
        if mode_key == _HRU_MODE_POINT:
            self._group_panel.grid_forget()
            self._point_panel.grid(row=self._hru_mode_panels_row, column=0, sticky="ew")
        else:
            self._point_panel.grid_forget()
            self._group_panel.grid(row=self._hru_mode_panels_row, column=0, sticky="ew")

    def _refresh_scope_panel(self) -> None:
        scope_key = self._scope_label_to_key[self._scope_selector.get()]
        if scope_key == _SCOPE_SUBBASINS:
            self._subbasins_scope_panel.grid()
        else:
            self._subbasins_scope_panel.grid_remove()

    # -- carpeta de batch -----------------------------------------------------

    def _on_browse_clicked(self) -> None:
        selected = filedialog.askdirectory()
        if not selected:
            return
        self._batch_dir = Path(selected)
        self._folder_field.set_value(str(self._batch_dir))
        self._refresh_batch_info()

    def _refresh_batch_info(self) -> None:
        config = self._config
        self._scenario_dirs = discover_scenario_dirs(self._batch_dir) if self._batch_dir else []

        if not self._scenario_dirs:
            self._set_status(config.text("scenario_comparison_window.no_scenarios_hint"), error=True)
        else:
            names = ", ".join(d.name for d in self._scenario_dirs)
            self._set_status(
                config.text("scenario_comparison_window.scenarios_found").format(
                    count=len(self._scenario_dirs), names=names
                )
            )

        land_uses, slopes, soils = discover_hru_group_options(self._batch_dir) if self._batch_dir else ([], [], [])
        self._land_use_checklist = self._replace_checklist_options(self._land_use_holder, self._land_use_checklist, land_uses)
        self._slope_checklist = self._replace_checklist_options(self._slope_holder, self._slope_checklist, slopes)
        self._soil_checklist = self._replace_checklist_options(self._soil_holder, self._soil_checklist, soils)

        self._subbasins, self._hrus_by_sub = (
            discover_hru_selection_options(self._batch_dir) if self._batch_dir else ([], {})
        )
        self._subbasins_checklist = self._replace_checklist_options(
            self._subbasins_scope_panel, self._subbasins_checklist, [str(s) for s in self._subbasins]
        )

        self._point_subbasin_selector.configure(values=[str(s) for s in self._subbasins])
        self._point_subbasin_selector.set(str(self._subbasins[0]) if self._subbasins else "")
        self._refresh_point_hru_selector()

    def _replace_checklist_options(
        self, holder: ctk.CTkBaseClass, old_checklist: VariableChecklist, values: list[str]
    ) -> VariableChecklist:
        """VariableChecklist arma sus checkboxes en el constructor -- al
        cambiar de carpeta de batch, las opciones (coberturas/pendientes/
        suelos/subcuencas realmente disponibles) pueden ser otras, así que
        se reconstruye el widget en el mismo lugar en vez de intentar
        mutarlo in-place.

        `holder` es el contenedor real (guardado aparte por el llamador),
        no `old_checklist.master`: CTkScrollableFrame redirige pack()/
        grid()/destroy() a un `_parent_frame` interno y usa un canvas
        propio como su `.master` real, así que `old_checklist.master` NO
        es el contenedor donde se empaquetó -- usarlo hacía que el widget
        nuevo se creara con un master interno del widget viejo (a veces ya
        destruido), reventando con TclError."""
        old_checklist.destroy()
        new_checklist = VariableChecklist(holder, self._config, [(v, v) for v in values], height=_CHECKLIST_HEIGHT_SMALL)
        new_checklist.pack(fill="x")
        return new_checklist

    def _refresh_point_hru_selector(self) -> None:
        sub_value = self._point_subbasin_selector.get()
        hrus = self._hrus_by_sub.get(int(sub_value), []) if sub_value else []
        labels = [str(h) for h in hrus]
        self._point_hru_selector.configure(values=labels)
        self._point_hru_selector.set(labels[0] if labels else "")

    # -- export ---------------------------------------------------------------

    def _on_export_clicked(self) -> None:
        config = self._config
        if self._batch_dir is None or not self._scenario_dirs:
            self._set_status(config.text("scenario_comparison_window.no_batch_folder_hint"), error=True)
            return

        source_key = self._source_label_to_key[self._source_selector.get()]

        if source_key == _SOURCE_RCH:
            variables = self._rch_checklist.selected()
            if not variables:
                self._set_status(config.text("scenario_comparison_window.no_variables_hint"), error=True)
                return
            self._run_export(lambda: export_rch_comparison(self._batch_dir, variables))
            return

        variables = self._hru_checklist.selected()
        if not variables:
            self._set_status(config.text("scenario_comparison_window.no_variables_hint"), error=True)
            return

        mode_key = self._hru_mode_label_to_key[self._hru_mode_selector.get()]
        if mode_key == _HRU_MODE_POINT:
            sub_value = self._point_subbasin_selector.get()
            hru_value = self._point_hru_selector.get()
            if not sub_value or not hru_value:
                return
            sub, hru = int(sub_value), int(hru_value)
            self._run_export(lambda: export_hru_point_comparison(self._batch_dir, sub, hru, variables))
            return

        group_filter = HRUGroupFilter(
            land_uses=self._land_use_checklist.selected() or None,
            slopes=self._slope_checklist.selected() or None,
            soils=self._soil_checklist.selected() or None,
        )
        scope_key = self._scope_label_to_key[self._scope_selector.get()]
        if scope_key == _SCOPE_BASIN:
            scope = _SCOPE_BASIN
        else:
            subbasin_scope = [int(s) for s in self._subbasins_checklist.selected()]
            if not subbasin_scope:
                self._set_status(config.text("scenario_comparison_window.no_subbasins_selected_hint"), error=True)
                return
            scope = subbasin_scope

        self._run_export(lambda: export_hru_group_comparison(self._batch_dir, group_filter, variables, scope=scope))

    def _run_export(self, work_fn: Callable[[], list[Path]]) -> None:
        self._set_controls_enabled(False)
        self._set_status(self._config.text("scenario_comparison_window.exporting_status"))

        def work(_report_progress: Callable[[str], None]) -> list[Path]:
            return work_fn()

        run_in_background(
            self,
            work,
            on_progress=lambda _message: None,
            on_done=self._on_export_done,
            on_error=self._on_export_error,
        )

    def _on_export_done(self, written: list[Path]) -> None:
        dest = comparison_exports_dir(self._batch_dir)
        self._set_status(
            self._config.text("scenario_comparison_window.export_success").format(count=len(written), path=str(dest))
        )
        self._set_controls_enabled(True)

    def _on_export_error(self, error: Exception) -> None:
        if isinstance(error, ComparisonExportError):
            message = str(error)
        else:
            message = self._config.text("scenario_comparison_window.export_error").format(error=str(error))
        self._set_status(message, error=True)
        self._set_controls_enabled(True)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._export_button.configure(state="normal" if enabled else "disabled")

    # -- status ---------------------------------------------------------------

    def _set_status(self, text: str, *, error: bool = False) -> None:
        color_key = "error" if error else "text_secondary"
        self._status_label.configure(text=text, text_color=self._colors.get(color_key))
