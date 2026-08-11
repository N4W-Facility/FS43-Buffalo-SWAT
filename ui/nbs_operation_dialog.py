"""Diálogo modal para agregar/editar UNA operación del calendario de manejo
de una NbS (ver ui/nbs_wizard_window.py, paso "Management calendar").

El tipo de operación (MGT_OP) determina qué campos aparecen -- se leen de
swat_io.mgt.operation_specs.OPERATION_FIELD_SPECS, con nombre legible vía
config.nbs_parameter_labels.label_for. Programación por mes/día O por HUSC
(fracción de heat units), nunca ambas (ver SWAT2012 IO doc cap. 20): un
selector alterna cuál de los dos grupos de campos queda habilitado.
"""
from __future__ import annotations

from tkinter import ttk
from typing import Callable

import customtkinter as ctk

from config.nbs_parameter_labels import label_for
from config.settings import ConfigManager
from scenarios.nbs import NbSOperation
from swat_io.mgt.operation_specs import MGT_OPERATION_NAMES, OPERATION_FIELD_SPECS

from .widgets import palette, style_combobox

_SCHEDULE_BY_DATE = "date"
_SCHEDULE_BY_HUSC = "husc"


class NbSOperationDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        config: ConfigManager,
        *,
        on_confirm: Callable[[NbSOperation], None],
        initial: NbSOperation | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self._config = config
        self._colors = palette(config)
        self._on_confirm = on_confirm
        self._field_widgets: dict[str, ctk.CTkEntry] = {}

        self.title(config.text("nbs_wizard.operation_dialog.title"))
        self.configure(fg_color=self._colors.get("window_bg"))
        self.geometry("480x560")
        self.transient(master)

        self._body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._body.pack(fill="both", expand=True, padx=20, pady=(20, 0))
        self._body.columnconfigure(0, weight=1)

        self._build_type_selector()
        self._build_schedule_selector()
        self._schedule_frame = ctk.CTkFrame(self._body, fg_color="transparent")
        self._schedule_frame.grid(row=3, column=0, sticky="ew", pady=(8, 12))
        self._schedule_frame.columnconfigure((0, 1), weight=1)
        self._build_schedule_fields()

        self._fields_frame = ctk.CTkFrame(self._body, fg_color="transparent")
        self._fields_frame.grid(row=4, column=0, sticky="ew")
        self._fields_frame.columnconfigure(0, weight=1)

        self._status_label = ctk.CTkLabel(self, text="", text_color=self._colors.get("error"), anchor="w")
        self._status_label.pack(fill="x", padx=20, pady=(8, 0))

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=20, pady=20)
        ctk.CTkButton(
            actions,
            text=config.text("action.cancel"),
            fg_color="transparent",
            border_width=1,
            border_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"),
            hover_color=self._colors.get("window_bg"),
            command=self.destroy,
        ).pack(side="right")
        ctk.CTkButton(
            actions, text=config.text("nbs_wizard.operation_dialog.add_button"), command=self._on_confirm_clicked
        ).pack(side="right", padx=(0, 8))

        if initial is not None:
            self._load_initial(initial)
        else:
            self._on_type_selected()

        self.grab_set()

    # -- construcción -----------------------------------------------------

    def _build_type_selector(self) -> None:
        label = ctk.CTkLabel(
            self._body, text=self._config.text("nbs_wizard.operation_dialog.type_label"),
            text_color=self._colors.get("text_secondary"), anchor="w",
        )
        label.grid(row=0, column=0, sticky="w")

        self._type_values = [f"{code} — {name}" for code, name in sorted(MGT_OPERATION_NAMES.items())]
        self._type_codes = [code for code, _ in sorted(MGT_OPERATION_NAMES.items())]
        style = style_combobox(self._config)
        self._type_selector = ttk.Combobox(
            self._body, style=style, state="readonly", values=self._type_values, width=40
        )
        self._type_selector.current(0)
        self._type_selector.grid(row=1, column=0, sticky="ew", pady=(4, 12))
        self._type_selector.bind("<<ComboboxSelected>>", lambda _e: self._on_type_selected())

    def _build_schedule_selector(self) -> None:
        self._schedule_mode = ctk.StringVar(value=_SCHEDULE_BY_HUSC)
        frame = ctk.CTkFrame(self._body, fg_color="transparent")
        frame.grid(row=2, column=0, sticky="w", pady=(4, 0))
        ctk.CTkRadioButton(
            frame, text=self._config.text("nbs_wizard.operation_dialog.schedule_husc"),
            variable=self._schedule_mode, value=_SCHEDULE_BY_HUSC, command=self._on_schedule_mode_changed,
        ).pack(side="left", padx=(0, 16))
        ctk.CTkRadioButton(
            frame, text=self._config.text("nbs_wizard.operation_dialog.schedule_date"),
            variable=self._schedule_mode, value=_SCHEDULE_BY_DATE, command=self._on_schedule_mode_changed,
        ).pack(side="left")

    def _build_schedule_fields(self) -> None:
        self._husc_entry = ctk.CTkEntry(self._schedule_frame, placeholder_text="0.150")
        self._month_entry = ctk.CTkEntry(self._schedule_frame, placeholder_text="MM")
        self._day_entry = ctk.CTkEntry(self._schedule_frame, placeholder_text="DD")
        self._refresh_schedule_widgets()

    def _refresh_schedule_widgets(self) -> None:
        for child in self._schedule_frame.winfo_children():
            child.grid_forget()
        if self._schedule_mode.get() == _SCHEDULE_BY_HUSC:
            label = ctk.CTkLabel(
                self._schedule_frame, text=label_for("HUSC"), text_color=self._colors.get("text_secondary")
            )
            label.grid(row=0, column=0, sticky="w")
            self._husc_entry.grid(row=1, column=0, sticky="ew")
        else:
            month_label = ctk.CTkLabel(
                self._schedule_frame, text=label_for("MONTH"), text_color=self._colors.get("text_secondary")
            )
            month_label.grid(row=0, column=0, sticky="w")
            self._month_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))
            day_label = ctk.CTkLabel(
                self._schedule_frame, text=label_for("DAY"), text_color=self._colors.get("text_secondary")
            )
            day_label.grid(row=0, column=1, sticky="w")
            self._day_entry.grid(row=1, column=1, sticky="ew")

    def _on_schedule_mode_changed(self) -> None:
        self._refresh_schedule_widgets()

    def _current_mgt_op(self) -> int:
        index = self._type_selector.current()
        return self._type_codes[index if index >= 0 else 0]

    def _on_type_selected(self) -> None:
        mgt_op = self._current_mgt_op()
        for child in self._fields_frame.winfo_children():
            child.destroy()
        self._field_widgets = {}

        specs = [s for s in OPERATION_FIELD_SPECS.get(mgt_op, ()) if s.name != "PLANT_ID"]
        if not specs:
            hint = ctk.CTkLabel(
                self._fields_frame,
                text=self._config.text("nbs_wizard.operation_dialog.no_fields_hint"),
                text_color=self._colors.get("text_secondary"), anchor="w",
            )
            hint.grid(row=0, column=0, sticky="w")
            return

        if mgt_op == 1:
            note = ctk.CTkLabel(
                self._fields_frame,
                text=self._config.text("nbs_wizard.operation_dialog.plant_id_note"),
                text_color=self._colors.get("text_secondary"), anchor="w", justify="left", wraplength=420,
            )
            note.grid(row=0, column=0, sticky="w", pady=(0, 8))

        for row, spec in enumerate(specs, start=1):
            label = ctk.CTkLabel(
                self._fields_frame, text=label_for(spec.name), text_color=self._colors.get("text_secondary"),
                anchor="w", wraplength=420, justify="left",
            )
            label.grid(row=row * 2 - 1, column=0, sticky="w", pady=(8, 2))
            entry = ctk.CTkEntry(self._fields_frame)
            entry.grid(row=row * 2, column=0, sticky="ew")
            self._field_widgets[spec.name] = entry

    # -- carga de valores iniciales (edición) ------------------------------

    def _load_initial(self, op: NbSOperation) -> None:
        if op.mgt_op in self._type_codes:
            self._type_selector.current(self._type_codes.index(op.mgt_op))
        self._on_type_selected()

        if op.husc is not None:
            self._schedule_mode.set(_SCHEDULE_BY_HUSC)
            self._husc_entry.insert(0, str(op.husc))
        else:
            self._schedule_mode.set(_SCHEDULE_BY_DATE)
            if op.month is not None:
                self._month_entry.insert(0, str(op.month))
            if op.day is not None:
                self._day_entry.insert(0, str(op.day))
        self._refresh_schedule_widgets()

        for name, widget in self._field_widgets.items():
            value = op.fields.get(name)
            if value is not None:
                widget.insert(0, str(value))

    # -- confirmación -------------------------------------------------------

    def _on_confirm_clicked(self) -> None:
        try:
            month = day = husc = None
            if self._schedule_mode.get() == _SCHEDULE_BY_HUSC:
                raw = self._husc_entry.get().strip()
                if not raw:
                    raise ValueError(self._config.text("nbs_wizard.operation_dialog.schedule_required"))
                husc = float(raw)
            else:
                raw_month = self._month_entry.get().strip()
                raw_day = self._day_entry.get().strip()
                if not raw_month or not raw_day:
                    raise ValueError(self._config.text("nbs_wizard.operation_dialog.schedule_required"))
                month, day = int(raw_month), int(raw_day)

            fields: dict[str, float | int | None] = {}
            for name, widget in self._field_widgets.items():
                raw = widget.get().strip()
                fields[name] = float(raw) if raw else None

            operation = NbSOperation(mgt_op=self._current_mgt_op(), month=month, day=day, husc=husc, fields=fields)
        except ValueError as error:
            self._status_label.configure(text=str(error))
            return

        self.destroy()
        self._on_confirm(operation)
