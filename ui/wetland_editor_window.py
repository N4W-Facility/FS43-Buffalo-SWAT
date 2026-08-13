"""Ventana de edición de parámetros de humedal (.pnd), una subcuenca a la vez.

Escribe directo sobre el .pnd real de la carpeta TxtInOut abierta (la app
no distingue hoy entre modelo de referencia y copia de escenario — es
responsabilidad del usuario abrir una copia, no la carpeta calibrada; ver
CLAUDE.md). Cada Guardar también reescribe
tool_outputs/wetland_params_draft.csv como respaldo, reconstruido desde
los .pnd reales al abrir la ventana (nunca es una segunda fuente de
verdad que pueda desincronizarse).

Los campos arrancan de solo lectura. "Edit" los vuelve editables;
"Cancel" descarta cualquier cambio sin guardar; "Save" pide confirmación
antes de escribir.
"""
from __future__ import annotations

from pathlib import Path
from tkinter import ttk

import customtkinter as ctk

from config.settings import ConfigManager
from scenarios.activity_log import log_action
from scenarios.validation import validate_field_value
from scenarios.wetland_draft import build_wetland_draft, save_wetland_draft
from swat_io.discovery import discover_subbasins
from swat_io.pnd_parser import write_wetland_params

from .dialog_confirm import ConfirmDialog
from .widgets import palette, style_combobox

_WINDOW_SIZE = "520x680"


class WetlandEditorWindow(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        config: ConfigManager,
        project_dir: Path,
        *,
        initial_subbasin: int | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self._config = config
        self._colors = palette(config)
        self._project_dir = project_dir
        self._txtinout_dir = project_dir / "TxtInOut"
        self._layout = config.load_layout("wetland_params")
        self._fields = self._layout["fields"]

        self.title(config.text("wetland_editor.title"))
        self.configure(fg_color=self._colors.get("window_bg"))
        self.geometry(_WINDOW_SIZE)
        self.transient(master)

        self._subbasins = discover_subbasins(self._txtinout_dir)
        if not self._subbasins:
            self._build_empty_state()
            self.grab_set()
            return

        self._draft = build_wetland_draft(self._txtinout_dir)
        self._current_subbasin = (
            initial_subbasin if initial_subbasin is not None else self._subbasins[0].subbasin_id
        )
        self._value_widgets: dict[str, ctk.CTkBaseClass] = {}

        self._build_selector()
        self._build_form()
        self._build_actions()
        self._load_subbasin(self._current_subbasin)

        self.grab_set()

    # -- construcción -----------------------------------------------------

    def _build_empty_state(self) -> None:
        label = ctk.CTkLabel(
            self,
            text=self._config.text("wetland_editor.no_subbasins"),
            text_color=self._colors.get("text_secondary"),
        )
        label.pack(fill="both", expand=True, padx=20, pady=20)

    def _build_selector(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(20, 0))

        label = ctk.CTkLabel(
            header, text=self._config.text("scenario.subbasin"), text_color=self._colors.get("text_secondary")
        )
        label.pack(side="left")

        values = [str(s.subbasin_id) for s in self._subbasins]
        self._selector = ttk.Combobox(
            header, style=style_combobox(self._config), state="readonly", values=values, width=8
        )
        self._selector.pack(side="left", padx=(8, 0))
        self._selector.set(str(self._current_subbasin))
        self._selector.bind("<<ComboboxSelected>>", self._on_subbasin_selected)

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

    def _render_fields(self, *, editable: bool) -> None:
        for child in self._form_frame.winfo_children():
            child.destroy()
        self._value_widgets = {}

        row_values = self._draft.loc[self._current_subbasin]
        for row, field in enumerate(self._fields):
            field_id = field["id"]

            label = ctk.CTkLabel(
                self._form_frame,
                text=self._config.text(field["label_key"]),
                text_color=self._colors.get("text_secondary"),
                anchor="w",
                wraplength=440,
                justify="left",
            )
            label.grid(row=row * 2, column=0, sticky="w", pady=(10 if row else 0, 2))

            current_text = f"{row_values[field_id]:.3f}"
            widget: ctk.CTkBaseClass
            if editable:
                widget = ctk.CTkEntry(self._form_frame)
                widget.insert(0, current_text)
            else:
                widget = ctk.CTkLabel(
                    self._form_frame, text=current_text, text_color=self._colors.get("text_primary"), anchor="w"
                )
            widget.grid(row=row * 2 + 1, column=0, sticky="ew")
            self._value_widgets[field_id] = widget

    # -- estado -------------------------------------------------------------

    def _on_subbasin_selected(self, _event=None) -> None:
        self._load_subbasin(int(self._selector.get()))

    def _load_subbasin(self, subbasin_id: int) -> None:
        self._current_subbasin = subbasin_id
        self._render_fields(editable=False)
        self._set_status("")

    def _on_edit_clicked(self) -> None:
        self._selector.configure(state="disabled")
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
            message=self._config.text("wetland_editor.confirm_save_message").format(id=self._current_subbasin),
            on_confirm=lambda: self._apply_save(values),
        )

    def _collect_and_validate(self) -> dict[str, float]:
        values: dict[str, float] = {}
        for field in self._fields:
            field_id = field["id"]
            raw = self._value_widgets[field_id].get()
            try:
                value = float(raw)
            except ValueError:
                label = self._config.text(field["label_key"])
                raise ValueError(self._config.text("wetland_editor.invalid_number").format(label=label)) from None
            validate_field_value(field_id, value, self._layout)
            values[field_id] = value
        return values

    def _apply_save(self, values: dict[str, float]) -> None:
        subbasin = next(s for s in self._subbasins if s.subbasin_id == self._current_subbasin)
        try:
            write_wetland_params(subbasin.pnd_file, values)
            for field_id, value in values.items():
                self._draft.loc[self._current_subbasin, field_id] = value
            save_wetland_draft(self._project_dir, self._draft)
        except OSError as error:
            self._set_status(self._config.text("wetland_editor.error").format(error=str(error)), error=True)
            return

        changed = ", ".join(f"{field_id}={value}" for field_id, value in values.items())
        log_action(self._project_dir, "WETLANDS", f"Saved subbasin {self._current_subbasin}: {changed}")

        self._exit_edit_mode()
        self._render_fields(editable=False)
        self._set_status(self._config.text("wetland_editor.saved"))

    def _exit_edit_mode(self) -> None:
        self._selector.configure(state="readonly")
        self._save_button.pack_forget()
        self._cancel_button.pack_forget()
        self._edit_button.pack(side="right")

    def _set_status(self, text: str, *, error: bool = False) -> None:
        color_key = "error" if error else "success"
        self._status_label.configure(text=text, text_color=self._colors.get(color_key))
