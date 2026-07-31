"""Piezas de UI compartidas entre pestañas.

Cero literales: todo texto viene de config.text(key), todo color de
config.theme["AppPalette"]. Ningún widget de este módulo sabe qué pestaña
lo usa.
"""
from __future__ import annotations

import customtkinter as ctk

from config.settings import ConfigManager

_PLACEHOLDER_VALUE = "—"  # em dash: valor aún no calculado


def palette(config: ConfigManager) -> dict:
    return config.theme.get("AppPalette", {})


class ReadOnlyField(ctk.CTkFrame):
    """Label secundario en mayúscula + valor en texto primario debajo."""

    def __init__(self, master: ctk.CTkBaseClass, config: ConfigManager, label_key: str, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        colors = palette(config)

        self._label = ctk.CTkLabel(
            self,
            text=config.text(label_key).upper(),
            text_color=colors.get("text_secondary"),
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        )
        self._label.pack(fill="x")

        self._value = ctk.CTkLabel(
            self,
            text="",
            text_color=colors.get("text_primary"),
            anchor="w",
            justify="left",
        )
        self._value.pack(fill="x", pady=(2, 0))

    def set_value(self, value: str) -> None:
        self._value.configure(text=value)


class SectionHeader(ctk.CTkFrame):
    """Título de grupo a la izquierda + timestamp secundario a la derecha."""

    def __init__(self, master: ctk.CTkBaseClass, config: ConfigManager, title_key: str, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        colors = palette(config)
        self.columnconfigure(0, weight=1)

        self._title = ctk.CTkLabel(
            self,
            text=config.text(title_key),
            text_color=colors.get("text_primary"),
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        )
        self._title.grid(row=0, column=0, sticky="w")

        self._timestamp = ctk.CTkLabel(
            self,
            text="",
            text_color=colors.get("text_secondary"),
            anchor="e",
        )
        self._timestamp.grid(row=0, column=1, sticky="e")

    def set_timestamp(self, text: str) -> None:
        self._timestamp.configure(text=text)


class StatCard(ctk.CTkFrame):
    """Tarjeta: valor grande arriba, label secundario debajo."""

    def __init__(self, master: ctk.CTkBaseClass, config: ConfigManager, label_key: str, **kwargs) -> None:
        kwargs.setdefault("corner_radius", 10)
        super().__init__(master, **kwargs)
        colors = palette(config)

        self._value = ctk.CTkLabel(
            self,
            text=_PLACEHOLDER_VALUE,
            text_color=colors.get("text_primary"),
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        self._value.pack(padx=16, pady=(14, 0))

        self._label = ctk.CTkLabel(
            self,
            text=config.text(label_key),
            text_color=colors.get("text_secondary"),
            font=ctk.CTkFont(size=11),
        )
        self._label.pack(padx=16, pady=(2, 14))

    def set_value(self, text: str | None) -> None:
        self._value.configure(text=text if text else _PLACEHOLDER_VALUE)
