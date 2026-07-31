"""Diálogo modal genérico de confirmación: mensaje + Guardar/Cancelar.

Cancelar solo cierra el diálogo — el llamador decide qué pasa con el
estado de edición en curso. Guardar dispara on_confirm y cierra.
"""
from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from config.settings import ConfigManager

from .widgets import palette


class ConfirmDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        config: ConfigManager,
        *,
        message: str,
        on_confirm: Callable[[], None],
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        colors = palette(config)
        self.title(config.text("action.confirm"))
        self.configure(fg_color=colors.get("window_bg"))
        self.transient(master)

        label = ctk.CTkLabel(
            self, text=message, text_color=colors.get("text_primary"), wraplength=320, justify="left"
        )
        label.pack(fill="both", expand=True, padx=20, pady=20)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=20, pady=(0, 20))

        cancel_button = ctk.CTkButton(
            actions,
            text=config.text("action.cancel"),
            fg_color="transparent",
            border_width=1,
            border_color=colors.get("border"),
            text_color=colors.get("text_primary"),
            hover_color=colors.get("window_bg"),
            command=self.destroy,
        )
        cancel_button.pack(side="right")

        def _confirm() -> None:
            self.destroy()
            on_confirm()

        save_button = ctk.CTkButton(actions, text=config.text("action.save"), command=_confirm)
        save_button.pack(side="right", padx=(0, 8))

        self.grab_set()
