"""Pestaña Run: ejecuta swat2012.exe como subproceso local sobre la copia de
trabajo del proyecto abierto (TxtInOut/), en hilo de fondo (ver
ui.tasks.run_in_background) -- CLAUDE.md exige esto para cualquier
operación que pueda tardar sobre un modelo real; una corrida de SWAT puede
tomar del orden de minutos.

También aloja la única configuración de ruta que la app necesita hoy: el
ejecutable SWAT (config.settings.AppPaths.swat_executable). Todavía no hay
una pestaña Settings separada, así que "Browse..." vive acá mismo, junto al
botón Run que la consume -- si en el futuro se agregan más rutas
configurables, ahí sí valdría la pena separarlo.

Y el período de la corrida (NBYR/IYR/NYSKIP/IPRINT de file.cio): años de
inicio/fin, años de warm-up excluidos del output, y frecuencia de
impresión. Decisión explícita del usuario (2026-07-31): CLAUDE.md ya
permitía tocar file.cio ante "cambio explícito de periodo simulado pedido
por el usuario"; NYSKIP e IPRINT se suman a esa misma excepción porque son
configuración de la corrida, no física del modelo (a diferencia de .bsn,
que sigue completamente fuera de alcance, sin excepción). Mismo patrón
Edit/Cancel/Save con confirmación que WetlandEditorWindow/HRUEditorWindow,
pero inline en la pestaña en vez de una ventana aparte -- son solo 4
campos.

Determinación de éxito/error de la corrida: solo el exit code del proceso
(0 = éxito, != 0 = error). CLAUDE.md pide distinguir "SWAT terminó con
error" de "no se pudo parsear la salida"; esta pestaña resuelve
únicamente lo primero -- parsear output.* para comparación línea
base/escenario es una pieza de viz/ que todavía no existe.

Deshabilitada (vía TabBar.set_enabled) hasta que haya un proyecto abierto.
"""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, ttk
from typing import Callable

import customtkinter as ctk

from config.settings import AppPaths, ConfigManager, validate_swat_executable
from engine.run import RunResult, run_scenario
from swat_io.cio_parser import (
    PRINT_FREQUENCY_DAILY,
    PRINT_FREQUENCY_MONTHLY,
    PRINT_FREQUENCY_YEARLY,
    CioParseError,
    RunSettings,
    parse_run_settings,
    write_run_settings,
)

from .dialog_confirm import ConfirmDialog
from .tasks import run_in_background
from .widgets import ReadOnlyField, palette, style_combobox

_PRINT_FREQUENCY_LABEL_KEYS = {
    PRINT_FREQUENCY_DAILY: "run_tab.print_frequency.daily",
    PRINT_FREQUENCY_MONTHLY: "run_tab.print_frequency.monthly",
    PRINT_FREQUENCY_YEARLY: "run_tab.print_frequency.yearly",
}


class RunTab(ctk.CTkFrame):
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
        self._run_settings: RunSettings | None = None
        self._period_value_widgets: dict[str, ctk.CTkBaseClass] = {}
        self._print_frequency_label_to_code = {
            self._config.text(key): code for code, key in _PRINT_FREQUENCY_LABEL_KEYS.items()
        }

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

        title = ctk.CTkLabel(
            frame,
            text=self._config.text("run_tab.title"),
            text_color=self._colors.get("accent"),
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        )
        title.grid(row=0, column=0, sticky="w", pady=(0, 12))

        exe_card = ctk.CTkFrame(frame)
        exe_card.grid(row=1, column=0, sticky="ew")
        exe_card.columnconfigure(0, weight=1)

        exe_row = ctk.CTkFrame(exe_card, fg_color="transparent")
        exe_row.grid(row=0, column=0, sticky="ew", padx=16, pady=16)
        exe_row.columnconfigure(0, weight=1)

        self._exe_field = ReadOnlyField(exe_row, self._config, "config.executable_path")
        self._exe_field.grid(row=0, column=0, sticky="ew")

        self._browse_button = ctk.CTkButton(
            exe_row, text=self._config.text("config.browse"), command=self._on_browse_clicked, width=90
        )
        self._browse_button.grid(row=0, column=1, sticky="ne", padx=(12, 0))

        self._exe_error_label = ctk.CTkLabel(
            exe_card, text="", text_color=self._colors.get("error"), anchor="w"
        )
        self._exe_error_label.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))

        separator_1 = ctk.CTkFrame(frame, height=1, fg_color=self._colors.get("border"))
        separator_1.grid(row=2, column=0, sticky="ew", pady=16)

        self._build_period_card(frame).grid(row=3, column=0, sticky="ew")

        separator_2 = ctk.CTkFrame(frame, height=1, fg_color=self._colors.get("border"))
        separator_2.grid(row=4, column=0, sticky="ew", pady=16)

        controls = ctk.CTkFrame(frame, fg_color="transparent")
        controls.grid(row=5, column=0, sticky="ew")
        controls.columnconfigure(0, weight=1)

        self._status_label = ctk.CTkLabel(
            controls, text="", text_color=self._colors.get("text_secondary"), anchor="w"
        )
        self._status_label.grid(row=0, column=0, sticky="w")

        self._run_button = ctk.CTkButton(
            controls, text=self._config.text("scenario.run"), command=self._on_run_clicked, state="disabled"
        )
        self._run_button.grid(row=0, column=1, sticky="e")

        log_label = ctk.CTkLabel(
            frame,
            text=self._config.text("run_tab.log_label"),
            text_color=self._colors.get("text_secondary"),
            anchor="w",
        )
        log_label.grid(row=6, column=0, sticky="w", pady=(16, 4))

        log_frame = ctk.CTkFrame(frame, fg_color=self._colors.get("surface"))
        log_frame.grid(row=7, column=0, sticky="nsew")
        frame.rowconfigure(7, weight=1)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self._log_text = ctk.CTkTextbox(log_frame, wrap="word", state="disabled")
        self._log_text.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        return frame

    def _build_period_card(self, master: ctk.CTkBaseClass) -> ctk.CTkFrame:
        card = ctk.CTkFrame(master)
        for col in range(4):
            card.columnconfigure(col, weight=1)

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=4, sticky="ew", padx=16, pady=(16, 8))
        header.columnconfigure(0, weight=1)

        header_title = ctk.CTkLabel(
            header,
            text=self._config.text("run_tab.period_title"),
            text_color=self._colors.get("text_primary"),
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        )
        header_title.grid(row=0, column=0, sticky="w")

        self._period_edit_button = ctk.CTkButton(
            header, text=self._config.text("action.edit"), command=self._on_period_edit_clicked, width=70
        )
        self._period_cancel_button = ctk.CTkButton(
            header,
            text=self._config.text("action.cancel"),
            fg_color="transparent",
            border_width=1,
            border_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"),
            hover_color=self._colors.get("window_bg"),
            command=self._on_period_cancel_clicked,
            width=70,
        )
        self._period_save_button = ctk.CTkButton(
            header, text=self._config.text("action.save"), command=self._on_period_save_clicked, width=70
        )
        self._period_edit_button.grid(row=0, column=1, sticky="e")

        self._period_fields_frame = ctk.CTkFrame(card, fg_color="transparent")
        self._period_fields_frame.grid(row=1, column=0, columnspan=4, sticky="ew", padx=16)
        for col in range(4):
            self._period_fields_frame.columnconfigure(col, weight=1)

        self._period_status_label = ctk.CTkLabel(card, text="", anchor="w", wraplength=880)
        self._period_status_label.grid(row=2, column=0, columnspan=4, sticky="ew", padx=16, pady=(8, 16))

        return card

    # -- estado del proyecto -------------------------------------------------

    def set_project(self, project_dir: Path) -> None:
        self._project_dir = project_dir
        self._enabled_state.pack(fill="both", expand=True)
        self._disabled_state.pack_forget()
        self._exe_error_label.configure(text="")
        self._status_label.configure(text="")
        self._set_log("")
        self._refresh_exe_field()
        self._load_run_settings()

    # -- configuración del ejecutable ----------------------------------------

    def _refresh_exe_field(self) -> None:
        exe = self._config.paths.swat_executable
        self._exe_field.set_value(str(exe) if exe else self._config.text("run_tab.exe_not_configured"))
        self._update_run_button_state()

    def _on_browse_clicked(self) -> None:
        selected = filedialog.askopenfilename(filetypes=[("Executable", "*.exe")])
        if not selected:
            return
        exe_path = Path(selected)

        error_key = validate_swat_executable(exe_path)
        if error_key is not None:
            self._exe_error_label.configure(text=self._config.text(error_key))
            return
        self._exe_error_label.configure(text="")

        current = self._config.paths
        updated = AppPaths(
            swat_executable=exe_path,
            base_models_root=current.base_models_root,
            workspace_root=current.workspace_root,
            target_executable_name=current.target_executable_name,
        )
        self._config.save_paths(updated)
        self._refresh_exe_field()

    def _update_run_button_state(self) -> None:
        exe = self._config.paths.swat_executable
        can_run = self._project_dir is not None and exe is not None and validate_swat_executable(exe) is None
        self._run_button.configure(state="normal" if can_run else "disabled")

    # -- periodo de la corrida (file.cio) ------------------------------------

    def _cio_path(self) -> Path:
        return self._project_dir / "TxtInOut" / "file.cio"

    def _load_run_settings(self) -> None:
        self._period_status_label.configure(text="")
        try:
            self._run_settings = parse_run_settings(self._cio_path())
        except (CioParseError, OSError) as error:
            self._run_settings = None
            self._period_status_label.configure(
                text=self._config.text("run_tab.period_load_error").format(error=str(error)),
                text_color=self._colors.get("error"),
            )
        self._period_edit_button.configure(state="normal" if self._run_settings is not None else "disabled")
        self._render_period_fields(editable=False)

    def _render_period_fields(self, *, editable: bool) -> None:
        for child in self._period_fields_frame.winfo_children():
            child.destroy()
        self._period_value_widgets = {}

        settings = self._run_settings
        specs = [
            ("start_year", "run_tab.start_year", "" if settings is None else str(settings.start_year)),
            ("end_year", "run_tab.end_year", "" if settings is None else str(settings.end_year)),
            ("years_to_skip", "run_tab.skip_years", "" if settings is None else str(settings.years_to_skip)),
            (
                "print_frequency",
                "run_tab.print_frequency",
                "" if settings is None else self._config.text(_PRINT_FREQUENCY_LABEL_KEYS[settings.print_frequency]),
            ),
        ]

        for col, (field_id, label_key, current_text) in enumerate(specs):
            label = ctk.CTkLabel(
                self._period_fields_frame,
                text=self._config.text(label_key).upper(),
                text_color=self._colors.get("text_secondary"),
                font=ctk.CTkFont(size=11, weight="bold"),
                anchor="w",
            )
            label.grid(row=0, column=col, sticky="w", padx=(0 if col == 0 else 12, 0))

            widget: ctk.CTkBaseClass
            if not editable or settings is None:
                widget = ctk.CTkLabel(
                    self._period_fields_frame, text=current_text, text_color=self._colors.get("text_primary"), anchor="w"
                )
            elif field_id == "print_frequency":
                widget = ttk.Combobox(
                    self._period_fields_frame,
                    style=style_combobox(self._config),
                    state="readonly",
                    values=list(self._print_frequency_label_to_code.keys()),
                )
                widget.set(current_text)
            else:
                widget = ctk.CTkEntry(self._period_fields_frame)
                widget.insert(0, current_text)
            widget.grid(row=1, column=col, sticky="ew", padx=(0 if col == 0 else 12, 0), pady=(2, 12))
            self._period_value_widgets[field_id] = widget

    def _on_period_edit_clicked(self) -> None:
        self._render_period_fields(editable=True)
        self._period_edit_button.grid_forget()
        self._period_save_button.grid(row=0, column=1, sticky="e", padx=(0, 8))
        self._period_cancel_button.grid(row=0, column=2, sticky="e")
        self._period_status_label.configure(text="")

    def _on_period_cancel_clicked(self) -> None:
        self._exit_period_edit_mode()
        self._render_period_fields(editable=False)
        self._period_status_label.configure(text="")

    def _on_period_save_clicked(self) -> None:
        try:
            values = self._collect_and_validate_period()
        except ValueError as error:
            self._period_status_label.configure(text=str(error), text_color=self._colors.get("error"))
            return

        ConfirmDialog(
            self, self._config, message=self._config.text("run_tab.period_confirm"),
            on_confirm=lambda: self._apply_period_save(values),
        )

    def _collect_and_validate_period(self) -> dict:
        try:
            start_year = int(self._period_value_widgets["start_year"].get())
            end_year = int(self._period_value_widgets["end_year"].get())
            years_to_skip = int(self._period_value_widgets["years_to_skip"].get())
        except ValueError:
            raise ValueError(self._config.text("run_tab.period_invalid_year")) from None

        if end_year < start_year:
            raise ValueError(self._config.text("run_tab.period_invalid_year"))
        if not 0 <= years_to_skip < (end_year - start_year + 1):
            raise ValueError(self._config.text("run_tab.period_invalid_skip_years"))

        print_frequency_label = self._period_value_widgets["print_frequency"].get()
        print_frequency = self._print_frequency_label_to_code[print_frequency_label]

        return {
            "start_year": start_year,
            "end_year": end_year,
            "years_to_skip": years_to_skip,
            "print_frequency": print_frequency,
        }

    def _apply_period_save(self, values: dict) -> None:
        try:
            write_run_settings(self._cio_path(), **values)
        except (ValueError, OSError) as error:
            self._period_status_label.configure(
                text=self._config.text("run_tab.period_save_error").format(error=str(error)),
                text_color=self._colors.get("error"),
            )
            return

        self._load_run_settings()
        self._exit_period_edit_mode()
        self._render_period_fields(editable=False)
        self._period_status_label.configure(
            text=self._config.text("run_tab.period_saved"), text_color=self._colors.get("success")
        )

    def _exit_period_edit_mode(self) -> None:
        self._period_save_button.grid_forget()
        self._period_cancel_button.grid_forget()
        self._period_edit_button.grid(row=0, column=1, sticky="e")

    # -- Run ------------------------------------------------------------------

    def _on_run_clicked(self) -> None:
        if self._project_dir is None or self._config.paths.swat_executable is None:
            return
        ConfirmDialog(
            self, self._config, message=self._config.text("run_tab.confirm"), on_confirm=self._start_run
        )

    def _start_run(self) -> None:
        txtinout_dir = self._project_dir / "TxtInOut"
        swat_executable = self._config.paths.swat_executable
        target_name = self._config.paths.target_executable_name

        self._set_controls_enabled(False)
        self._status_label.configure(text=self._config.text("scenario.running"))
        self._set_log("")
        self._on_run_state_changed(True)

        def work(report_progress: Callable[[str], None]) -> RunResult:
            return run_scenario(txtinout_dir, swat_executable, target_name, on_progress=report_progress)

        run_in_background(
            self,
            work,
            on_progress=lambda message: self._status_label.configure(text=message),
            on_done=self._on_run_done,
            on_error=self._on_run_error,
        )

    def _on_run_done(self, result: RunResult) -> None:
        self._set_log(result.stdout + (("\n" + result.stderr) if result.stderr else ""))
        if result.success:
            self._status_label.configure(
                text=self._config.text("run_tab.success").format(seconds=result.elapsed_seconds)
            )
        else:
            self._status_label.configure(
                text=self._config.text("scenario.error.swat_failed").format(exit_code=result.exit_code)
            )
        self._finish_run()

    def _on_run_error(self, error: Exception) -> None:
        self._status_label.configure(text=str(error))
        self._finish_run()

    def _finish_run(self) -> None:
        self._set_controls_enabled(True)
        self._on_run_state_changed(False)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._browse_button.configure(state="normal" if enabled else "disabled")
        self._period_edit_button.configure(
            state="normal" if enabled and self._run_settings is not None else "disabled"
        )
        if enabled:
            self._update_run_button_state()
        else:
            self._run_button.configure(state="disabled")

    def _set_log(self, text: str) -> None:
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.insert("1.0", text)
        self._log_text.configure(state="disabled")
