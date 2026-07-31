"""Pestaña Project: abrir/cambiar de proyecto y ver/editar su metadata.

Un proyecto es una única carpeta que contiene TxtInOut/ directamente. Al
abrirla se lee (o se crea vacío, si no existe) su project.json.
"""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog
from typing import Callable

import customtkinter as ctk

from config.settings import ConfigManager
from scenarios.project import ProjectMetadata, is_valid_project_dir, load_project

from .dialog_project_edit import ProjectEditDialog
from .widgets import ReadOnlyField, palette

OnProjectOpened = Callable[[Path, ProjectMetadata], None]


class ProjectTab(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        config: ConfigManager,
        *,
        on_project_opened: OnProjectOpened,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._config = config
        self._colors = palette(config)
        self._on_project_opened = on_project_opened

        self._project_dir: Path | None = None
        self._metadata: ProjectMetadata = ProjectMetadata()

        self._empty_state = self._build_empty_state()
        self._loaded_state = self._build_loaded_state()

        self._empty_state.pack(fill="both", expand=True)

    def _build_empty_state(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self, fg_color="transparent")

        center = ctk.CTkFrame(frame, fg_color="transparent")
        center.place(relx=0.5, rely=0.4, anchor="center")

        self._open_button = ctk.CTkButton(
            center, text=self._config.text("project.open"), command=self._on_open_clicked
        )
        self._open_button.pack()

        hint = ctk.CTkLabel(
            center,
            text=self._config.text("project.empty_hint"),
            text_color=self._colors.get("text_secondary"),
        )
        hint.pack(pady=(10, 0))

        self._error_label = ctk.CTkLabel(center, text="", text_color=self._colors.get("error"))
        self._error_label.pack(pady=(10, 0))

        return frame

    def _build_loaded_state(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.columnconfigure(0, weight=1)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        self._path_label = ctk.CTkLabel(
            header, text="", text_color=self._colors.get("text_secondary"), anchor="w"
        )
        self._path_label.grid(row=0, column=0, sticky="w")

        self._change_button = ctk.CTkButton(
            header,
            text=self._config.text("project.change"),
            fg_color="transparent",
            border_width=1,
            border_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"),
            hover_color=self._colors.get("window_bg"),
            width=70,
            command=self._on_open_clicked,
        )
        self._change_button.grid(row=0, column=1, sticky="e")

        separator = ctk.CTkFrame(frame, height=1, fg_color=self._colors.get("border"))
        separator.grid(row=1, column=0, columnspan=2, sticky="ew", pady=12)

        info_card = ctk.CTkFrame(frame)
        info_card.grid(row=2, column=0, columnspan=2, sticky="new")
        info_card.columnconfigure(0, weight=1)

        name_row = ctk.CTkFrame(info_card, fg_color="transparent")
        name_row.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        name_row.columnconfigure(0, weight=1)

        self._name_field = ReadOnlyField(name_row, self._config, "project.name")
        self._name_field.grid(row=0, column=0, sticky="ew")

        self._edit_button = ctk.CTkButton(
            name_row,
            text=self._config.text("project.edit"),
            fg_color="transparent",
            border_width=1,
            border_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"),
            hover_color=self._colors.get("window_bg"),
            width=70,
            command=self._on_edit_clicked,
        )
        self._edit_button.grid(row=0, column=1, sticky="ne", padx=(12, 0))

        self._description_field = ReadOnlyField(info_card, self._config, "project.description")
        self._description_field.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 16))

        return frame

    def _on_open_clicked(self) -> None:
        selected = filedialog.askdirectory()
        if not selected:
            return
        project_dir = Path(selected)
        if not is_valid_project_dir(project_dir):
            self._error_label.configure(text=self._config.text("project.error.no_txtinout"))
            return
        self._error_label.configure(text="")
        self._open_project(project_dir)

    def _on_edit_clicked(self) -> None:
        if self._project_dir is None:
            return
        dialog = ProjectEditDialog(self, self._config, self._metadata, self._project_dir)
        self.wait_window(dialog)
        if dialog.saved_metadata is not None:
            self._metadata = dialog.saved_metadata
            self._refresh_fields()
            self._on_project_opened(self._project_dir, self._metadata)

    def _open_project(self, project_dir: Path) -> None:
        self._project_dir = project_dir
        self._metadata = load_project(project_dir)
        self._refresh_fields()
        self._loaded_state.pack(fill="both", expand=True)
        self._empty_state.pack_forget()
        self._on_project_opened(project_dir, self._metadata)

    def _refresh_fields(self) -> None:
        self._path_label.configure(text=str(self._project_dir))
        self._name_field.set_value(self._metadata.name)
        self._description_field.set_value(self._metadata.description)

    def set_locked(self, locked: bool) -> None:
        """Deshabilita Open/Change/Edit mientras Summary corre un Run: cambiar
        de proyecto a mitad de una corrida rompería el project_dir que el
        hilo de fondo está usando."""
        state = "disabled" if locked else "normal"
        self._open_button.configure(state=state)
        self._change_button.configure(state=state)
        self._edit_button.configure(state=state)
