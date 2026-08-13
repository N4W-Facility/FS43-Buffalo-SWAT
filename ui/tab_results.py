"""Pestaña Results (output.rch): organiza la salida de caudal/cargas por
tramo en CSV legibles (uno por reach, una fila por fecha -- estilo serie de
tiempo), y permite explorarla con un selector de reach + variable
(gráfica) y un mapa estático de subcuencas/reach que resalta la selección.

"Organize .rch" corre en hilo de fondo (ui.tasks.run_in_background, como
toda operación que parsea un modelo real -- CLAUDE.md): parsea
TxtInOut/output.rch entero (swat_io.rch_parser.parse_rch_file),
reconstruye fechas reales según file.cio (año/frecuencia de impresión,
swat_io.cio_parser.parse_run_settings +
swat_io.rch_parser.build_rch_timeseries) y escribe un CSV por reach en
tool_outputs/rch_timeseries/. No toca ningún archivo de TxtInOut -- a
diferencia de Materialize en Wetlands/HRUs, no pide confirmación, igual
que el botón Run de SummaryTab (genera resultados propios de la app, no
modifica el modelo).

Al reabrir el proyecto, si tool_outputs/rch_timeseries/ ya tiene CSVs de
una corrida anterior de Organize, se releen directo
(swat_io.rch_parser.read_rch_timeseries_dir) sin volver a parsear el
.rch -- mismo patrón de caché que SummaryTab con land_use_by_subbasin.csv.

El mapa (viz.shapefile_map, geometría de viz.shapefile_reader) es
puramente estático: no hay click-to-select sobre él, solo se redibuja
cuando cambia el selector de reach (pedido explícito del usuario). Usa
los shapefiles configurados en la pestaña Project
(ProjectMetadata.reach_shp_path / subbasin_shp_path); si no están
configurados o no se pueden leer, se muestra un hint en vez de intentar
dibujar. La geometría se lee una sola vez por cada set_project (no en
cada cambio de selección) y se cachea en memoria -- solo el resaltado
cambia al redibujar.

Deshabilitada (vía TabBar.set_enabled) hasta que haya un proyecto abierto
-- a diferencia de Wetlands/HRUs/Run, queda habilitada incluso si
output.rch todavía no existe (el usuario puede no haber corrido SWAT
todavía): en ese caso "Organize .rch" queda deshabilitado con un hint, en
vez de bloquear toda la pestaña.
"""
from __future__ import annotations

import os
from pathlib import Path
from tkinter import ttk
from typing import Callable

import customtkinter as ctk
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from config.settings import ConfigManager
from scenarios.activity_log import log_action
from scenarios.project import ProjectMetadata
from swat_io.cio_parser import CioParseError, parse_run_settings
from swat_io.rch_parser import (
    RCH_VARIABLE_COLUMNS,
    build_rch_timeseries,
    export_rch_timeseries_csvs,
    parse_rch_file,
    rch_timeseries_dir,
    read_rch_timeseries_dir,
)
from viz.rch_chart import build_rch_timeseries_figure
from viz.shapefile_map import build_shapefile_map_figure
from viz.shapefile_reader import ShapefileReadError, read_reach_shapes, read_subbasin_shapes

from .tasks import run_in_background
from .widgets import palette, style_combobox

_DEFAULT_VARIABLE = "FLOW_OUT"


class ResultsTab(ctk.CTkFrame):
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
        self._metadata: ProjectMetadata = ProjectMetadata()
        self._timeseries: pd.DataFrame = pd.DataFrame()

        # Nombre + unidad para mostrar en el selector/gráfica (pedido
        # explícito del usuario, 2026-08-03: el código crudo de SWAT, ej.
        # "FLOW_OUT", no es intuitivo para un usuario del común). El código
        # sigue siendo la clave interna (columna del DataFrame, nombre del
        # CSV exportado) -- solo la etiqueta visible cambia.
        self._variable_code_to_label = {code: self._config.text(f"rch_var.{code}") for code in RCH_VARIABLE_COLUMNS}
        self._variable_label_to_code = {label: code for code, label in self._variable_code_to_label.items()}

        self._subbasin_shapes: list | None = None
        self._reach_shapes: list | None = None
        self._map_error: str | None = None

        self._chart_canvas: FigureCanvasTkAgg | None = None
        self._map_canvas: FigureCanvasTkAgg | None = None

        self._disabled_state = self._build_disabled_state()
        self._enabled_state = self._build_enabled_state()
        self._disabled_state.pack(fill="both", expand=True)

    # -- construcción -----------------------------------------------------

    def _build_disabled_state(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        hint = ctk.CTkLabel(
            frame, text=self._config.text("summary.disabled_hint"), text_color=self._colors.get("text_secondary")
        )
        hint.place(relx=0.5, rely=0.4, anchor="center")
        return frame

    def _build_enabled_state(self) -> ctk.CTkFrame:
        frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        frame.columnconfigure(0, weight=1)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            header,
            text=self._config.text("results_tab.title"),
            text_color=self._colors.get("accent"),
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        )
        title.grid(row=0, column=0, sticky="w")

        self._open_folder_button = ctk.CTkButton(
            header,
            text=self._config.text("summary.open_output_folder"),
            fg_color="transparent",
            border_width=1,
            border_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"),
            hover_color=self._colors.get("window_bg"),
            command=self._on_open_folder_clicked,
        )
        self._open_folder_button.grid(row=0, column=1, sticky="e", padx=(0, 8))

        self._organize_button = ctk.CTkButton(
            header,
            text=self._config.text("results_tab.organize_button"),
            command=self._on_organize_clicked,
            state="disabled",
        )
        self._organize_button.grid(row=0, column=2, sticky="e")

        self._status_label = ctk.CTkLabel(
            frame, text="", anchor="w", justify="left", wraplength=880, text_color=self._colors.get("text_secondary")
        )
        self._status_label.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        separator = ctk.CTkFrame(frame, height=1, fg_color=self._colors.get("border"))
        separator.grid(row=2, column=0, sticky="ew", pady=(0, 12))

        selectors = ctk.CTkFrame(frame, fg_color="transparent")
        selectors.grid(row=3, column=0, sticky="w")

        reach_label = ctk.CTkLabel(
            selectors,
            text=self._config.text("results_tab.reach_label").upper(),
            text_color=self._colors.get("text_secondary"),
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        reach_label.grid(row=0, column=0, sticky="w")
        self._reach_selector = ttk.Combobox(
            selectors, style=style_combobox(self._config), state="readonly", values=[], width=8
        )
        self._reach_selector.grid(row=1, column=0, sticky="w", padx=(0, 16))
        self._reach_selector.bind("<<ComboboxSelected>>", self._on_selection_changed)

        variable_label = ctk.CTkLabel(
            selectors,
            text=self._config.text("results_tab.variable_label").upper(),
            text_color=self._colors.get("text_secondary"),
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        variable_label.grid(row=0, column=1, sticky="w")
        self._variable_selector = ttk.Combobox(
            selectors,
            style=style_combobox(self._config),
            state="readonly",
            values=list(self._variable_code_to_label.values()),
            width=48,
        )
        self._variable_selector.grid(row=1, column=1, sticky="w")
        self._variable_selector.bind("<<ComboboxSelected>>", self._on_selection_changed)

        body = ctk.CTkFrame(frame, fg_color="transparent")
        body.grid(row=4, column=0, sticky="ew", pady=(16, 0))
        body.columnconfigure(0, weight=1)

        chart_card = ctk.CTkFrame(body, fg_color="transparent")
        chart_card.grid(row=0, column=0, sticky="new")

        self._chart_empty_label = ctk.CTkLabel(
            chart_card, text=self._config.text("results_tab.chart_empty_hint"), text_color=self._colors.get("text_secondary"), anchor="w"
        )
        self._chart_empty_label.pack(anchor="w")

        self._chart_canvas_frame = ctk.CTkFrame(chart_card, fg_color=self._colors.get("surface"))

        map_card = ctk.CTkFrame(body)
        map_card.grid(row=0, column=1, sticky="n", padx=(16, 0))

        map_title = ctk.CTkLabel(
            map_card,
            text=self._config.text("results_tab.map_title"),
            text_color=self._colors.get("text_primary"),
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        map_title.pack(anchor="w", padx=12, pady=(12, 4))

        self._map_hint_label = ctk.CTkLabel(
            map_card,
            text=self._config.text("results_tab.map_missing_hint"),
            text_color=self._colors.get("text_secondary"),
            wraplength=220,
            justify="left",
        )
        self._map_hint_label.pack(anchor="w", padx=12, pady=(0, 12))

        self._map_canvas_frame = ctk.CTkFrame(map_card, fg_color=self._colors.get("surface"))

        return frame

    # -- estado del proyecto -----------------------------------------------

    def set_project(self, project_dir: Path, metadata: ProjectMetadata) -> None:
        self._project_dir = project_dir
        self._metadata = metadata
        self._enabled_state.pack(fill="both", expand=True)
        self._disabled_state.pack_forget()

        self._refresh_organize_availability()

        cached = read_rch_timeseries_dir(rch_timeseries_dir(project_dir))
        self._timeseries = cached
        self._refresh_selectors()

        self._load_map_shapes()
        self._refresh_map()

    def _rch_path(self) -> Path:
        return self._project_dir / "TxtInOut" / "output.rch"

    def _on_open_folder_clicked(self) -> None:
        if self._project_dir is None:
            return
        os.startfile(rch_timeseries_dir(self._project_dir))  # solo Windows: target de distribución del proyecto

    def _refresh_organize_availability(self) -> None:
        exists = self._rch_path().is_file()
        self._organize_button.configure(state="normal" if exists else "disabled")
        self._set_status("" if exists else self._config.text("results_tab.no_rch_hint"))

    # -- Organize .rch (hilo de fondo) --------------------------------------

    def _on_organize_clicked(self) -> None:
        if self._project_dir is None:
            return

        project_dir = self._project_dir
        rch_path = self._rch_path()
        cio_path = project_dir / "TxtInOut" / "file.cio"

        self._set_controls_enabled(False)
        self._set_status(self._config.text("results_tab.organizing"))
        self._on_run_state_changed(True)

        def work(report_progress: Callable[[str], None]) -> dict:
            report_progress(self._config.text("results_tab.organizing"))
            run_settings = parse_run_settings(cio_path)
            raw = parse_rch_file(rch_path)
            timeseries = build_rch_timeseries(raw, run_settings)
            dest_dir = rch_timeseries_dir(project_dir)
            written = export_rch_timeseries_csvs(timeseries, dest_dir)
            log_action(project_dir, "RESULTS_RCH", f"Organized output.rch: {len(written)} reach(es) written to '{dest_dir}'.")
            return {"timeseries": timeseries, "written": written, "dest_dir": dest_dir}

        run_in_background(
            self,
            work,
            on_progress=lambda message: self._set_status(message),
            on_done=self._on_organize_done,
            on_error=self._on_organize_error,
        )

    def _on_organize_done(self, result: dict) -> None:
        self._timeseries = result["timeseries"]
        self._refresh_selectors()
        self._set_status(
            self._config.text("results_tab.organize_success").format(
                reaches=len(result["written"]), path=str(result["dest_dir"])
            )
        )
        self._finish_organize()

    def _on_organize_error(self, error: Exception) -> None:
        if isinstance(error, CioParseError):
            message = self._config.text("results_tab.period_error").format(error=str(error))
        else:
            message = self._config.text("results_tab.organize_error").format(error=str(error))
        self._set_status(message, error=True)
        self._finish_organize()

    def _finish_organize(self) -> None:
        self._set_controls_enabled(True)
        self._on_run_state_changed(False)

    def _set_controls_enabled(self, enabled: bool) -> None:
        # No reusa _refresh_organize_availability: esa además pisa el status
        # label con el hint de "no output.rch" -- acá el status ya lo dejó
        # con el resultado de Organize (éxito o error), que no debe perderse
        # al reactivar los controles.
        can_organize = enabled and self._rch_path().is_file()
        self._organize_button.configure(state="normal" if can_organize else "disabled")
        self._open_folder_button.configure(state="normal" if enabled else "disabled")
        self._reach_selector.configure(state="readonly" if enabled else "disabled")
        self._variable_selector.configure(state="readonly" if enabled else "disabled")

    # -- selectores + gráfica -------------------------------------------------

    def _refresh_selectors(self) -> None:
        if self._timeseries.empty:
            self._reach_selector.configure(values=[])
            self._reach_selector.set("")
            self._refresh_chart()
            return

        reach_ids = sorted(int(r) for r in self._timeseries["reach"].unique())
        reach_labels = [str(r) for r in reach_ids]
        self._reach_selector.configure(values=reach_labels)
        if self._reach_selector.get() not in reach_labels:
            self._reach_selector.set(reach_labels[0])

        if not self._variable_selector.get():
            default_code = _DEFAULT_VARIABLE if _DEFAULT_VARIABLE in RCH_VARIABLE_COLUMNS else RCH_VARIABLE_COLUMNS[0]
            self._variable_selector.set(self._variable_code_to_label[default_code])

        self._refresh_chart()

    def _on_selection_changed(self, _event=None) -> None:
        self._refresh_chart()
        self._refresh_map()

    def _refresh_chart(self) -> None:
        reach_value = self._reach_selector.get()
        variable_label = self._variable_selector.get()

        if self._timeseries.empty or not reach_value or not variable_label:
            self._chart_canvas_frame.pack_forget()
            self._chart_empty_label.pack(anchor="w")
            return

        self._chart_empty_label.pack_forget()

        reach_id = int(reach_value)
        variable_code = self._variable_label_to_code[variable_label]
        subset = self._timeseries[self._timeseries["reach"] == reach_id].sort_values("date")
        series = subset.set_index("date")[variable_code]

        figure = build_rch_timeseries_figure(
            series,
            line_color=self._colors.get("accent"),
            grid_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"),
            muted_color=self._colors.get("text_secondary"),
            y_axis_label=variable_label,
            title=self._config.text("results_tab.chart_title").format(reach=reach_id, variable=variable_label),
        )

        if self._chart_canvas is not None:
            self._chart_canvas.get_tk_widget().destroy()
        self._chart_canvas = FigureCanvasTkAgg(figure, master=self._chart_canvas_frame)
        self._chart_canvas.draw()
        self._chart_canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)
        self._chart_canvas_frame.pack(fill="x")

    # -- mapa estático (viz.shapefile_map) ------------------------------------

    def _load_map_shapes(self) -> None:
        self._subbasin_shapes = None
        self._reach_shapes = None
        self._map_error = None

        if not self._metadata.subbasin_shp_path or not self._metadata.reach_shp_path:
            return

        try:
            self._subbasin_shapes = read_subbasin_shapes(self._metadata.subbasin_shp_path)
            self._reach_shapes = read_reach_shapes(self._metadata.reach_shp_path)
        except (ShapefileReadError, OSError) as error:
            self._map_error = str(error)

    def _refresh_map(self) -> None:
        if self._map_error is not None:
            self._show_map_hint(self._config.text("results_tab.map_error").format(error=self._map_error))
            return
        if self._subbasin_shapes is None or self._reach_shapes is None:
            self._show_map_hint(self._config.text("results_tab.map_missing_hint"))
            return

        reach_value = self._reach_selector.get()
        highlighted_id = int(reach_value) if reach_value else None

        figure = build_shapefile_map_figure(
            self._subbasin_shapes,
            self._reach_shapes,
            highlighted_id,
            fill_color=self._colors.get("surface"),
            highlight_fill_color=self._colors.get("accent"),
            border_color=self._colors.get("border"),
            reach_color=self._colors.get("text_secondary"),
            highlight_reach_color=self._colors.get("error"),
            background_color="#FFFFFF",
        )

        self._map_hint_label.pack_forget()
        if self._map_canvas is not None:
            self._map_canvas.get_tk_widget().destroy()
        self._map_canvas = FigureCanvasTkAgg(figure, master=self._map_canvas_frame)
        self._map_canvas.draw()
        self._map_canvas.get_tk_widget().pack(padx=8, pady=8)
        self._map_canvas_frame.pack(padx=12, pady=(0, 12))

    def _show_map_hint(self, text: str) -> None:
        self._map_canvas_frame.pack_forget()
        self._map_hint_label.configure(text=text)
        self._map_hint_label.pack(anchor="w", padx=12, pady=(0, 12))

    # -- status ---------------------------------------------------------------

    def _set_status(self, text: str, *, error: bool = False) -> None:
        color_key = "error" if error else "text_secondary"
        self._status_label.configure(text=text, text_color=self._colors.get(color_key))
