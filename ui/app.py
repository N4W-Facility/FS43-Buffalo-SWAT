from __future__ import annotations

import customtkinter as ctk

from config.settings import ConfigManager
from scenarios.models import Project
from ui.config_dialog import show_config_dialog
from ui.initial_window import InitialWindowFrame
from ui.project_window import ProjectWindowFrame


class App(ctk.CTk):
    def __init__(self) -> None:
        self.config_manager = ConfigManager()
        self.config_manager.load_all()
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme(str(self.config_manager.theme_path()))

        super().__init__()
        self.title(self.config_manager.text("app.title"))
        self.geometry("900x600")
        self._current_frame: ctk.CTkFrame | None = None

        if not self.config_manager.paths.is_complete():
            self.withdraw()
            show_config_dialog(self, self.config_manager, on_saved=self._start)
        else:
            self._start()

    def _start(self) -> None:
        self.deiconify()
        self.show_initial_window()

    def _set_frame(self, frame: ctk.CTkFrame) -> None:
        if self._current_frame is not None:
            self._current_frame.destroy()
        self._current_frame = frame
        frame.pack(fill="both", expand=True)

    def show_initial_window(self) -> None:
        self._set_frame(
            InitialWindowFrame(self, self.config_manager, on_project_selected=self.show_project_window)
        )

    def show_project_window(self, project: Project) -> None:
        self._set_frame(ProjectWindowFrame(self, self.config_manager, project))
