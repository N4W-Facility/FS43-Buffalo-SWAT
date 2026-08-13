"""Ventana de edición de parámetros de HRU (.hru), una HRU a la vez.

A diferencia de WetlandEditorWindow (una subcuenca = un .pnd, campos fijos
declarados en wetland_params.yaml), aquí una subcuenca tiene N archivos
.hru y el set de parámetros de cada uno se lee directo del archivo (no hay
lista curada ni rangos: se expone todo lo que swat_io.hru.parser
reconoció). Por eso hay dos selectores encadenados (subcuenca -> HRU) y la
lista de campos se reconstruye cada vez que cambia la HRU seleccionada.

Escribe directo sobre el .hru real de la carpeta TxtInOut abierta (mismo
aviso de aislamiento que WetlandEditorWindow: ver CLAUDE.md). Sin rango
declarado por campo, la validación antes de guardar corre
HRUFile.validate() sobre una copia con los cambios ya aplicados y bloquea
si hay algún issue de severidad ERROR (p. ej. HRU_FR fuera de [0, 1]).
"""
from __future__ import annotations

from pathlib import Path
from tkinter import ttk

import customtkinter as ctk

from config.settings import ConfigManager
from scenarios.activity_log import log_action
from scenarios.hru_draft import load_subbasin_hru_files, write_hru_values
from swat_io.discovery import discover_subbasins
from swat_io.hru.models import HRUParameterLine, ParamValue
from swat_io.hru.parser import _coerce_value
from swat_io.hru.validation import SEVERITY_ERROR

from .dialog_confirm import ConfirmDialog
from .widgets import palette, style_combobox

_WINDOW_SIZE = "560x680"


class HRUEditorWindow(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        config: ConfigManager,
        project_dir: Path,
        *,
        initial_subbasin: int | None = None,
        initial_hru: int | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self._config = config
        self._colors = palette(config)
        self._project_dir = project_dir
        self._txtinout_dir = project_dir / "TxtInOut"

        self.title(config.text("hru_editor.title"))
        self.configure(fg_color=self._colors.get("window_bg"))
        self.geometry(_WINDOW_SIZE)
        self.transient(master)

        self._subbasins = discover_subbasins(self._txtinout_dir)
        if not self._subbasins:
            self._build_empty_state(config.text("hru_editor.no_subbasins"))
            self.grab_set()
            return

        self._current_subbasin = (
            initial_subbasin if initial_subbasin is not None else self._subbasins[0].subbasin_id
        )
        self._hru_files: dict[int, object] = {}
        self._current_hru: int | None = None
        self._value_widgets: dict[str, ctk.CTkBaseClass] = {}

        self._build_selectors()
        self._build_form()
        self._build_actions()
        self._select_subbasin(self._current_subbasin, preferred_hru=initial_hru)

        self.grab_set()

    # -- construcción -----------------------------------------------------

    def _build_empty_state(self, text: str) -> None:
        label = ctk.CTkLabel(self, text=text, text_color=self._colors.get("text_secondary"))
        label.pack(fill="both", expand=True, padx=20, pady=20)

    def _build_selectors(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(20, 0))

        subbasin_label = ctk.CTkLabel(
            header, text=self._config.text("scenario.subbasin"), text_color=self._colors.get("text_secondary")
        )
        subbasin_label.pack(side="left")

        subbasin_values = [str(s.subbasin_id) for s in self._subbasins]
        combobox_style = style_combobox(self._config)
        self._subbasin_selector = ttk.Combobox(
            header, style=combobox_style, state="readonly", values=subbasin_values, width=8
        )
        self._subbasin_selector.pack(side="left", padx=(8, 16))
        self._subbasin_selector.bind("<<ComboboxSelected>>", self._on_subbasin_selected)

        hru_label = ctk.CTkLabel(
            header, text=self._config.text("hru_editor.hru"), text_color=self._colors.get("text_secondary")
        )
        hru_label.pack(side="left")

        self._hru_selector = ttk.Combobox(header, style=combobox_style, state="readonly", values=[], width=8)
        self._hru_selector.pack(side="left", padx=(8, 0))
        self._hru_selector.bind("<<ComboboxSelected>>", self._on_hru_selected)

    def _build_form(self) -> None:
        self._form_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._form_frame.pack(fill="both", expand=True, padx=20, pady=12)
        self._form_frame.columnconfigure(0, weight=1)

    def _build_actions(self) -> None:
        self._actions = ctk.CTkFrame(self, fg_color="transparent")
        self._actions.pack(fill="x", padx=20, pady=(0, 20))

        self._status_label = ctk.CTkLabel(self._actions, text="", anchor="w")
        self._status_label.pack(side="left", fill="x", expand=True)

        self._edit_button = ctk.CTkButton(
            self._actions, text=self._config.text("action.edit"), command=self._on_edit_clicked
        )

        self._cancel_button = ctk.CTkButton(
            self._actions,
            text=self._config.text("action.cancel"),
            fg_color="transparent",
            border_width=1,
            border_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"),
            hover_color=self._colors.get("window_bg"),
            command=self._on_cancel_clicked,
        )
        self._save_button = ctk.CTkButton(
            self._actions, text=self._config.text("action.save"), command=self._on_save_clicked
        )

        self._edit_button.pack(side="right")

    # -- render de campos --------------------------------------------------

    def _parameter_lines(self) -> list[HRUParameterLine]:
        hru_file = self._hru_files[self._current_hru]
        seen: set[str] = set()
        lines: list[HRUParameterLine] = []
        for line in hru_file.lines:
            if isinstance(line, HRUParameterLine) and line.parameter_name.upper() not in seen:
                seen.add(line.parameter_name.upper())
                lines.append(line)
        return lines

    def _render_fields(self, *, editable: bool) -> None:
        for child in self._form_frame.winfo_children():
            child.destroy()
        self._value_widgets = {}

        for row, line in enumerate(self._parameter_lines()):
            label_text = line.parameter_name
            if line.description:
                label_text = f"{line.parameter_name} — {line.description}"

            label = ctk.CTkLabel(
                self._form_frame,
                text=label_text,
                text_color=self._colors.get("text_secondary"),
                anchor="w",
                wraplength=480,
                justify="left",
            )
            label.grid(row=row * 2, column=0, sticky="w", pady=(10 if row else 0, 2))

            current_text = str(line.parsed_value)
            widget: ctk.CTkBaseClass
            if editable:
                widget = ctk.CTkEntry(self._form_frame)
                widget.insert(0, current_text)
            else:
                widget = ctk.CTkLabel(
                    self._form_frame, text=current_text, text_color=self._colors.get("text_primary"), anchor="w"
                )
            widget.grid(row=row * 2 + 1, column=0, sticky="ew")
            self._value_widgets[line.parameter_name] = widget

    # -- estado -------------------------------------------------------------

    def _on_subbasin_selected(self, _event=None) -> None:
        self._select_subbasin(int(self._subbasin_selector.get()))

    def _select_subbasin(self, subbasin_id: int, *, preferred_hru: int | None = None) -> None:
        self._current_subbasin = subbasin_id
        self._subbasin_selector.set(str(subbasin_id))
        self._hru_files = load_subbasin_hru_files(self._txtinout_dir, subbasin_id)

        if not self._hru_files:
            self._hru_selector.configure(values=[])
            self._hru_selector.set("")
            for child in self._form_frame.winfo_children():
                child.destroy()
            self._set_status(self._config.text("hru_editor.no_hrus"), error=True)
            self._edit_button.configure(state="disabled")
            return

        self._edit_button.configure(state="normal")
        hru_ids = sorted(self._hru_files)
        self._hru_selector.configure(values=[str(h) for h in hru_ids])
        target_hru = preferred_hru if preferred_hru in self._hru_files else hru_ids[0]
        self._load_hru(target_hru)

    def _on_hru_selected(self, _event=None) -> None:
        self._load_hru(int(self._hru_selector.get()))

    def _load_hru(self, hru_id: int) -> None:
        self._current_hru = hru_id
        self._hru_selector.set(str(hru_id))
        self._render_fields(editable=False)
        self._set_status("")

    def _on_edit_clicked(self) -> None:
        self._subbasin_selector.configure(state="disabled")
        self._hru_selector.configure(state="disabled")
        self._render_fields(editable=True)
        self._edit_button.pack_forget()
        self._save_button.pack(side="right")
        self._cancel_button.pack(side="right", padx=(0, 8))
        self._set_status("")

    def _on_cancel_clicked(self) -> None:
        self._exit_edit_mode()
        self._render_fields(editable=False)
        self._set_status("")

    def _on_save_clicked(self) -> None:
        try:
            values = self._collect_and_validate()
        except ValueError as error:
            self._set_status(str(error), error=True)
            return

        ConfirmDialog(
            self,
            self._config,
            message=self._config.text("hru_editor.confirm_save_message").format(
                subbasin=self._current_subbasin, hru=self._current_hru
            ),
            on_confirm=lambda: self._apply_save(values),
        )

    def _collect_and_validate(self) -> dict[str, ParamValue]:
        values: dict[str, ParamValue] = {}
        for name, widget in self._value_widgets.items():
            raw = widget.get().strip()
            if not raw:
                raise ValueError(self._config.text("hru_editor.empty_value").format(field=name))
            values[name] = _coerce_value(raw)

        hru_file = self._hru_files[self._current_hru]
        working_copy = hru_file.copy()
        for name, value in values.items():
            working_copy.set_value(name, value)

        errors = [issue.message for issue in working_copy.validate() if issue.severity == SEVERITY_ERROR]
        if errors:
            raise ValueError(self._config.text("hru_editor.validation_error").format(error="; ".join(errors)))

        return values

    def _apply_save(self, values: dict[str, ParamValue]) -> None:
        hru_file = self._hru_files[self._current_hru]
        try:
            write_hru_values(hru_file, values)
        except OSError as error:
            self._set_status(self._config.text("hru_editor.error").format(error=str(error)), error=True)
            return

        changed = ", ".join(f"{name}={value}" for name, value in values.items())
        log_action(
            self._project_dir, "HRU", f"Saved subbasin {self._current_subbasin} HRU {self._current_hru}: {changed}"
        )

        self._exit_edit_mode()
        self._render_fields(editable=False)
        self._set_status(self._config.text("hru_editor.saved"))

    def _exit_edit_mode(self) -> None:
        self._subbasin_selector.configure(state="readonly")
        self._hru_selector.configure(state="readonly")
        self._save_button.pack_forget()
        self._cancel_button.pack_forget()
        self._edit_button.pack(side="right")

    def _set_status(self, text: str, *, error: bool = False) -> None:
        color_key = "error" if error else "success"
        self._status_label.configure(text=text, text_color=self._colors.get(color_key))
