from __future__ import annotations

from pathlib import Path
from tkinter import filedialog
from typing import Callable

import customtkinter as ctk

from config.settings import AppPaths, ConfigManager, validate_app_paths


def show_config_dialog(
    parent, config: ConfigManager, on_saved: Callable[[], None]
) -> ctk.CTkToplevel:
    dialog = ctk.CTkToplevel(parent)
    dialog.title(config.text("config.title"))
    dialog.geometry("560x360")
    dialog.grab_set()

    entries: dict[str, ctk.CTkEntry] = {}
    error_label = ctk.CTkLabel(dialog, text="", text_color="#B3261E")

    def add_path_row(row: int, label_key: str, field: str, select_dir: bool) -> None:
        ctk.CTkLabel(dialog, text=config.text(label_key)).grid(
            row=row, column=0, sticky="w", padx=12, pady=8
        )
        entry = ctk.CTkEntry(dialog, width=280)
        current = getattr(config.paths, field)
        if current:
            entry.insert(0, str(current))
        entry.grid(row=row, column=1, sticky="ew", padx=6, pady=8)
        entries[field] = entry

        def browse() -> None:
            path = (
                filedialog.askdirectory(parent=dialog)
                if select_dir
                else filedialog.askopenfilename(parent=dialog)
            )
            if path:
                entry.delete(0, "end")
                entry.insert(0, path)

        ctk.CTkButton(dialog, text=config.text("config.browse"), command=browse).grid(
            row=row, column=2, padx=12, pady=8
        )

    add_path_row(0, "config.executable_path", "swat_executable", select_dir=False)
    add_path_row(1, "config.base_models_root", "base_models_root", select_dir=True)
    add_path_row(2, "config.workspace_root", "workspace_root", select_dir=True)

    ctk.CTkLabel(dialog, text=config.text("config.target_executable_name")).grid(
        row=3, column=0, sticky="w", padx=12, pady=8
    )
    exe_name_entry = ctk.CTkEntry(dialog, width=280)
    exe_name_entry.insert(0, config.paths.target_executable_name)
    exe_name_entry.grid(row=3, column=1, sticky="ew", padx=6, pady=8)

    error_label.grid(row=4, column=0, columnspan=3, sticky="w", padx=12)

    def save() -> None:
        swat_executable_text = entries["swat_executable"].get().strip()
        base_models_root_text = entries["base_models_root"].get().strip()
        workspace_root_text = entries["workspace_root"].get().strip()

        if not swat_executable_text or not base_models_root_text or not workspace_root_text:
            error_label.configure(text=config.text("config.error.missing_path"))
            return

        swat_executable = Path(swat_executable_text)
        base_models_root = Path(base_models_root_text)
        workspace_root = Path(workspace_root_text)

        error_key = validate_app_paths(swat_executable, base_models_root, workspace_root)
        if error_key is not None:
            error_label.configure(text=config.text(error_key))
            return

        config.save_paths(
            AppPaths(
                swat_executable=swat_executable,
                base_models_root=base_models_root,
                workspace_root=workspace_root,
                target_executable_name=exe_name_entry.get().strip() or "swatUser.exe",
            )
        )
        dialog.destroy()
        on_saved()

    save_button = ctk.CTkButton(dialog, text=config.text("config.save"), command=save)
    save_button.grid(row=5, column=0, columnspan=3, pady=16)
    dialog.grid_columnconfigure(1, weight=1)

    dialog.entries = entries
    dialog.error_label = error_label
    dialog.save_button = save_button
    return dialog
