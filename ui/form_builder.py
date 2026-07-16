from __future__ import annotations

from typing import Callable

import customtkinter as ctk


def build_wetland_form(
    parent: ctk.CTkFrame,
    config,
    layout: dict,
    initial_values: dict[str, float],
    on_commit: Callable[[str, float], None],
    on_error: Callable[[str, str], None],
) -> dict[str, ctk.CTkEntry]:
    entries: dict[str, ctk.CTkEntry] = {}
    for row, field in enumerate(layout["fields"]):
        ctk.CTkLabel(parent, text=config.text(field["label_key"])).grid(
            row=row, column=0, sticky="w", padx=8, pady=4
        )
        entry = ctk.CTkEntry(parent)
        entry.insert(0, str(initial_values.get(field["id"], "")))
        entry.grid(row=row, column=1, sticky="ew", padx=8, pady=4)

        def make_handler(field_id: str, entry_widget: ctk.CTkEntry) -> Callable[[object], None]:
            def handler(_event=None) -> None:
                raw = entry_widget.get()
                try:
                    value = float(raw)
                except ValueError:
                    on_error(field_id, f"'{raw}' no es un número válido.")
                    return
                try:
                    on_commit(field_id, value)
                except ValueError as exc:
                    on_error(field_id, str(exc))

            return handler

        handler = make_handler(field["id"], entry)
        entry.bind("<FocusOut>", handler)
        entry.bind("<Return>", handler)
        entries[field["id"]] = entry

    parent.grid_columnconfigure(1, weight=1)
    return entries
