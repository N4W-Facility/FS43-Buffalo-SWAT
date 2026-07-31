"""Ventana raíz: aplica el tema, monta la barra de pestañas, y sincroniza el
ProjectMetadata activo entre las pestañas Project y Summary.
"""
from __future__ import annotations

from pathlib import Path

import customtkinter as ctk

from config.settings import ConfigManager
from scenarios.project import ProjectMetadata

from .tab_project import ProjectTab
from .tab_summary import SummaryTab
from .tab_wetlands import WetlandsTab
from .tabs import TabBar

_WINDOW_SIZE = "980x800"


class App(ctk.CTk):
    def __init__(self, config: ConfigManager) -> None:
        ctk.set_default_color_theme(str(config.theme_path()))
        ctk.set_appearance_mode("light")
        super().__init__()

        self._config = config
        colors = config.theme.get("AppPalette", {})

        self.title(config.text("app.title"))
        self.geometry(_WINDOW_SIZE)
        self.configure(fg_color=colors.get("window_bg"))

        self._tab_bar = TabBar(self, config)
        self._tab_bar.pack(fill="both", expand=True, padx=16, pady=16)

        self._project_tab = ProjectTab(self._tab_bar, config, on_project_opened=self._on_project_opened)
        self._summary_tab = SummaryTab(
            self._tab_bar, config, on_run_state_changed=self._on_summary_run_state_changed
        )
        self._wetlands_tab = WetlandsTab(self._tab_bar, config)

        self._tab_bar.add_tab("project", "tab.project", self._project_tab, enabled=True)
        self._tab_bar.add_tab("summary", "tab.summary", self._summary_tab, enabled=False)
        self._tab_bar.add_tab("wetlands", "tab.wetlands", self._wetlands_tab, enabled=False)

    def _on_project_opened(self, project_dir: Path, metadata: ProjectMetadata) -> None:
        self._tab_bar.set_enabled("summary", True)
        self._summary_tab.set_project(project_dir, metadata)
        self._tab_bar.set_enabled("wetlands", True)
        self._wetlands_tab.set_project(project_dir)

    def _on_summary_run_state_changed(self, running: bool) -> None:
        """Mientras Summary corre un Run, bloquea toda navegación (pestañas y
        Open/Change/Edit de Project) para que el usuario no pueda cambiar de
        proyecto ni de pestaña a mitad de una operación de fondo."""
        self._tab_bar.set_navigation_locked(running)
        self._project_tab.set_locked(running)
