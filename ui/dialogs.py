from __future__ import annotations

import customtkinter as ctk


def ask_choice(
    parent, title: str, options: list[str], confirm_text: str, cancel_text: str
) -> str | None:
    if not options:
        return None
    dialog = ctk.CTkToplevel(parent)
    dialog.title(title)
    dialog.grab_set()
    result: dict[str, str | None] = {"value": None}

    var = ctk.StringVar(value=options[0])
    ctk.CTkLabel(dialog, text=title).pack(padx=20, pady=(20, 8))
    ctk.CTkOptionMenu(dialog, variable=var, values=options).pack(padx=20, pady=8)

    def confirm() -> None:
        result["value"] = var.get()
        dialog.destroy()

    button_row = ctk.CTkFrame(dialog, fg_color="transparent")
    button_row.pack(pady=(8, 20))
    ctk.CTkButton(button_row, text=confirm_text, command=confirm).pack(side="left", padx=8)
    ctk.CTkButton(button_row, text=cancel_text, command=dialog.destroy).pack(side="left", padx=8)

    parent.wait_window(dialog)
    return result["value"]


def ask_text(parent, title: str, confirm_text: str, cancel_text: str, default: str = "") -> str | None:
    dialog = ctk.CTkToplevel(parent)
    dialog.title(title)
    dialog.grab_set()
    result: dict[str, str | None] = {"value": None}

    ctk.CTkLabel(dialog, text=title).pack(padx=20, pady=(20, 8))
    entry = ctk.CTkEntry(dialog)
    entry.insert(0, default)
    entry.pack(padx=20, pady=8)

    def confirm() -> None:
        result["value"] = entry.get()
        dialog.destroy()

    button_row = ctk.CTkFrame(dialog, fg_color="transparent")
    button_row.pack(pady=(8, 20))
    ctk.CTkButton(button_row, text=confirm_text, command=confirm).pack(side="left", padx=8)
    ctk.CTkButton(button_row, text=cancel_text, command=dialog.destroy).pack(side="left", padx=8)

    parent.wait_window(dialog)
    return result["value"]
