from __future__ import annotations

from pathlib import Path
from tkinter import filedialog
from typing import Callable

import customtkinter as ctk

from config.settings import ConfigManager
from scenarios.models import Project
from scenarios.project import open_or_create_project
from swat_io.discovery import discover_base_models
from ui.dialogs import ask_choice


class InitialWindowFrame(ctk.CTkFrame):
    def __init__(
        self, master, config: ConfigManager, on_project_selected: Callable[[Project], None]
    ) -> None:
        super().__init__(master)
        self.config = config
        self.on_project_selected = on_project_selected

        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(expand=True)

        ctk.CTkLabel(container, text=config.text("app.title")).pack(pady=(0, 24))
        ctk.CTkButton(
            container, text=config.text("project.open_or_create"), command=self._open_or_create
        ).pack()

        self.path_entry = ctk.CTkEntry(container, width=320)
        self.path_entry.pack(pady=(20, 0))
        self._set_path_display(config.text("project.no_selection"))

    def _set_path_display(self, text: str) -> None:
        self.path_entry.configure(state="normal")
        self.path_entry.delete(0, "end")
        self.path_entry.insert(0, text)
        self.path_entry.configure(state="disabled")

    def _open_or_create(self) -> None:
        action = ask_choice(
            self,
            self.config.text("project.open_or_create"),
            [self.config.text("project.action.create"), self.config.text("project.action.open")],
            self.config.text("action.confirm"),
            self.config.text("action.cancel"),
        )
        if action == self.config.text("project.action.create"):
            self._create_project()
        elif action == self.config.text("project.action.open"):
            self._open_existing_project()

    def _create_project(self) -> None:
        models = discover_base_models(self.config.paths.base_models_root)
        if not models:
            self._set_path_display(self.config.text("scenario.error.parse_failed"))
            return
        watershed = ask_choice(
            self,
            self.config.text("watershed.select"),
            [m.watershed for m in models],
            self.config.text("action.confirm"),
            self.config.text("action.cancel"),
        )
        if watershed is None:
            return
        match = next(m for m in models if m.watershed == watershed)
        project = open_or_create_project(
            self.config.paths.workspace_root, match.watershed, match.model_dir, match.txtinout_dir
        )
        self._set_path_display(str(project.project_dir))
        self.on_project_selected(project)

    def _open_existing_project(self) -> None:
        directory = filedialog.askdirectory(
            parent=self, initialdir=str(self.config.paths.workspace_root)
        )
        if not directory:
            return
        project_dir = Path(directory)
        watershed = project_dir.name
        models = discover_base_models(self.config.paths.base_models_root)
        match = next((m for m in models if m.watershed == watershed), None)
        if match is None:
            self._set_path_display(self.config.text("scenario.error.parse_failed"))
            return
        project = Project(
            watershed=watershed,
            base_model_dir=match.model_dir,
            base_txtinout_dir=match.txtinout_dir,
            project_dir=project_dir,
        )
        self._set_path_display(str(project.project_dir))
        self.on_project_selected(project)
