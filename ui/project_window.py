from __future__ import annotations

import customtkinter as ctk

from config.settings import ConfigManager
from engine.configure import configure_scenario
from scenarios.draft import draft_csv_path
from scenarios.models import WETLAND_ABBREVIATIONS, Project, build_scenario_name
from ui.dialogs import ask_choice, ask_text
from ui.parametrizacion_view import ParametrizacionView


class ProjectWindowFrame(ctk.CTkFrame):
    def __init__(self, master, config: ConfigManager, project: Project) -> None:
        super().__init__(master)
        self.config = config
        self.project = project
        self.active_scenario_name: str | None = None

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=12)
        ctk.CTkLabel(header, text=project.watershed).pack(anchor="w")
        self.scenario_label = ctk.CTkLabel(header, text=config.text("project.no_scenario"))
        self.scenario_label.pack(anchor="w")

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=12)
        ctk.CTkButton(
            toolbar, text=config.text("wetland.form.title"), command=self._open_parametrizacion
        ).pack(side="left", padx=(0, 8))
        self.configure_button = ctk.CTkButton(
            toolbar, text=config.text("action.configure_scenario"),
            command=self._configure_scenario, state="disabled",
        )
        self.configure_button.pack(side="left")

        self.status_label = ctk.CTkLabel(self, text="")
        self.status_label.pack(fill="x", padx=12, pady=(8, 0))

        self.content = ctk.CTkFrame(self)
        self.content.pack(fill="both", expand=True, padx=12, pady=12)

    def _open_parametrizacion(self) -> None:
        name = self.active_scenario_name or self._prompt_scenario_name()
        if name is None:
            return
        self._activate_scenario(name)

    def _activate_scenario(self, name: str) -> None:
        self.active_scenario_name = name
        self.scenario_label.configure(text=name)
        self.configure_button.configure(state="normal")
        for child in self.content.winfo_children():
            child.destroy()
        view = ParametrizacionView(self.content, self.config, self.project, name)
        view.pack(fill="both", expand=True)

    def _prompt_scenario_name(self) -> str | None:
        abbreviation = ask_choice(
            self, self.config.text("scenario.abbreviation"), list(WETLAND_ABBREVIATIONS),
            self.config.text("action.confirm"), self.config.text("action.cancel"),
        )
        if abbreviation is None:
            return None
        timestep = ask_text(
            self, self.config.text("scenario.timestep"),
            self.config.text("action.confirm"), self.config.text("action.cancel"), default="annual",
        )
        if not timestep:
            return None
        try:
            name = build_scenario_name(self.project.watershed, abbreviation, timestep)
        except ValueError as exc:
            self.status_label.configure(text=str(exc))
            return None
        already_exists = draft_csv_path(self.project, name).exists() or (self.project.project_dir / name).exists()
        if already_exists:
            self.status_label.configure(text=self.config.text("scenario.error.duplicate_name"))
            return None
        return name

    def _configure_scenario(self) -> None:
        if self.active_scenario_name is None:
            return
        try:
            result = configure_scenario(
                self.project, self.active_scenario_name,
                self.config.paths.swat_executable, self.config.paths.target_executable_name,
            )
        except (FileNotFoundError, FileExistsError) as exc:
            self.status_label.configure(text=str(exc))
            return
        self.status_label.configure(text=str(result.scenario_dir))
        self.configure_button.configure(state="disabled")
