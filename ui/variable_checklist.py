"""Lista scrolleable de checkboxes reutilizada por cualquier selección de
variables: "Export selected variables" en HRU Results, y las dos listas
(RCH/HRU) de la ventana de exportación comparativa de Batch Scenarios.

Solo la lista en sí (checkboxes + scroll); "Select all"/"Clear" y el resto
del layout quedan a cargo de quien la embeba, porque cada ventana los
ubica distinto.
"""
from __future__ import annotations

import customtkinter as ctk

from .widgets import palette


class VariableChecklist(ctk.CTkScrollableFrame):
    def __init__(self, master: ctk.CTkBaseClass, config, options: list[tuple[str, str]], **kwargs) -> None:
        """options: lista de (code, label) en el orden en que deben mostrarse."""
        colors = palette(config)
        kwargs.setdefault("fg_color", colors.get("surface"))
        super().__init__(master, **kwargs)

        self._vars: dict[str, ctk.BooleanVar] = {}
        for code, label in options:
            var = ctk.BooleanVar(value=False)
            checkbox = ctk.CTkCheckBox(self, text=label, variable=var, text_color=colors.get("text_primary"))
            checkbox.pack(anchor="w", padx=8, pady=3)
            self._vars[code] = var

    def selected(self) -> list[str]:
        """Códigos marcados, en el mismo orden en que se pasaron en `options`."""
        return [code for code, var in self._vars.items() if var.get()]

    def set_selected(self, codes: set[str]) -> None:
        for code, var in self._vars.items():
            var.set(code in codes)

    def select_all(self) -> None:
        for var in self._vars.values():
            var.set(True)

    def select_none(self) -> None:
        for var in self._vars.values():
            var.set(False)
