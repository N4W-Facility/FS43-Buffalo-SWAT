"""Diálogo modal "Edit Project": name/description de project.json.

Construido desde resources/layout/project_metadata.yaml (form builder
declarativo) en vez de campos escritos a mano — agregar un campo nuevo al
diálogo es una entrada de YAML, no un cambio de este archivo.
"""
from __future__ import annotations

import copy
from pathlib import Path

import customtkinter as ctk

from config.settings import ConfigManager
from scenarios.project import ProjectMetadata, save_project

from .widgets import palette


class ProjectEditDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        config: ConfigManager,
        metadata: ProjectMetadata,
        project_dir: Path,
    ) -> None:
        super().__init__(master)
        self._config = config
        self._colors = palette(config)
        self._metadata = metadata
        self._project_dir = project_dir
        self.saved_metadata: ProjectMetadata | None = None

        self.title(config.text("project.edit_title"))
        self.configure(fg_color=self._colors.get("window_bg"))
        self.transient(master)

        self._inputs: dict[str, ctk.CTkBaseClass] = {}
        layout = config.load_layout("project_metadata")
        self._build_fields(layout)
        self._build_actions()

        self.grab_set()

    def _build_fields(self, layout: dict) -> None:
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=20, pady=20)

        for field in layout["fields"]:
            label = ctk.CTkLabel(
                container,
                text=self._config.text(field["label_key"]),
                text_color=self._colors.get("text_secondary"),
                anchor="w",
            )
            label.pack(fill="x", pady=(8, 2))

            current_value = getattr(self._metadata, field["id"], "") or ""
            widget: ctk.CTkBaseClass
            if field.get("multiline"):
                widget = ctk.CTkTextbox(container, height=110)
                widget.insert("1.0", current_value)
            else:
                widget = ctk.CTkEntry(container)
                widget.insert(0, current_value)
            widget.pack(fill="x")
            self._inputs[field["id"]] = widget

    def _build_actions(self) -> None:
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=20, pady=(0, 20))

        cancel_button = ctk.CTkButton(
            actions,
            text=self._config.text("action.cancel"),
            fg_color="transparent",
            border_width=1,
            border_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"),
            hover_color=self._colors.get("window_bg"),
            command=self.destroy,
        )
        cancel_button.pack(side="right")

        save_button = ctk.CTkButton(
            actions,
            text=self._config.text("action.save"),
            command=self._on_save,
        )
        save_button.pack(side="right", padx=(0, 8))

    def _on_save(self) -> None:
        updated = copy.copy(self._metadata)
        for field_id, widget in self._inputs.items():
            if isinstance(widget, ctk.CTkTextbox):
                value = widget.get("1.0", "end-1c")
            else:
                value = widget.get()
            setattr(updated, field_id, value)

        save_project(self._project_dir, updated)
        self.saved_metadata = updated
        self.destroy()
