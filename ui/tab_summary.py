"""Pestaña Summary: corre los dos resúmenes existentes y muestra el panel
agregado, cacheado en project.json (con su generated_at) para no
recalcular al reabrir el proyecto.

Deshabilitada (vía TabBar.set_enabled) hasta que haya un proyecto abierto.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from tkinter import ttk
from typing import Callable

import customtkinter as ctk
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from config.settings import ConfigManager
from generar_resumen_coberturas import build_land_use_summary
from scenarios.project import ProjectMetadata, SummaryEntry, save_project
from swat_io.cio_parser import CioParseError, parse_file_cio
from swat_io.hru.summary import (
    export_land_use_summary_csv,
    land_use_percentages,
    read_land_use_summary_csv,
    subbasin_area_km2,
)
from swat_io.stats import HruStats, WetlandStats, hru_stats_from_summary, wetland_stats_from_summary
from swat_io.summary import summarize_project
from swat_io.tool_outputs import save_wetland_summary, tool_outputs_dir
from viz.land_use_chart import build_land_use_figure

from .tasks import run_in_background
from .widgets import SectionHeader, StatCard, palette, style_combobox

_LAND_USE_CSV_NAME = "land_use_by_subbasin.csv"

_GROUP_TITLE_KEYS = {"wetlands": "summary.group_wetlands", "hru": "summary.group_hru"}

# Animación propia de la barra de progreso, en vez del modo "indeterminate"
# nativo de CTkProgressBar: ese modo corre su propio bucle after() a un
# intervalo muy corto (redibuja constantemente) y, contra un modelo real con
# miles de .hru, esa carga extra en el hilo principal compite por el GIL con
# el hilo de fondo y multiplica el tiempo total de la corrida varias veces
# (medido: ~5x más lento, con cortes de hasta 2s). Un vaivén simple atado al
# mismo intervalo de sondeo (150ms) que ya usa ui.tasks.run_in_background no
# agrega un bucle rápido nuevo y no reproduce el problema.
_PROGRESS_MIN = 0.15
_PROGRESS_MAX = 0.85
_PROGRESS_STEP = 0.05
_PROGRESS_INTERVAL_MS = 150


class SummaryTab(ctk.CTkFrame):
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
        self._stat_specs: list[dict] = config.load_layout("summary_stats")["stats"]

        self._project_dir: Path | None = None
        self._metadata: ProjectMetadata = ProjectMetadata()

        self._land_use_df: pd.DataFrame | None = None
        self._chart_canvas: FigureCanvasTkAgg | None = None
        self._chart_values_to_subbasin: dict[str, int] = {}

        self._disabled_state = self._build_disabled_state()
        self._enabled_state = self._build_enabled_state()
        self._disabled_state.pack(fill="both", expand=True)

    # -- construcción --------------------------------------------------

    def _build_disabled_state(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        hint = ctk.CTkLabel(
            frame,
            text=self._config.text("summary.disabled_hint"),
            text_color=self._colors.get("text_secondary"),
        )
        hint.place(relx=0.5, rely=0.4, anchor="center")
        return frame

    def _build_check_with_hint(self, master: ctk.CTkBaseClass, label_key: str, hint_key: str) -> ctk.CTkCheckBox:
        """Checkbox tildada por default (para que "Run" haga algo útil sin
        que el usuario tenga que adivinar que hay que tildar algo antes) más
        una línea chica debajo diciendo qué calcula -- pedido explícito del
        usuario, 2026-08-13: antes ninguna de las dos casillas indicaba qué
        generaba, y ambas arrancaban destildadas, así que un primer click en
        Run sin tocar nada no hacía nada (ver _on_run_clicked)."""
        holder = ctk.CTkFrame(master, fg_color="transparent")
        holder.pack(side="left", padx=(0, 16))

        check = ctk.CTkCheckBox(holder, text=self._config.text(label_key))
        check.pack(anchor="w")
        check.select()

        hint = ctk.CTkLabel(
            holder,
            text=self._config.text(hint_key),
            text_color=self._colors.get("text_secondary"),
            font=ctk.CTkFont(size=11),
            anchor="w",
        )
        hint.pack(anchor="w")

        return check

    def _build_enabled_state(self) -> ctk.CTkFrame:
        # Scrollable en vez de CTkFrame plano: con los tres bloques (Wetlands,
        # HRU, Gráficas) más el canvas de matplotlib, el contenido puede
        # superar el alto de la ventana en pantallas chicas.
        frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        frame.columnconfigure(0, weight=1)

        controls = ctk.CTkFrame(frame, fg_color="transparent")
        controls.grid(row=0, column=0, sticky="ew")

        self._wetlands_check = self._build_check_with_hint(
            controls, "summary.check_wetlands", "summary.check_wetlands_hint"
        )
        self._hru_check = self._build_check_with_hint(controls, "summary.check_hru", "summary.check_hru_hint")

        self._run_button = ctk.CTkButton(
            controls, text=self._config.text("summary.run"), command=self._on_run_clicked
        )
        self._run_button.pack(side="right")

        self._progress_bar = ctk.CTkProgressBar(
            frame,
            height=3,
            corner_radius=1,
            fg_color=self._colors.get("border"),
            progress_color=self._colors.get("accent"),
        )
        self._progress_bar.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self._progress_bar.grid_remove()
        self._progress_animation_running = False
        self._progress_value = _PROGRESS_MIN
        self._progress_direction = 1

        self._status_label = ctk.CTkLabel(
            frame, text="", text_color=self._colors.get("text_secondary"), anchor="w"
        )
        self._status_label.grid(row=2, column=0, sticky="ew", pady=(6, 0))

        separator = ctk.CTkFrame(frame, height=1, fg_color=self._colors.get("border"))
        separator.grid(row=3, column=0, sticky="ew", pady=12)

        groups_container = ctk.CTkFrame(frame, fg_color="transparent")
        groups_container.grid(row=4, column=0, sticky="new")
        groups_container.columnconfigure(0, weight=1)

        self._group_headers: dict[str, SectionHeader] = {}
        self._group_cards: dict[str, dict[str, StatCard]] = {"wetlands": {}, "hru": {}}
        self._open_output_buttons: list[ctk.CTkButton] = []

        row = 0
        for group_key, title_key in _GROUP_TITLE_KEYS.items():
            header_row = ctk.CTkFrame(groups_container, fg_color="transparent")
            header_row.grid(row=row, column=0, sticky="ew", pady=(0 if row == 0 else 16, 4))
            header_row.columnconfigure(0, weight=1)

            header = SectionHeader(header_row, self._config, title_key)
            header.grid(row=0, column=0, sticky="ew")
            self._group_headers[group_key] = header

            open_button = ctk.CTkButton(
                header_row,
                text=self._config.text("summary.open_output_folder"),
                fg_color="transparent",
                border_width=1,
                border_color=self._colors.get("border"),
                text_color=self._colors.get("text_primary"),
                hover_color=self._colors.get("window_bg"),
                command=lambda g=group_key: self._open_output_folder(g),
            )
            open_button.grid(row=0, column=1, sticky="e", padx=(12, 0))
            self._open_output_buttons.append(open_button)

            cards_row = ctk.CTkFrame(groups_container, fg_color="transparent")
            cards_row.grid(row=row + 1, column=0, sticky="ew")

            specs_for_group = [spec for spec in self._stat_specs if spec["group"] == group_key]
            for col, spec in enumerate(specs_for_group):
                card = StatCard(cards_row, self._config, spec["label_key"])
                card.grid(row=0, column=col, padx=(0 if col == 0 else 8, 0), sticky="w")
                self._group_cards[group_key][spec["id"]] = card

            row += 2

        charts_header_row = ctk.CTkFrame(groups_container, fg_color="transparent")
        charts_header_row.grid(row=row, column=0, sticky="ew", pady=(16, 4))
        charts_header_row.columnconfigure(0, weight=1)
        self._charts_header = SectionHeader(charts_header_row, self._config, "summary.group_charts")
        self._charts_header.grid(row=0, column=0, sticky="ew")

        charts_body = ctk.CTkFrame(groups_container, fg_color="transparent")
        charts_body.grid(row=row + 1, column=0, sticky="ew")
        charts_body.columnconfigure(0, weight=1)

        self._chart_empty_label = ctk.CTkLabel(
            charts_body,
            text=self._config.text("summary.chart_empty_hint"),
            text_color=self._colors.get("text_secondary"),
            anchor="w",
        )
        self._chart_empty_label.grid(row=0, column=0, sticky="w")

        self._chart_selector = ttk.Combobox(
            charts_body, style=style_combobox(self._config), state="readonly", values=[], width=20
        )
        self._chart_selector.grid(row=0, column=0, sticky="w")
        self._chart_selector.grid_remove()
        self._chart_selector.bind("<<ComboboxSelected>>", self._on_chart_subbasin_selected)

        self._chart_canvas_frame = ctk.CTkFrame(charts_body, fg_color=self._colors.get("surface"))
        self._chart_canvas_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self._chart_canvas_frame.grid_remove()

        return frame

    # -- estado del proyecto ---------------------------------------------

    def set_project(self, project_dir: Path, metadata: ProjectMetadata) -> None:
        self._project_dir = project_dir
        self._metadata = metadata
        self._enabled_state.pack(fill="both", expand=True)
        self._disabled_state.pack_forget()
        self._render_cached_summary()

        csv_path = tool_outputs_dir(project_dir) / _LAND_USE_CSV_NAME
        self._land_use_df = read_land_use_summary_csv(csv_path) if csv_path.exists() else None
        self._refresh_chart_selector()

    def _render_cached_summary(self) -> None:
        self._render_group("wetlands", self._metadata.wetlands)
        self._render_group("hru", self._metadata.hru)

    def _render_group(self, group_key: str, entry: SummaryEntry | None) -> None:
        header = self._group_headers[group_key]
        cards = self._group_cards[group_key]

        if entry is None:
            header.set_timestamp(self._config.text("summary.never"))
            for card in cards.values():
                card.set_value(None)
            return

        header.set_timestamp(self._config.text("summary.generated_at").format(timestamp=entry.generated_at))
        specs_by_id = {spec["id"]: spec for spec in self._stat_specs if spec["group"] == group_key}
        for stat_id, card in cards.items():
            spec = specs_by_id[stat_id]
            value = entry.stats.get(spec["source"])
            card.set_value(_format_stat(value, spec, self._config))

    def _open_output_folder(self, group_key: str) -> None:  # noqa: ARG002 - mismo folder para ambos grupos
        if self._project_dir is None:
            return
        os.startfile(tool_outputs_dir(self._project_dir))  # solo Windows: target de distribución del proyecto

    # -- Gráfica de coberturas ---------------------------------------------

    def _refresh_chart_selector(self) -> None:
        if self._land_use_df is None or self._land_use_df.empty:
            self._chart_selector.grid_remove()
            self._chart_canvas_frame.grid_remove()
            self._chart_empty_label.grid()
            return

        self._chart_empty_label.grid_remove()

        subbasins = sorted(self._land_use_df["subbasin"].unique())
        total_label = self._config.text("summary.chart_total_watershed")
        subbasin_labels = [self._config.text("summary.chart_subbasin_label").format(id=s) for s in subbasins]
        self._chart_values_to_subbasin = dict(zip(subbasin_labels, subbasins))

        self._chart_selector.configure(values=[total_label] + subbasin_labels)
        self._chart_selector.set(total_label)
        self._chart_selector.grid()
        self._chart_canvas_frame.grid()
        self._render_chart(None, total_label)

    def _on_chart_subbasin_selected(self, _event=None) -> None:
        value = self._chart_selector.get()
        self._render_chart(self._chart_values_to_subbasin.get(value), value)

    def _render_chart(self, subbasin: int | None, label: str) -> None:
        categories = sorted(self._land_use_df["land_use"].dropna().unique())
        percentages = land_use_percentages(self._land_use_df, subbasin, categories=categories)
        area_km2 = subbasin_area_km2(self._land_use_df, subbasin)
        title = self._config.text("summary.chart_title").format(
            label=label, area=area_km2, unit=self._config.text("unit.km2")
        )

        figure = build_land_use_figure(
            percentages,
            bar_color=self._colors.get("accent"),
            grid_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"),
            muted_color=self._colors.get("text_secondary"),
            y_axis_label=self._config.text("summary.chart_y_axis"),
            title=title,
        )

        if self._chart_canvas is not None:
            self._chart_canvas.get_tk_widget().destroy()
        self._chart_canvas = FigureCanvasTkAgg(figure, master=self._chart_canvas_frame)
        self._chart_canvas.draw()
        self._chart_canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)

    # -- Run --------------------------------------------------------------

    def _on_run_clicked(self) -> None:
        if self._project_dir is None:
            return
        run_wetlands = bool(self._wetlands_check.get())
        run_hru = bool(self._hru_check.get())
        if not run_wetlands and not run_hru:
            self._set_status(self._config.text("summary.no_selection_hint"), error=True)
            return

        self._set_controls_enabled(False)
        self._set_status(self._config.text("summary.running"))
        self._progress_bar.grid()
        self._progress_value = _PROGRESS_MIN
        self._progress_direction = 1
        self._progress_bar.set(self._progress_value)
        self._progress_animation_running = True
        self.after(_PROGRESS_INTERVAL_MS, self._animate_progress)
        self._on_run_state_changed(True)

        project_dir = self._project_dir
        config = self._config

        def work(report_progress: Callable[[str], None]) -> dict:
            # Cada rama parsea TxtInOut una sola vez y reusa ese DataFrame
            # tanto para el CSV como para las estadísticas del panel — antes
            # se parseaba dos veces (una por generar_resumen_*, otra por
            # compute_*_stats), lo que duplicaba el tiempo que el hilo de
            # fondo pasaba compitiendo por CPU con la ventana.
            results: dict = {}
            txtinout_dir = project_dir / "TxtInOut"

            if run_wetlands:
                report_progress(config.text("summary.group_wetlands"))
                wetland_df = summarize_project(txtinout_dir)
                save_wetland_summary(project_dir, wetland_df)
                results["wetlands"] = _wetland_stats_to_dict(wetland_stats_from_summary(wetland_df))

            if run_hru:
                report_progress(config.text("summary.group_hru"))
                hru_summary_df, land_use_summary_df = build_land_use_summary(project_dir)
                export_land_use_summary_csv(
                    land_use_summary_df, tool_outputs_dir(project_dir) / _LAND_USE_CSV_NAME
                )
                try:
                    simulation_period = parse_file_cio(txtinout_dir / "file.cio")
                except (CioParseError, FileNotFoundError):
                    simulation_period = None
                results["hru"] = _hru_stats_to_dict(hru_stats_from_summary(hru_summary_df, simulation_period))
                results["land_use_df"] = land_use_summary_df

            return results

        run_in_background(
            self,
            work,
            on_progress=lambda message: self._set_status(message),
            on_done=self._on_run_done,
            on_error=self._on_run_error,
        )

    def _on_run_done(self, results: dict) -> None:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if "wetlands" in results:
            self._metadata.wetlands = SummaryEntry(generated_at=timestamp, stats=results["wetlands"])
        if "hru" in results:
            self._metadata.hru = SummaryEntry(generated_at=timestamp, stats=results["hru"])

        save_project(self._project_dir, self._metadata)
        self._render_cached_summary()

        if "land_use_df" in results:
            self._land_use_df = results["land_use_df"]
            self._refresh_chart_selector()

        self._set_status("")
        self._finish_run()

    def _on_run_error(self, error: Exception) -> None:
        self._set_status(self._config.text("summary.error").format(error=str(error)), error=True)
        self._finish_run()

    def _set_status(self, text: str, *, error: bool = False) -> None:
        color_key = "error" if error else "text_secondary"
        self._status_label.configure(text=text, text_color=self._colors.get(color_key))

    def _animate_progress(self) -> None:
        if not self._progress_animation_running:
            return
        self._progress_value += _PROGRESS_STEP * self._progress_direction
        if self._progress_value >= _PROGRESS_MAX:
            self._progress_value = _PROGRESS_MAX
            self._progress_direction = -1
        elif self._progress_value <= _PROGRESS_MIN:
            self._progress_value = _PROGRESS_MIN
            self._progress_direction = 1
        self._progress_bar.set(self._progress_value)
        self.after(_PROGRESS_INTERVAL_MS, self._animate_progress)

    def _finish_run(self) -> None:
        self._progress_animation_running = False
        self._progress_bar.grid_remove()
        self._set_controls_enabled(True)
        self._on_run_state_changed(False)

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self._wetlands_check.configure(state=state)
        self._hru_check.configure(state=state)
        self._run_button.configure(state=state)
        for button in self._open_output_buttons:
            button.configure(state=state)


def _format_stat(value: object, spec: dict, config: ConfigManager) -> str | None:
    fmt = spec["format"]
    if value is None:
        return None

    if fmt == "int":
        return f"{int(value)}"

    if fmt.startswith("float:"):
        decimals = int(fmt.split(":", 1)[1])
        text = f"{float(value):.{decimals}f}"
        unit_key = spec.get("unit_key")
        return f"{text} {config.text(unit_key)}" if unit_key else text

    if fmt.startswith("percent:"):
        decimals = int(fmt.split(":", 1)[1])
        return f"{float(value):.{decimals}f}{config.text('unit.pct')}"

    if fmt == "period":
        if not isinstance(value, dict) or value.get("start_year") is None:
            return None
        return f"{value['start_year']}-{value['end_year']}"

    return str(value)


def _wetland_stats_to_dict(stats: WetlandStats) -> dict:
    return {
        "subbasin_count": stats.subbasin_count,
        "total_area_km2": stats.total_area_km2,
        "wetland_area_ha": stats.wetland_area_ha,
        "wetland_coverage_pct": stats.wetland_coverage_pct,
        "subbasins_with_wetland": stats.subbasins_with_wetland,
    }


def _hru_stats_to_dict(stats: HruStats) -> dict:
    period = stats.simulation_period
    return {
        "hru_count": stats.hru_count,
        "land_use_count": stats.land_use_count,
        "simulation_period": (
            {"start_year": period.start_year, "end_year": period.end_year, "n_years": period.n_years}
            if period is not None
            else None
        ),
    }
