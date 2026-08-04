"""Ventana modal para elegir un subconjunto de variables por checkbox.

Solo decide *qué* variables exportar -- no toca ningún archivo ni hace
diálogo de guardado: al confirmar, cierra y devuelve la lista de códigos
elegidos vía on_confirm, dejando que el llamador (la pestaña) haga el
filedialog + la exportación real y muestre su propio status, igual que ya
hacen los demás botones de export de HRU Results.
"""
from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from config.settings import ConfigManager

from .variable_checklist import VariableChecklist
from .widgets import palette


class VariableSelectionWindow(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        config: ConfigManager,
        *,
        title_key: str,
        options: list[tuple[str, str]],
        on_confirm: Callable[[list[str]], None],
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        colors = palette(config)
        self.title(config.text(title_key))
        self.configure(fg_color=colors.get("window_bg"))
        self.transient(master)
        self.geometry("420x520")

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(16, 8))

        select_all_button = ctk.CTkButton(
            header,
            text=config.text("variable_selection_window.select_all"),
            fg_color="transparent",
            border_width=1,
            border_color=colors.get("border"),
            text_color=colors.get("text_primary"),
            hover_color=colors.get("window_bg"),
            width=90,
            command=lambda: self._checklist.select_all(),
        )
        select_all_button.pack(side="left")

        clear_button = ctk.CTkButton(
            header,
            text=config.text("variable_selection_window.clear"),
            fg_color="transparent",
            border_width=1,
            border_color=colors.get("border"),
            text_color=colors.get("text_primary"),
            hover_color=colors.get("window_bg"),
            width=90,
            command=lambda: self._checklist.select_none(),
        )
        clear_button.pack(side="left", padx=(8, 0))

        self._checklist = VariableChecklist(self, config, options)
        self._checklist.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        self._hint_label = ctk.CTkLabel(self, text="", text_color=colors.get("error"), anchor="w")
        self._hint_label.pack(fill="x", padx=16)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=16)

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
            selected = self._checklist.selected()
            if not selected:
                self._hint_label.configure(text=config.text("variable_selection_window.empty_selection_hint"))
                return
            self.destroy()
            on_confirm(selected)

        export_button = ctk.CTkButton(actions, text=config.text("variable_selection_window.export_button"), command=_confirm)
        export_button.pack(side="right", padx=(0, 8))

        self.grab_set()
