"""Pestaña Batch Scenarios: corre una serie de escenarios de cambio de
cobertura (ej. "aumentar bosque a 10%, 20%, 30% del área de cada
subcuenca") sobre copias aisladas del proyecto abierto, en hilo de fondo
(ui.tasks.run_in_background -- CLAUDE.md exige esto para cualquier
operación larga; acá son N copias de proyecto + N corridas de SWAT
+ N post-procesamientos encadenados).

El proyecto abierto es siempre la referencia (engine.batch_run.
run_land_cover_batch nunca la modifica); cada paso de la serie se calcula
de forma independiente desde ella, nunca encadenado (ver
scenarios.land_cover_reallocation). El usuario elige una carpeta destino
(fuera del proyecto) y un CSV de configuración
(scenarios.land_cover_config.parse_land_cover_batch_csv); cada paso
resultante queda en <destino>/scenario_<pct>pct/, con TxtInOut/ directo y
sus salidas ya organizadas (resumen de coberturas/humedales,
output.rch/output.hru) -- listo para abrirse como proyecto en la app, sin
pasos manuales adicionales.

Como esto copia carpetas y corre swat2012.exe varias veces, "Run batch"
pide confirmación (a diferencia de Organize en Results/HRU Results, que no
toca ningún archivo de TxtInOut del proyecto abierto -- acá si bien la
referencia tampoco se toca, sí se ejecuta el motor de cómputo real sobre
cada copia).

Deshabilitada (vía TabBar.set_enabled) hasta que haya un proyecto abierto.
"""
from __future__ import annotations

import os
from pathlib import Path
from tkinter import filedialog
from typing import Callable

import customtkinter as ctk

from config.settings import ConfigManager, validate_swat_executable
from engine.batch_run import ScenarioRunResult, run_land_cover_batch, scenario_folder_name
from scenarios.land_cover_config import (
    LandCoverBatchConfig,
    parse_land_cover_batch_csv,
    write_land_cover_batch_template_csv,
)

from .dialog_confirm import ConfirmDialog
from .tasks import run_in_background
from .widgets import ReadOnlyField, palette


class BatchTab(ctk.CTkFrame):
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
        self._destination_dir: Path | None = None
        self._batch_config: LandCoverBatchConfig | None = None

        self._disabled_state = self._build_disabled_state()
        self._enabled_state = self._build_enabled_state()
        self._disabled_state.pack(fill="both", expand=True)

    # -- construcción ---------------------------------------------------

    def _build_disabled_state(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        hint = ctk.CTkLabel(
            frame, text=self._config.text("batch_tab.disabled_hint"), text_color=self._colors.get("text_secondary")
        )
        hint.place(relx=0.5, rely=0.4, anchor="center")
        return frame

    def _build_enabled_state(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            frame,
            text=self._config.text("batch_tab.title"),
            text_color=self._colors.get("accent"),
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        )
        title.grid(row=0, column=0, sticky="w", pady=(0, 12))

        config_card = ctk.CTkFrame(frame)
        config_card.grid(row=1, column=0, sticky="ew")
        config_card.columnconfigure(0, weight=1)

        dest_row = ctk.CTkFrame(config_card, fg_color="transparent")
        dest_row.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        dest_row.columnconfigure(0, weight=1)

        self._dest_field = ReadOnlyField(dest_row, self._config, "batch_tab.destination_label")
        self._dest_field.grid(row=0, column=0, sticky="ew")

        self._dest_browse_button = ctk.CTkButton(
            dest_row, text=self._config.text("config.browse"), command=self._on_browse_destination_clicked, width=90
        )
        self._dest_browse_button.grid(row=0, column=1, sticky="ne", padx=(12, 0))

        csv_row = ctk.CTkFrame(config_card, fg_color="transparent")
        csv_row.grid(row=1, column=0, sticky="ew", padx=16, pady=(8, 16))
        csv_row.columnconfigure(0, weight=1)

        self._csv_field = ReadOnlyField(csv_row, self._config, "batch_tab.config_csv_label")
        self._csv_field.grid(row=0, column=0, sticky="ew")

        self._download_template_button = ctk.CTkButton(
            csv_row,
            text=self._config.text("batch_tab.download_template_button"),
            fg_color="transparent",
            border_width=1,
            border_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"),
            hover_color=self._colors.get("window_bg"),
            command=self._on_download_template_clicked,
        )
        self._download_template_button.grid(row=0, column=1, sticky="ne", padx=(12, 0))

        self._csv_load_button = ctk.CTkButton(
            csv_row, text=self._config.text("batch_tab.load_csv_button"), command=self._on_load_csv_clicked, width=90
        )
        self._csv_load_button.grid(row=0, column=2, sticky="ne", padx=(8, 0))

        separator_1 = ctk.CTkFrame(frame, height=1, fg_color=self._colors.get("border"))
        separator_1.grid(row=2, column=0, sticky="ew", pady=16)

        preview_title = ctk.CTkLabel(
            frame,
            text=self._config.text("batch_tab.preview_title"),
            text_color=self._colors.get("text_primary"),
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        )
        preview_title.grid(row=3, column=0, sticky="w")

        self._preview_label = ctk.CTkLabel(
            frame,
            text=self._config.text("batch_tab.preview_empty_hint"),
            text_color=self._colors.get("text_secondary"),
            anchor="w",
            justify="left",
            wraplength=880,
        )
        self._preview_label.grid(row=4, column=0, sticky="ew", pady=(4, 16))

        separator_2 = ctk.CTkFrame(frame, height=1, fg_color=self._colors.get("border"))
        separator_2.grid(row=5, column=0, sticky="ew", pady=(0, 16))

        controls = ctk.CTkFrame(frame, fg_color="transparent")
        controls.grid(row=6, column=0, sticky="ew")
        controls.columnconfigure(0, weight=1)

        self._status_label = ctk.CTkLabel(
            controls, text="", text_color=self._colors.get("text_secondary"), anchor="w", justify="left", wraplength=600
        )
        self._status_label.grid(row=0, column=0, sticky="w")

        self._open_folder_button = ctk.CTkButton(
            controls,
            text=self._config.text("summary.open_output_folder"),
            fg_color="transparent",
            border_width=1,
            border_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"),
            hover_color=self._colors.get("window_bg"),
            command=self._on_open_folder_clicked,
            state="disabled",
        )
        self._open_folder_button.grid(row=0, column=1, sticky="e", padx=(0, 8))

        self._run_button = ctk.CTkButton(
            controls, text=self._config.text("batch_tab.run_button"), command=self._on_run_clicked, state="disabled"
        )
        self._run_button.grid(row=0, column=2, sticky="e")

        log_label = ctk.CTkLabel(
            frame,
            text=self._config.text("batch_tab.log_label"),
            text_color=self._colors.get("text_secondary"),
            anchor="w",
        )
        log_label.grid(row=7, column=0, sticky="w", pady=(16, 4))

        log_frame = ctk.CTkFrame(frame, fg_color=self._colors.get("surface"))
        log_frame.grid(row=8, column=0, sticky="nsew")
        frame.rowconfigure(8, weight=1)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self._log_text = ctk.CTkTextbox(log_frame, wrap="word", state="disabled")
        self._log_text.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        return frame

    # -- estado del proyecto ---------------------------------------------

    def set_project(self, project_dir: Path) -> None:
        self._project_dir = project_dir
        self._destination_dir = None
        self._batch_config = None
        self._enabled_state.pack(fill="both", expand=True)
        self._disabled_state.pack_forget()

        self._dest_field.set_value(self._config.text("batch_tab.destination_not_set"))
        self._csv_field.set_value(self._config.text("batch_tab.config_csv_not_loaded"))
        self._preview_label.configure(text=self._config.text("batch_tab.preview_empty_hint"))
        self._status_label.configure(text="", text_color=self._colors.get("text_secondary"))
        self._open_folder_button.configure(state="disabled")
        self._set_log("")
        self._update_run_button_state()

    # -- destino -----------------------------------------------------------

    def _on_browse_destination_clicked(self) -> None:
        selected = filedialog.askdirectory()
        if not selected:
            return
        self._destination_dir = Path(selected)
        self._dest_field.set_value(str(self._destination_dir))
        self._open_folder_button.configure(state="normal")
        self._update_run_button_state()

    def _on_open_folder_clicked(self) -> None:
        if self._destination_dir is None:
            return
        os.startfile(self._destination_dir)  # solo Windows: target de distribución del proyecto

    # -- configuración CSV ---------------------------------------------------

    def _on_download_template_clicked(self) -> None:
        if self._project_dir is None:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="batch_config_template.csv",
        )
        if not path:
            return

        txtinout_dir = self._project_dir / "TxtInOut"
        destination = Path(path)

        self._set_controls_enabled(False)
        self._set_status(self._config.text("batch_tab.generating_template"))
        self._on_run_state_changed(True)

        def work(report_progress: Callable[[str], None]) -> Path:
            return write_land_cover_batch_template_csv(txtinout_dir, destination)

        run_in_background(
            self,
            work,
            on_progress=lambda message: None,
            on_done=self._on_template_done,
            on_error=self._on_template_error,
        )

    def _on_template_done(self, result_path: Path) -> None:
        self._set_status(self._config.text("batch_tab.template_success").format(path=str(result_path)))
        self._finish_template()

    def _on_template_error(self, error: Exception) -> None:
        self._set_status(self._config.text("batch_tab.template_error").format(error=str(error)), error=True)
        self._finish_template()

    def _finish_template(self) -> None:
        self._set_controls_enabled(True)
        self._on_run_state_changed(False)

    def _on_load_csv_clicked(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
        if not path:
            return

        try:
            config = parse_land_cover_batch_csv(Path(path))
        except ValueError as error:
            self._set_status(self._config.text("batch_tab.load_csv_error").format(error=str(error)), error=True)
            return

        self._batch_config = config
        self._csv_field.set_value(path)
        self._set_status(
            self._config.text("batch_tab.load_csv_success").format(
                target_lulc=config.target_lulc, count=len(config.target_pct_series)
            )
        )
        self._refresh_preview()
        self._update_run_button_state()

    def _refresh_preview(self) -> None:
        if self._batch_config is None:
            self._preview_label.configure(text=self._config.text("batch_tab.preview_empty_hint"))
            return

        lines = [
            self._config.text("batch_tab.preview_item").format(
                folder=scenario_folder_name(pct), target_lulc=self._batch_config.target_lulc, pct=pct
            )
            for pct in self._batch_config.target_pct_series
        ]
        self._preview_label.configure(text="\n".join(lines))

    # -- Run batch (hilo de fondo) -------------------------------------------

    def _update_run_button_state(self) -> None:
        exe = self._config.paths.swat_executable
        exe_ok = exe is not None and validate_swat_executable(exe) is None
        can_run = (
            self._project_dir is not None
            and self._destination_dir is not None
            and self._batch_config is not None
            and exe_ok
        )
        self._run_button.configure(state="normal" if can_run else "disabled")

    def _on_run_clicked(self) -> None:
        if self._batch_config is None:
            return
        exe = self._config.paths.swat_executable
        if exe is None or validate_swat_executable(exe) is not None:
            self._set_status(self._config.text("batch_tab.exe_missing_hint"), error=True)
            return

        message = self._config.text("batch_tab.confirm").format(count=len(self._batch_config.target_pct_series))
        ConfirmDialog(self, self._config, message=message, on_confirm=self._start_batch)

    def _start_batch(self) -> None:
        project_dir = self._project_dir
        destination_dir = self._destination_dir
        batch_config = self._batch_config
        exe = self._config.paths.swat_executable
        target_name = self._config.paths.target_executable_name

        self._set_controls_enabled(False)
        self._set_status(self._config.text("batch_tab.running"))
        self._set_log("")
        self._on_run_state_changed(True)

        def work(report_progress: Callable[[str], None]) -> list[ScenarioRunResult]:
            return run_land_cover_batch(
                project_dir, destination_dir, batch_config, exe, target_name, on_progress=report_progress
            )

        run_in_background(
            self,
            work,
            on_progress=self._set_log,
            on_done=self._on_batch_done,
            on_error=self._on_batch_error,
        )

    def _on_batch_done(self, results: list[ScenarioRunResult]) -> None:
        ok_count = sum(1 for r in results if r.status == "ok")
        self._set_status(self._config.text("batch_tab.summary").format(ok=ok_count, total=len(results)))

        lines = []
        for result in results:
            if result.status == "ok":
                lines.append(self._config.text("batch_tab.log_line_ok").format(folder=result.scenario_dir.name))
            else:
                lines.append(
                    self._config.text("batch_tab.log_line_error").format(
                        folder=result.scenario_dir.name, error=result.error
                    )
                )
        self._set_log("\n".join(lines))
        self._finish_batch()

    def _on_batch_error(self, error: Exception) -> None:
        self._set_status(self._config.text("batch_tab.error").format(error=str(error)), error=True)
        self._finish_batch()

    def _finish_batch(self) -> None:
        self._set_controls_enabled(True)
        self._on_run_state_changed(False)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._dest_browse_button.configure(state="normal" if enabled else "disabled")
        self._download_template_button.configure(state="normal" if enabled else "disabled")
        self._csv_load_button.configure(state="normal" if enabled else "disabled")
        self._open_folder_button.configure(
            state="normal" if enabled and self._destination_dir is not None else "disabled"
        )
        if enabled:
            self._update_run_button_state()
        else:
            self._run_button.configure(state="disabled")

    # -- status/log ---------------------------------------------------------

    def _set_status(self, text: str, *, error: bool = False) -> None:
        color_key = "error" if error else "text_secondary"
        self._status_label.configure(text=text, text_color=self._colors.get(color_key))

    def _set_log(self, text: str) -> None:
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.insert("1.0", text)
        self._log_text.configure(state="disabled")
