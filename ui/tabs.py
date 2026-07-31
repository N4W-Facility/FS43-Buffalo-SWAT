"""Barra de pestañas propia (no CTkTabview).

CTkTabview dibuja botones tipo segmento/píldora y no permite deshabilitar
una pestaña individual; el diseño acordado pide un subrayado azul fino
sobre fondo plano, y la pestaña Summary debe poder quedar deshabilitada
hasta que haya un proyecto abierto. Registrar una pestaña nueva es una
sola llamada a add_tab(), para que agregar futuras pestañas no toque el
resto de la UI.
"""
from __future__ import annotations

import customtkinter as ctk

from config.settings import ConfigManager

_UNDERLINE_HEIGHT = 2


class TabBar(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, config: ConfigManager, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._config = config
        self._colors = config.theme.get("AppPalette", {})

        self._bar = ctk.CTkFrame(self, fg_color="transparent")
        self._bar.pack(fill="x")

        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.pack(fill="both", expand=True, pady=(8, 0))

        self._tabs: dict[str, dict] = {}
        self._active_key: str | None = None
        self._navigation_locked = False

    def add_tab(self, key: str, label_key: str, view: ctk.CTkBaseClass, *, enabled: bool = True) -> None:
        container = ctk.CTkFrame(self._bar, fg_color="transparent")
        container.pack(side="left")

        button = ctk.CTkButton(
            container,
            text=self._config.text(label_key),
            fg_color="transparent",
            hover_color=self._colors.get("window_bg"),
            text_color=self._colors.get("text_primary"),
            corner_radius=0,
            command=lambda: self.select(key),
        )
        button.pack(fill="x", padx=12, pady=(6, 4))

        underline = ctk.CTkFrame(container, height=_UNDERLINE_HEIGHT, fg_color="transparent")
        underline.pack(fill="x")

        view.place(in_=self._content, relx=0, rely=0, relwidth=1, relheight=1)

        self._tabs[key] = {"button": button, "underline": underline, "view": view, "enabled": enabled}
        self._apply_enabled(key)

        if self._active_key is None and enabled:
            self.select(key)

    def set_enabled(self, key: str, enabled: bool) -> None:
        self._tabs[key]["enabled"] = enabled
        self._apply_enabled(key)
        if not enabled and self._active_key == key:
            for other_key, info in self._tabs.items():
                if info["enabled"]:
                    self.select(other_key)
                    break

    def select(self, key: str) -> None:
        info = self._tabs.get(key)
        if info is None or not info["enabled"]:
            return
        self._active_key = key
        for other_key, other_info in self._tabs.items():
            is_active = other_key == key
            other_info["button"].configure(
                text_color=self._colors.get("accent") if is_active else self._colors.get("text_primary"),
            )
            other_info["underline"].configure(
                fg_color=self._colors.get("accent") if is_active else "transparent",
            )
            if is_active:
                other_info["view"].tkraise()

    def set_navigation_locked(self, locked: bool) -> None:
        """Deshabilita el clic en todas las pestañas (sin tocar cuál está
        activa ni el flag "enabled" de cada una), para que el usuario no
        pueda navegar a otro lado mientras corre una operación larga."""
        self._navigation_locked = locked
        for key in self._tabs:
            self._apply_enabled(key)

    def _apply_enabled(self, key: str) -> None:
        info = self._tabs[key]
        enabled = info["enabled"] and not self._navigation_locked
        info["button"].configure(
            state="normal" if enabled else "disabled",
            text_color=self._colors.get("text_primary") if enabled else self._colors.get("disabled"),
        )
