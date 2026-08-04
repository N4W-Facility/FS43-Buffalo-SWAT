"""Pestaña HRU Results (output.hru): organiza el balance por HRU de SWAT en
una base SQLite (swat_io.hru_output_parser, ver su docstring para el porqué
de SQLite en vez de CSV como Results/.rch -- output.hru puede tener miles
de HRU y pesar más de 1GB en salida Daily), y permite explorarlo con
selectores encadenados subcuenca -> HRU -> variable (gráfica) más dos
exports CSV: la serie de un único HRU, o una variable para todas las HRU de
una subcuenca (formato ancho: fecha + una columna por HRU).

A diferencia de ResultsTab (output.rch), esta pestaña nunca mantiene la
serie completa en memoria: solo cachea la lista de subcuencas (chica) y
consulta SQLite bajo demanda (HRU de una subcuenca, serie de un HRU) --
igual filosofía de streaming que el propio parser, para que ni siquiera la
UI post-procesamiento cargue el archivo completo a memoria.

"Organize .hru output" corre en hilo de fondo (ui.tasks.run_in_background,
igual que ResultsTab) y no toca ningún archivo de TxtInOut, así que no pide
confirmación. Sin mapa -- pedido explícito del usuario (2026-08-03): "no
quiero nada espacial", a diferencia de Results/.rch que sí tiene mapa
estático.

Deshabilitada hasta que haya un proyecto abierto; igual que ResultsTab,
queda habilitada aunque output.hru todavía no exista (el botón Organize
queda deshabilitado con un hint en ese caso, sin bloquear toda la pestaña).
"""
from __future__ import annotations

import os
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Callable

import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from config.settings import ConfigManager
from swat_io.cio_parser import CioParseError, parse_run_settings
from swat_io.hru_output_parser import (
    HRU_OUTPUT_VARIABLE_COLUMNS,
    build_hru_output_database,
    export_hru_variables_csv,
    export_single_series_csv,
    export_subbasin_variable_csv,
    hru_output_db_path,
    list_hrus_for_subbasin,
    list_subbasins,
    read_hru_series,
)
from viz.rch_chart import build_rch_timeseries_figure

from .tasks import run_in_background
from .variable_selection_window import VariableSelectionWindow
from .widgets import palette, style_combobox

_DEFAULT_VARIABLE = "WYLD"


class HruResultsTab(ctk.CTkFrame):
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
        self._db_path: Path | None = None
        self._subbasins: list[int] = []

        self._variable_code_to_label = {
            code: self._config.text(f"hru_out_var.{code}") for code in HRU_OUTPUT_VARIABLE_COLUMNS
        }
        self._variable_label_to_code = {label: code for code, label in self._variable_code_to_label.items()}

        self._chart_canvas: FigureCanvasTkAgg | None = None

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
            text=self._config.text("hru_results_tab.title"),
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
            text=self._config.text("hru_results_tab.organize_button"),
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

        self._subbasin_selector = self._build_selector(selectors, "hru_results_tab.subbasin_label", column=0, width=8)
        self._subbasin_selector.bind("<<ComboboxSelected>>", self._on_subbasin_changed)

        self._hru_selector = self._build_selector(selectors, "hru_results_tab.hru_label", column=1, width=8)
        self._hru_selector.bind("<<ComboboxSelected>>", self._on_selection_changed)

        self._variable_selector = self._build_selector(
            selectors, "hru_results_tab.variable_label", column=2, width=48
        )
        self._variable_selector.configure(values=list(self._variable_code_to_label.values()))
        self._variable_selector.bind("<<ComboboxSelected>>", self._on_selection_changed)

        chart_card = ctk.CTkFrame(frame, fg_color="transparent")
        chart_card.grid(row=4, column=0, sticky="ew", pady=(16, 0))

        self._chart_empty_label = ctk.CTkLabel(
            chart_card,
            text=self._config.text("hru_results_tab.chart_empty_hint"),
            text_color=self._colors.get("text_secondary"),
            anchor="w",
        )
        self._chart_empty_label.pack(anchor="w")

        self._chart_canvas_frame = ctk.CTkFrame(chart_card, fg_color=self._colors.get("surface"))

        export_row = ctk.CTkFrame(frame, fg_color="transparent")
        export_row.grid(row=5, column=0, sticky="w", pady=(12, 0))

        self._export_series_button = ctk.CTkButton(
            export_row,
            text=self._config.text("hru_results_tab.export_series_button"),
            command=self._on_export_series_clicked,
            state="disabled",
        )
        self._export_series_button.grid(row=0, column=0, sticky="w", padx=(0, 8))

        self._export_subbasin_button = ctk.CTkButton(
            export_row,
            text=self._config.text("hru_results_tab.export_subbasin_button"),
            command=self._on_export_subbasin_clicked,
            state="disabled",
        )
        self._export_subbasin_button.grid(row=0, column=1, sticky="w")

        self._export_all_variables_button = ctk.CTkButton(
            export_row,
            text=self._config.text("hru_results_tab.export_all_variables_button"),
            command=self._on_export_all_variables_clicked,
            state="disabled",
        )
        self._export_all_variables_button.grid(row=0, column=2, sticky="w", padx=(8, 0))

        self._export_selected_variables_button = ctk.CTkButton(
            export_row,
            text=self._config.text("hru_results_tab.export_selected_variables_button"),
            command=self._on_export_selected_variables_clicked,
            state="disabled",
        )
        self._export_selected_variables_button.grid(row=0, column=3, sticky="w", padx=(8, 0))

        return frame

    def _build_selector(self, master: ctk.CTkBaseClass, label_key: str, *, column: int, width: int) -> ttk.Combobox:
        label = ctk.CTkLabel(
            master,
            text=self._config.text(label_key).upper(),
            text_color=self._colors.get("text_secondary"),
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        label.grid(row=0, column=column, sticky="w")
        selector = ttk.Combobox(master, style=style_combobox(self._config), state="readonly", values=[], width=width)
        selector.grid(row=1, column=column, sticky="w", padx=(0, 16))
        return selector

    # -- estado del proyecto -----------------------------------------------

    def set_project(self, project_dir: Path) -> None:
        self._project_dir = project_dir
        self._db_path = hru_output_db_path(project_dir)
        self._enabled_state.pack(fill="both", expand=True)
        self._disabled_state.pack_forget()

        self._refresh_organize_availability()
        self._load_subbasins_from_db()

    def _hru_output_path(self) -> Path:
        return self._project_dir / "TxtInOut" / "output.hru"

    def _on_open_folder_clicked(self) -> None:
        if self._db_path is None:
            return
        os.startfile(self._db_path.parent)  # solo Windows: target de distribución del proyecto

    def _refresh_organize_availability(self) -> None:
        exists = self._hru_output_path().is_file()
        self._organize_button.configure(state="normal" if exists else "disabled")
        self._set_status("" if exists else self._config.text("hru_results_tab.no_hru_output_hint"))

    def _load_subbasins_from_db(self) -> None:
        self._subbasins = list_subbasins(self._db_path) if self._db_path is not None else []
        self._refresh_subbasin_selector()

    # -- Organize .hru output (hilo de fondo) --------------------------------

    def _on_organize_clicked(self) -> None:
        if self._project_dir is None or self._db_path is None:
            return

        project_dir = self._project_dir
        hru_path = self._hru_output_path()
        db_path = self._db_path
        cio_path = project_dir / "TxtInOut" / "file.cio"

        self._set_controls_enabled(False)
        self._set_status(self._config.text("hru_results_tab.organizing"))
        self._on_run_state_changed(True)

        def work(report_progress: Callable[[str], None]) -> dict:
            report_progress(self._config.text("hru_results_tab.organizing"))
            run_settings = parse_run_settings(cio_path)
            return build_hru_output_database(hru_path, run_settings, db_path, report_progress=report_progress)

        run_in_background(
            self,
            work,
            on_progress=lambda message: self._set_status(message),
            on_done=self._on_organize_done,
            on_error=self._on_organize_error,
        )

    def _on_organize_done(self, result: dict) -> None:
        self._load_subbasins_from_db()
        self._set_status(
            self._config.text("hru_results_tab.organize_success").format(
                rows=result["rows"], hrus=result["hrus"], subbasins=result["subbasins"]
            )
        )
        self._finish_organize()

    def _on_organize_error(self, error: Exception) -> None:
        if isinstance(error, CioParseError):
            message = self._config.text("hru_results_tab.period_error").format(error=str(error))
        else:
            message = self._config.text("hru_results_tab.organize_error").format(error=str(error))
        self._set_status(message, error=True)
        self._finish_organize()

    def _finish_organize(self) -> None:
        self._set_controls_enabled(True)
        self._on_run_state_changed(False)

    def _set_controls_enabled(self, enabled: bool) -> None:
        can_organize = enabled and self._hru_output_path().is_file()
        self._organize_button.configure(state="normal" if can_organize else "disabled")
        self._open_folder_button.configure(state="normal" if enabled else "disabled")
        self._subbasin_selector.configure(state="readonly" if enabled else "disabled")
        self._hru_selector.configure(state="readonly" if enabled else "disabled")
        self._variable_selector.configure(state="readonly" if enabled else "disabled")
        self._refresh_export_buttons_enabled(enabled)

    # -- selectores encadenados + gráfica -------------------------------------

    def _refresh_subbasin_selector(self) -> None:
        labels = [str(s) for s in self._subbasins]
        self._subbasin_selector.configure(values=labels)
        if not labels:
            self._subbasin_selector.set("")
            self._hru_selector.configure(values=[])
            self._hru_selector.set("")
            self._refresh_chart()
            return

        if self._subbasin_selector.get() not in labels:
            self._subbasin_selector.set(labels[0])

        if not self._variable_selector.get():
            default_code = _DEFAULT_VARIABLE if _DEFAULT_VARIABLE in HRU_OUTPUT_VARIABLE_COLUMNS else HRU_OUTPUT_VARIABLE_COLUMNS[0]
            self._variable_selector.set(self._variable_code_to_label[default_code])

        self._refresh_hru_selector()

    def _on_subbasin_changed(self, _event=None) -> None:
        self._refresh_hru_selector()

    def _refresh_hru_selector(self) -> None:
        subbasin_value = self._subbasin_selector.get()
        if not subbasin_value or self._db_path is None:
            self._hru_selector.configure(values=[])
            self._hru_selector.set("")
            self._refresh_chart()
            return

        hru_ids = list_hrus_for_subbasin(self._db_path, int(subbasin_value))
        labels = [str(h) for h in hru_ids]
        self._hru_selector.configure(values=labels)
        if self._hru_selector.get() not in labels:
            self._hru_selector.set(labels[0] if labels else "")

        self._refresh_chart()

    def _on_selection_changed(self, _event=None) -> None:
        self._refresh_chart()

    def _current_selection(self) -> tuple[int, int, str] | None:
        subbasin_value = self._subbasin_selector.get()
        hru_value = self._hru_selector.get()
        variable_label = self._variable_selector.get()
        if not subbasin_value or not hru_value or not variable_label or self._db_path is None:
            return None
        return int(subbasin_value), int(hru_value), self._variable_label_to_code[variable_label]

    def _current_hru(self) -> tuple[int, int] | None:
        """Subcuenca + HRU elegidos, sin requerir una variable seleccionada --
        a diferencia de _current_selection, la usan los dos exports que no
        dependen de qué variable esté graficada (todas las variables /
        selección por checkbox)."""
        subbasin_value = self._subbasin_selector.get()
        hru_value = self._hru_selector.get()
        if not subbasin_value or not hru_value or self._db_path is None:
            return None
        return int(subbasin_value), int(hru_value)

    def _refresh_chart(self) -> None:
        selection = self._current_selection()
        self._refresh_export_buttons_enabled(True)

        if selection is None:
            self._chart_canvas_frame.pack_forget()
            self._chart_empty_label.pack(anchor="w")
            return

        sub, hru, variable_code = selection
        variable_label = self._variable_selector.get()
        series = read_hru_series(self._db_path, hru, variable_code)
        if series.empty:
            self._chart_canvas_frame.pack_forget()
            self._chart_empty_label.pack(anchor="w")
            return

        self._chart_empty_label.pack_forget()

        figure = build_rch_timeseries_figure(
            series,
            line_color=self._colors.get("accent"),
            grid_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"),
            muted_color=self._colors.get("text_secondary"),
            y_axis_label=variable_label,
            title=self._config.text("hru_results_tab.chart_title").format(sub=sub, hru=hru, variable=variable_label),
        )

        if self._chart_canvas is not None:
            self._chart_canvas.get_tk_widget().destroy()
        self._chart_canvas = FigureCanvasTkAgg(figure, master=self._chart_canvas_frame)
        self._chart_canvas.draw()
        self._chart_canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)
        self._chart_canvas_frame.pack(fill="x")

    def _refresh_export_buttons_enabled(self, controls_enabled: bool) -> None:
        selection = self._current_selection() if controls_enabled else None
        hru_selection = self._current_hru() if controls_enabled else None
        state = "normal" if selection is not None else "disabled"
        hru_state = "normal" if hru_selection is not None else "disabled"
        self._export_series_button.configure(state=state)
        self._export_subbasin_button.configure(state=state)
        self._export_all_variables_button.configure(state=hru_state)
        self._export_selected_variables_button.configure(state=hru_state)

    # -- exports CSV ------------------------------------------------------

    def _on_export_series_clicked(self) -> None:
        selection = self._current_selection()
        if selection is None:
            return
        sub, hru, variable_code = selection

        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile=f"hru_{hru}_{variable_code}.csv",
        )
        if not path:
            return

        try:
            export_single_series_csv(self._db_path, hru, variable_code, Path(path))
        except OSError as error:
            self._set_status(self._config.text("hru_results_tab.export_error").format(error=str(error)), error=True)
            return
        self._set_status(self._config.text("hru_results_tab.export_success").format(path=path))

    def _on_export_subbasin_clicked(self) -> None:
        selection = self._current_selection()
        if selection is None:
            return
        sub, _hru, variable_code = selection

        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile=f"subbasin_{sub}_{variable_code}.csv",
        )
        if not path:
            return

        try:
            export_subbasin_variable_csv(self._db_path, sub, variable_code, Path(path))
        except OSError as error:
            self._set_status(self._config.text("hru_results_tab.export_error").format(error=str(error)), error=True)
            return
        self._set_status(self._config.text("hru_results_tab.export_success").format(path=path))

    def _on_export_all_variables_clicked(self) -> None:
        hru_selection = self._current_hru()
        if hru_selection is None:
            return
        _sub, hru = hru_selection

        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile=f"hru_{hru}_all_variables.csv",
        )
        if not path:
            return

        try:
            export_hru_variables_csv(self._db_path, hru, HRU_OUTPUT_VARIABLE_COLUMNS, Path(path))
        except OSError as error:
            self._set_status(self._config.text("hru_results_tab.export_error").format(error=str(error)), error=True)
            return
        self._set_status(self._config.text("hru_results_tab.export_success").format(path=path))

    def _on_export_selected_variables_clicked(self) -> None:
        hru_selection = self._current_hru()
        if hru_selection is None:
            return
        _sub, hru = hru_selection

        options = [(code, self._variable_code_to_label[code]) for code in HRU_OUTPUT_VARIABLE_COLUMNS]

        def on_confirm(selected_codes: list[str]) -> None:
            path = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV", "*.csv")],
                initialfile=f"hru_{hru}_selected_variables.csv",
            )
            if not path:
                return
            try:
                export_hru_variables_csv(self._db_path, hru, selected_codes, Path(path))
            except OSError as error:
                self._set_status(self._config.text("hru_results_tab.export_error").format(error=str(error)), error=True)
                return
            self._set_status(self._config.text("hru_results_tab.export_success").format(path=path))

        VariableSelectionWindow(
            self,
            self._config,
            title_key="hru_results_tab.select_variables_window_title",
            options=options,
            on_confirm=on_confirm,
        )

    # -- status ---------------------------------------------------------------

    def _set_status(self, text: str, *, error: bool = False) -> None:
        color_key = "error" if error else "text_secondary"
        self._status_label.configure(text=text, text_color=self._colors.get(color_key))
