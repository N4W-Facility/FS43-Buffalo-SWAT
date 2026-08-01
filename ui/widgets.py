"""Piezas de UI compartidas entre pestañas.

Cero literales: todo texto viene de config.text(key), todo color de
config.theme["AppPalette"]. Ningún widget de este módulo sabe qué pestaña
lo usa.
"""
from __future__ import annotations

from tkinter import ttk

import customtkinter as ctk

from config.settings import ConfigManager

_PLACEHOLDER_VALUE = "—"  # em dash: valor aún no calculado
_COMBOBOX_STYLE_NAME = "Swat.TCombobox"


def palette(config: ConfigManager) -> dict:
    return config.theme.get("AppPalette", {})


def style_combobox(config: ConfigManager) -> str:
    """Configura (si hace falta) y devuelve el nombre de estilo ttk
    compartido para los selectores largos de la app (subcuenca, HRU).

    ttk.Combobox en vez de CTkOptionMenu: el desplegable de CTkOptionMenu
    no tiene alto máximo ni scroll -- con muchos ítems (subcuencas, HRU)
    crece sin límite y se sale de la pantalla. El desplegable de
    ttk.Combobox usa el control nativo del SO, que scrollea solo. Mismo
    motivo por el que las tablas usan ttk.Treeview en vez de un widget CTk.
    Idempotente: llamarla varias veces desde distintos widgets solo
    reconfigura el mismo estilo compartido, no crea uno nuevo por widget.

    Dos capas a pelar del look "Windows 98" por defecto de clam:
    1. El campo cerrado: clam dibuja un bisel de 3 tonos (lightcolor
       arriba/izq, darkcolor abajo/der) aunque no se pida relieve
       explícito -- si no se igualan light/dark al fondo, se ve un borde
       hundido tipo Win95/98 sin importar qué color de borde se use.
    2. El desplegable abierto: la lista de opciones NO es un widget ttk,
       es un tk.Listbox plano -- style.configure no la toca en absoluto.
       Sin esto se queda con los grises/borde hundido nativos del SO,
       que es la parte más "retro" del combo y la que más contrasta con
       el resto de la UI (CTk plana, sin biseles).
    """
    colors = palette(config)
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(
        _COMBOBOX_STYLE_NAME,
        relief="flat",
        borderwidth=1,
        padding=(8, 6),
        arrowsize=12,
        fieldbackground=colors.get("surface"),
        background=colors.get("surface"),
        foreground=colors.get("text_primary"),
        arrowcolor=colors.get("text_secondary"),
        bordercolor=colors.get("border"),
        lightcolor=colors.get("surface"),
        darkcolor=colors.get("surface"),
    )
    style.map(
        _COMBOBOX_STYLE_NAME,
        fieldbackground=[("readonly", colors.get("surface")), ("disabled", colors.get("window_bg"))],
        foreground=[("disabled", colors.get("disabled"))],
        background=[("readonly", colors.get("surface")), ("active", colors.get("window_bg"))],
        bordercolor=[("focus", colors.get("accent")), ("hover", colors.get("accent"))],
        arrowcolor=[("disabled", colors.get("disabled")), ("hover", colors.get("accent"))],
        lightcolor=[("focus", colors.get("surface"))],
        darkcolor=[("focus", colors.get("surface"))],
    )

    root = style.master
    root.option_add("*TCombobox*Listbox.background", colors.get("surface"))
    root.option_add("*TCombobox*Listbox.foreground", colors.get("text_primary"))
    root.option_add("*TCombobox*Listbox.selectBackground", colors.get("accent"))
    root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
    root.option_add("*TCombobox*Listbox.borderWidth", 0)
    root.option_add("*TCombobox*Listbox.relief", "flat")
    root.option_add("*TCombobox*Listbox.activeStyle", "none")

    return _COMBOBOX_STYLE_NAME


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
