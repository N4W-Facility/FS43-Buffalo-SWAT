"""Ventana raíz: aplica el tema, monta la barra de pestañas, y sincroniza el
ProjectMetadata activo entre las pestañas Project y Summary.
"""
from __future__ import annotations

from pathlib import Path

import customtkinter as ctk

from config.settings import ConfigManager
from scenarios.project import ProjectMetadata

from .tab_hru import HRUsTab
from .tab_hru_results import HruResultsTab
from .tab_project import ProjectTab
from .tab_results import ResultsTab
from .tab_run import RunTab
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
        self._hru_tab = HRUsTab(self._tab_bar, config, on_run_state_changed=self._on_hru_run_state_changed)
        self._run_tab = RunTab(self._tab_bar, config, on_run_state_changed=self._on_run_tab_run_state_changed)
        self._results_tab = ResultsTab(
            self._tab_bar, config, on_run_state_changed=self._on_results_tab_run_state_changed
        )
        self._hru_results_tab = HruResultsTab(
            self._tab_bar, config, on_run_state_changed=self._on_hru_results_tab_run_state_changed
        )

        self._tab_bar.add_tab("project", "tab.project", self._project_tab, enabled=True)
        self._tab_bar.add_tab("summary", "tab.summary", self._summary_tab, enabled=False)
        self._tab_bar.add_tab("wetlands", "tab.wetlands", self._wetlands_tab, enabled=False)
        self._tab_bar.add_tab("hru", "tab.hru", self._hru_tab, enabled=False)
        self._tab_bar.add_tab("run", "tab.run", self._run_tab, enabled=False)
        self._tab_bar.add_tab("results", "tab.results", self._results_tab, enabled=False)
        self._tab_bar.add_tab("hru_results", "tab.hru_results", self._hru_results_tab, enabled=False)

    def _on_project_opened(self, project_dir: Path, metadata: ProjectMetadata) -> None:
        self._tab_bar.set_enabled("summary", True)
        self._summary_tab.set_project(project_dir, metadata)
        self._tab_bar.set_enabled("wetlands", True)
        self._wetlands_tab.set_project(project_dir)
        self._tab_bar.set_enabled("hru", True)
        self._hru_tab.set_project(project_dir)
        self._tab_bar.set_enabled("run", True)
        self._run_tab.set_project(project_dir)
        self._tab_bar.set_enabled("results", True)
        self._results_tab.set_project(project_dir, metadata)
        self._tab_bar.set_enabled("hru_results", True)
        self._hru_results_tab.set_project(project_dir)

    def _on_summary_run_state_changed(self, running: bool) -> None:
        """Mientras Summary corre un Run, bloquea toda navegación (pestañas y
        Open/Change/Edit de Project) para que el usuario no pueda cambiar de
        proyecto ni de pestaña a mitad de una operación de fondo."""
        self._tab_bar.set_navigation_locked(running)
        self._project_tab.set_locked(running)

    def _on_hru_run_state_changed(self, running: bool) -> None:
        """Mismo bloqueo que _on_summary_run_state_changed, mientras
        HRUsTab materializa staging en hilo de fondo: escribir sobre
        muchos .hru puede tardar, y cambiar de proyecto o pestaña a mitad
        de esa escritura dejaría el resultado en un estado inconsistente."""
        self._tab_bar.set_navigation_locked(running)
        self._project_tab.set_locked(running)

    def _on_run_tab_run_state_changed(self, running: bool) -> None:
        """Mismo bloqueo que las demás operaciones de fondo, mientras
        RunTab corre swat2012.exe: cambiar de proyecto a mitad de una
        corrida dejaría el subproceso escribiendo sobre un TxtInOut que
        la UI ya no considera activo."""
        self._tab_bar.set_navigation_locked(running)
        self._project_tab.set_locked(running)

    def _on_results_tab_run_state_changed(self, running: bool) -> None:
        """Mismo bloqueo que las demás operaciones de fondo, mientras
        ResultsTab parsea output.rch entero en Organize: cambiar de
        proyecto a mitad de esa lectura dejaría el hilo de fondo operando
        sobre un project_dir que la UI ya no considera activo."""
        self._tab_bar.set_navigation_locked(running)
        self._project_tab.set_locked(running)

    def _on_hru_results_tab_run_state_changed(self, running: bool) -> None:
        """Mismo bloqueo que las demás operaciones de fondo, mientras
        HruResultsTab parsea output.hru entero en Organize (puede pesar
        más de 1GB en salida Daily): cambiar de proyecto a mitad de esa
        lectura dejaría el hilo de fondo operando sobre un project_dir que
        la UI ya no considera activo."""
        self._tab_bar.set_navigation_locked(running)
        self._project_tab.set_locked(running)
