"""Pestaña NbS: biblioteca de Soluciones basadas en la Naturaleza (cambios
de cobertura reutilizables, ver scenarios/nbs.py) y su aplicación masiva a
HRU reales.

Dos secciones independientes:

- Biblioteca: lista las NbS ya creadas del proyecto (JSON en
  tool_outputs/nbs_library.json). "New NbS..." abre el wizard
  (ui.nbs_wizard_window.NbSWizardWindow), que solo escribe en esa
  biblioteca -- nunca toca TxtInOut. El usuario puede crear varias NbS
  antes de aplicar ninguna (pedido explícito del usuario).
- Aplicar: selector de subcuenca + lista de HRU (multi-selección) para
  construir una lista de HRU objetivo; "Apply NbS" escribe de verdad sobre
  plant.dat/.hru/.mgt reales del proyecto abierto (scenarios.nbs_apply,
  mismo patrón in-place ya aceptado para Wetlands/HRUs) -- por eso, a
  diferencia de crear una NbS, pide confirmación y corre en hilo de fondo
  (ui.tasks.run_in_background, patrón obligatorio de CLAUDE.md: puede
  tocar muchas HRU y plant.dat es compartido por toda la cuenca).

Deshabilitada (vía TabBar.set_enabled) hasta que haya un proyecto abierto.
"""
from __future__ import annotations

import os
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Callable

import customtkinter as ctk

from config.cpnm_names import name_for
from config.settings import ConfigManager
from scenarios.hru_draft import list_subbasin_hru_ids, load_subbasin_hru_files
from scenarios.nbs import NbSDefinition, delete_definition, load_library
from scenarios.nbs_apply import NbSApplyReport, apply_nbs, write_apply_report_csv
from scenarios.nbs_area_apply import (
    AreaAllocationPlan,
    parse_priority_text,
    plan_area_allocation,
    subbasin_land_uses,
    validate_source_allocations,
)
from scenarios.nbs_mass_apply import (
    MassAreaAllocationResult,
    parse_mass_allocation_csv,
    plan_mass_area_allocation,
    write_mass_allocation_template_csv,
)
from swat_io.discovery import discover_subbasins
from swat_io.sub_parser import parse_sub_file
from swat_io.tool_outputs import tool_outputs_dir

from .dialog_confirm import ConfirmDialog
from .nbs_wizard_window import NbSWizardWindow
from .tasks import run_in_background
from .widgets import ReadOnlyField, bind_responsive_wraplength, build_scrollable_treeview, palette, style_combobox

# Misma tolerancia que scenarios.nbs_area_apply.validate_source_allocations
# (_DEFAULT_PCT_SUM_TOLERANCE) -- para que "completo" en la UI coincida
# exactamente con lo que el backend acepta al calcular el plan.
_AREA_PCT_SUM_TOLERANCE = 0.5


class NbSTab(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        config: ConfigManager,
        *,
        on_run_state_changed: Callable[[bool], None] = lambda running: None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._config = config
        self._colors = palette(config)
        self._on_run_state_changed = on_run_state_changed

        self._project_dir: Path | None = None
        self._library: list[NbSDefinition] = []
        self._subbasins: list[int] = []
        self._targets: list[tuple[int, int]] = []
        self._area_source_rows: list[tuple[str, float]] = []
        self._area_coverage_request_id = 0
        self._mass_allocations: dict[int, list[tuple[str, float]]] = {}

        self._disabled_state = self._build_disabled_state()
        self._enabled_state = self._build_enabled_state()
        self._disabled_state.pack(fill="both", expand=True)

    # -- construcción ---------------------------------------------------------

    def _build_disabled_state(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        hint = ctk.CTkLabel(
            frame, text=self._config.text("nbs_tab.disabled_hint"), text_color=self._colors.get("text_secondary")
        )
        hint.place(relx=0.5, rely=0.4, anchor="center")
        return frame

    def _build_enabled_state(self) -> ctk.CTkFrame:
        # Scrollable en vez de CTkFrame plano (mismo criterio que Summary/
        # Results/HRU Results): con la biblioteca más las dos tarjetas de
        # aplicar (manual y por área), el contenido supera el alto de la
        # ventana en pantallas chicas.
        frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        frame.columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            frame, text=self._config.text("nbs_tab.title"), text_color=self._colors.get("accent"),
            font=ctk.CTkFont(size=18, weight="bold"), anchor="w",
        )
        title.grid(row=0, column=0, sticky="w", pady=(0, 4))

        subtitle = ctk.CTkLabel(
            frame, text=self._config.text("nbs_tab.subtitle"), text_color=self._colors.get("text_secondary"),
            anchor="w", justify="left",
        )
        subtitle.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        bind_responsive_wraplength(subtitle)

        self._build_library_card(frame, row=2)
        self._build_apply_card(frame, row=3)
        self._build_area_apply_card(frame, row=4)
        self._build_mass_area_apply_card(frame, row=5)

        return frame

    def _build_library_card(self, parent: ctk.CTkFrame, *, row: int) -> None:
        card = ctk.CTkFrame(parent)
        card.grid(row=row, column=0, sticky="ew", pady=(0, 16))
        card.columnconfigure(0, weight=1)

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        header.columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text=self._config.text("nbs_tab.library_title"), text_color=self._colors.get("text_primary"),
            font=ctk.CTkFont(size=14, weight="bold"), anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            header, text=self._config.text("nbs_tab.open_folder_button"),
            fg_color="transparent", border_width=1, border_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"), hover_color=self._colors.get("window_bg"),
            command=self._on_open_library_folder_clicked, width=110,
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))
        self._edit_button = ctk.CTkButton(
            header, text=self._config.text("nbs_tab.edit_button"),
            fg_color="transparent", border_width=1, border_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"), hover_color=self._colors.get("window_bg"),
            command=self._on_edit_clicked, width=90, state="disabled",
        )
        self._edit_button.grid(row=0, column=2, sticky="e", padx=(8, 0))
        self._delete_button = ctk.CTkButton(
            header, text=self._config.text("nbs_tab.delete_button"),
            fg_color="transparent", border_width=1, border_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"), hover_color=self._colors.get("window_bg"),
            command=self._on_delete_clicked, width=90, state="disabled",
        )
        self._delete_button.grid(row=0, column=3, sticky="e", padx=(8, 0))
        ctk.CTkButton(
            header, text=self._config.text("nbs_tab.new_button"), command=self._on_new_nbs_clicked, width=110
        ).grid(row=0, column=4, sticky="e", padx=(8, 0))

        columns = ("name", "target", "mode", "ops", "description")
        self._library_tree, tree_container = build_scrollable_treeview(
            card, self._config, columns=columns, height=6, style_prefix="NbSLibrary"
        )
        for col, key, width in (
            ("name", "nbs_tab.col_name", 140),
            ("target", "nbs_tab.col_target", 160),
            ("mode", "nbs_tab.col_mode", 100),
            ("ops", "nbs_tab.col_ops", 60),
            ("description", "nbs_tab.col_description", 300),
        ):
            self._library_tree.heading(col, text=self._config.text(key))
            self._library_tree.column(col, width=width, anchor="w" if col != "ops" else "center", stretch=False)
        tree_container.grid(row=1, column=0, columnspan=5, sticky="ew", padx=16, pady=(0, 16))
        self._library_tree.bind("<<TreeviewSelect>>", lambda _e: self._on_library_selection_changed())
        self._library_tree.bind("<Double-1>", lambda _e: self._on_edit_clicked())

    def _build_apply_card(self, parent: ctk.CTkFrame, *, row: int) -> None:
        card = ctk.CTkFrame(parent)
        card.grid(row=row, column=0, sticky="ew")
        card.columnconfigure(0, weight=1)
        parent.rowconfigure(row, weight=1)

        ctk.CTkLabel(
            card, text=self._config.text("nbs_tab.apply_title"), text_color=self._colors.get("text_primary"),
            font=ctk.CTkFont(size=14, weight="bold"), anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))

        nbs_row = ctk.CTkFrame(card, fg_color="transparent")
        nbs_row.grid(row=1, column=0, sticky="ew", padx=16)
        nbs_row.columnconfigure(1, weight=1)
        ctk.CTkLabel(
            nbs_row, text=self._config.text("nbs_tab.select_nbs_label"), text_color=self._colors.get("text_secondary")
        ).grid(row=0, column=0, sticky="w")
        style = style_combobox(self._config)
        self._nbs_selector = ttk.Combobox(nbs_row, style=style, state="readonly", values=[], width=40)
        self._nbs_selector.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        selector_row = ctk.CTkFrame(card, fg_color="transparent")
        selector_row.grid(row=2, column=0, sticky="ew", padx=16, pady=(12, 4))

        subbasin_col = ctk.CTkFrame(selector_row, fg_color="transparent")
        subbasin_col.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(
            subbasin_col, text=self._config.text("scenario.subbasin"), text_color=self._colors.get("text_secondary")
        ).pack(anchor="w")
        self._subbasin_selector = ttk.Combobox(subbasin_col, style=style, state="readonly", values=[], width=10)
        self._subbasin_selector.pack(anchor="w", pady=(4, 0))
        self._subbasin_selector.bind("<<ComboboxSelected>>", lambda _e: self._on_subbasin_selected())

        hru_col = ctk.CTkFrame(selector_row, fg_color="transparent")
        hru_col.pack(side="left")
        ctk.CTkLabel(
            hru_col, text=self._config.text("nbs_tab.hru_list_label"), text_color=self._colors.get("text_secondary")
        ).pack(anchor="w")
        self._hru_listbox = tk.Listbox(hru_col, selectmode="extended", height=5, exportselection=False, width=14)
        self._hru_listbox.pack(anchor="w", pady=(4, 0))

        add_col = ctk.CTkFrame(selector_row, fg_color="transparent")
        add_col.pack(side="left", padx=(16, 0), anchor="s")
        ctk.CTkButton(
            add_col, text=self._config.text("nbs_tab.add_targets_button"), command=self._on_add_targets_clicked, width=140
        ).pack()

        targets_row = ctk.CTkFrame(card, fg_color="transparent")
        targets_row.grid(row=3, column=0, sticky="ew", padx=16, pady=(8, 4))
        targets_row.columnconfigure(0, weight=1)
        ctk.CTkLabel(
            targets_row, text=self._config.text("nbs_tab.targets_label"), text_color=self._colors.get("text_secondary")
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            targets_row, text=self._config.text("nbs_tab.clear_targets_button"),
            fg_color="transparent", border_width=1, border_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"), hover_color=self._colors.get("window_bg"),
            command=self._on_clear_targets_clicked, width=90,
        ).grid(row=0, column=1, sticky="e")

        self._targets_label = ctk.CTkLabel(
            card, text="", text_color=self._colors.get("text_secondary"), anchor="w", justify="left"
        )
        self._targets_label.grid(row=4, column=0, sticky="ew", padx=16)
        bind_responsive_wraplength(self._targets_label)

        controls = ctk.CTkFrame(card, fg_color="transparent")
        controls.grid(row=5, column=0, sticky="ew", padx=16, pady=(12, 8))
        controls.columnconfigure(0, weight=1)
        self._apply_status_label = ctk.CTkLabel(
            controls, text="", text_color=self._colors.get("text_secondary"), anchor="w", justify="left"
        )
        self._apply_status_label.grid(row=0, column=0, sticky="w")
        bind_responsive_wraplength(self._apply_status_label)
        self._apply_button = ctk.CTkButton(
            controls, text=self._config.text("nbs_tab.apply_button"), command=self._on_apply_clicked
        )
        self._apply_button.grid(row=0, column=1, sticky="e")

        log_frame = ctk.CTkFrame(card, fg_color=self._colors.get("surface"))
        log_frame.grid(row=6, column=0, sticky="nsew", padx=16, pady=(0, 16))
        card.rowconfigure(6, weight=1)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self._apply_log = ctk.CTkTextbox(log_frame, wrap="word", state="disabled", height=100)
        self._apply_log.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    def _build_area_apply_card(self, parent: ctk.CTkFrame, *, row: int) -> None:
        card = ctk.CTkFrame(parent)
        card.grid(row=row, column=0, sticky="ew", pady=(16, 0))
        card.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card, text=self._config.text("nbs_tab.area_apply_title"), text_color=self._colors.get("text_primary"),
            font=ctk.CTkFont(size=14, weight="bold"), anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))

        subtitle = ctk.CTkLabel(
            card, text=self._config.text("nbs_tab.area_apply_subtitle"), text_color=self._colors.get("text_secondary"),
            anchor="w", justify="left",
        )
        subtitle.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        bind_responsive_wraplength(subtitle)

        style = style_combobox(self._config)

        top_row = ctk.CTkFrame(card, fg_color="transparent")
        top_row.grid(row=2, column=0, sticky="ew", padx=16)

        nbs_col = ctk.CTkFrame(top_row, fg_color="transparent")
        nbs_col.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(
            nbs_col, text=self._config.text("nbs_tab.select_nbs_label"), text_color=self._colors.get("text_secondary")
        ).pack(anchor="w")
        self._area_nbs_selector = ttk.Combobox(nbs_col, style=style, state="readonly", values=[], width=30)
        self._area_nbs_selector.pack(anchor="w", pady=(4, 0))

        subbasin_col = ctk.CTkFrame(top_row, fg_color="transparent")
        subbasin_col.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(
            subbasin_col, text=self._config.text("scenario.subbasin"), text_color=self._colors.get("text_secondary")
        ).pack(anchor="w")
        self._area_subbasin_selector = ttk.Combobox(subbasin_col, style=style, state="readonly", values=[], width=10)
        self._area_subbasin_selector.pack(anchor="w", pady=(4, 0))
        self._area_subbasin_selector.bind("<<ComboboxSelected>>", lambda _e: self._on_area_subbasin_selected())

        total_col = ctk.CTkFrame(top_row, fg_color="transparent")
        total_col.pack(side="left")
        ctk.CTkLabel(
            total_col, text=self._config.text("nbs_tab.area_total_label"), text_color=self._colors.get("text_secondary")
        ).pack(anchor="w")
        self._area_total_entry = ctk.CTkEntry(total_col, width=100)
        self._area_total_entry.pack(anchor="w", pady=(4, 0))

        ctk.CTkLabel(
            card, text=self._config.text("nbs_tab.area_source_section_label"),
            text_color=self._colors.get("text_secondary"), anchor="w",
        ).grid(row=3, column=0, sticky="w", padx=16, pady=(12, 4))

        add_row = ctk.CTkFrame(card, fg_color="transparent")
        add_row.grid(row=4, column=0, sticky="ew", padx=16)

        coverage_col = ctk.CTkFrame(add_row, fg_color="transparent")
        coverage_col.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(
            coverage_col, text=self._config.text("nbs_tab.area_coverage_label"),
            text_color=self._colors.get("text_secondary"),
        ).pack(anchor="w")
        self._area_coverage_selector = ttk.Combobox(coverage_col, style=style, state="readonly", values=[], width=12)
        self._area_coverage_selector.pack(anchor="w", pady=(4, 0))

        percent_col = ctk.CTkFrame(add_row, fg_color="transparent")
        percent_col.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(
            percent_col, text=self._config.text("nbs_tab.area_percent_label"),
            text_color=self._colors.get("text_secondary"),
        ).pack(anchor="w")
        self._area_percent_entry = ctk.CTkEntry(percent_col, width=80)
        self._area_percent_entry.pack(anchor="w", pady=(4, 0))

        buttons_col = ctk.CTkFrame(add_row, fg_color="transparent")
        buttons_col.pack(side="left", anchor="s")
        ctk.CTkButton(
            buttons_col, text=self._config.text("nbs_tab.area_add_row_button"),
            command=self._on_add_source_row_clicked, width=90,
        ).pack(side="left")
        ctk.CTkButton(
            buttons_col, text=self._config.text("nbs_tab.area_remove_row_button"),
            fg_color="transparent", border_width=1, border_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"), hover_color=self._colors.get("window_bg"),
            command=self._on_remove_source_row_clicked, width=120,
        ).pack(side="left", padx=(8, 0))

        columns = ("coverage", "percent")
        self._area_rows_tree, rows_container = build_scrollable_treeview(
            card, self._config, columns=columns, height=4, style_prefix="NbSAreaRows"
        )
        self._area_rows_tree.heading("coverage", text=self._config.text("nbs_tab.area_col_coverage"))
        self._area_rows_tree.column("coverage", width=120, anchor="w", stretch=False)
        self._area_rows_tree.heading("percent", text=self._config.text("nbs_tab.area_col_percent"))
        self._area_rows_tree.column("percent", width=100, anchor="e", stretch=False)
        rows_container.grid(row=5, column=0, sticky="ew", padx=16, pady=(8, 4))

        self._area_total_pct_label = ctk.CTkLabel(
            card, text="", text_color=self._colors.get("text_secondary"), anchor="w"
        )
        self._area_total_pct_label.grid(row=6, column=0, sticky="w", padx=16)

        priority_help = ctk.CTkLabel(
            card, text=self._config.text("nbs_tab.area_priority_help"),
            text_color=self._colors.get("text_secondary"), anchor="w", justify="left",
        )
        priority_help.grid(row=7, column=0, sticky="ew", padx=16, pady=(12, 0))
        bind_responsive_wraplength(priority_help)

        priority_row = ctk.CTkFrame(card, fg_color="transparent")
        priority_row.grid(row=8, column=0, sticky="ew", padx=16, pady=(4, 4))
        priority_row.columnconfigure(1, weight=1)
        priority_row.columnconfigure(3, weight=1)
        ctk.CTkLabel(
            priority_row, text=self._config.text("nbs_tab.area_slope_priority_label"),
            text_color=self._colors.get("text_secondary"),
        ).grid(row=0, column=0, sticky="w")
        self._area_slope_entry = ctk.CTkEntry(priority_row)
        self._area_slope_entry.grid(row=0, column=1, sticky="ew", padx=(8, 16))
        ctk.CTkLabel(
            priority_row, text=self._config.text("nbs_tab.area_soil_priority_label"),
            text_color=self._colors.get("text_secondary"),
        ).grid(row=0, column=2, sticky="w")
        self._area_soil_entry = ctk.CTkEntry(priority_row)
        self._area_soil_entry.grid(row=0, column=3, sticky="ew", padx=(8, 0))

        controls = ctk.CTkFrame(card, fg_color="transparent")
        controls.grid(row=9, column=0, sticky="ew", padx=16, pady=(12, 8))
        controls.columnconfigure(0, weight=1)
        self._area_status_label = ctk.CTkLabel(
            controls, text="", text_color=self._colors.get("text_secondary"), anchor="w", justify="left"
        )
        self._area_status_label.grid(row=0, column=0, sticky="w")
        bind_responsive_wraplength(self._area_status_label)
        self._area_preview_button = ctk.CTkButton(
            controls, text=self._config.text("nbs_tab.area_preview_button"),
            fg_color="transparent", border_width=1, border_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"), hover_color=self._colors.get("window_bg"),
            command=self._on_area_preview_clicked, width=90,
        )
        self._area_preview_button.grid(row=0, column=1, sticky="e", padx=(0, 8))
        self._area_apply_button = ctk.CTkButton(
            controls, text=self._config.text("nbs_tab.area_apply_button"), command=self._on_area_apply_clicked,
            state="disabled",
        )
        self._area_apply_button.grid(row=0, column=2, sticky="e")

        log_frame = ctk.CTkFrame(card, fg_color=self._colors.get("surface"))
        log_frame.grid(row=10, column=0, sticky="nsew", padx=16, pady=(0, 16))
        card.rowconfigure(10, weight=1)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self._area_log = ctk.CTkTextbox(log_frame, wrap="word", state="disabled", height=100)
        self._area_log.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    def _build_mass_area_apply_card(self, parent: ctk.CTkFrame, *, row: int) -> None:
        card = ctk.CTkFrame(parent)
        card.grid(row=row, column=0, sticky="ew", pady=(16, 0))
        card.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card, text=self._config.text("nbs_tab.mass_apply_title"), text_color=self._colors.get("text_primary"),
            font=ctk.CTkFont(size=14, weight="bold"), anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))

        subtitle = ctk.CTkLabel(
            card, text=self._config.text("nbs_tab.mass_apply_subtitle"), text_color=self._colors.get("text_secondary"),
            anchor="w", justify="left",
        )
        subtitle.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        bind_responsive_wraplength(subtitle)

        style = style_combobox(self._config)

        nbs_row = ctk.CTkFrame(card, fg_color="transparent")
        nbs_row.grid(row=2, column=0, sticky="ew", padx=16)
        nbs_row.columnconfigure(1, weight=1)
        ctk.CTkLabel(
            nbs_row, text=self._config.text("nbs_tab.select_nbs_label"), text_color=self._colors.get("text_secondary")
        ).grid(row=0, column=0, sticky="w")
        self._mass_nbs_selector = ttk.Combobox(nbs_row, style=style, state="readonly", values=[], width=40)
        self._mass_nbs_selector.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        csv_row = ctk.CTkFrame(card, fg_color="transparent")
        csv_row.grid(row=3, column=0, sticky="ew", padx=16, pady=(12, 4))
        csv_row.columnconfigure(0, weight=1)
        self._mass_csv_field = ReadOnlyField(csv_row, self._config, "nbs_tab.mass_csv_label")
        self._mass_csv_field.grid(row=0, column=0, sticky="ew")
        self._mass_download_button = ctk.CTkButton(
            csv_row, text=self._config.text("nbs_tab.mass_download_template_button"),
            fg_color="transparent", border_width=1, border_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"), hover_color=self._colors.get("window_bg"),
            command=self._on_mass_download_template_clicked, width=140,
        )
        self._mass_download_button.grid(row=0, column=1, sticky="e", padx=(12, 0))
        self._mass_load_csv_button = ctk.CTkButton(
            csv_row, text=self._config.text("nbs_tab.mass_load_csv_button"),
            command=self._on_mass_load_csv_clicked, width=90,
        )
        self._mass_load_csv_button.grid(row=0, column=2, sticky="e", padx=(8, 0))

        priority_help = ctk.CTkLabel(
            card, text=self._config.text("nbs_tab.mass_priority_help"),
            text_color=self._colors.get("text_secondary"), anchor="w", justify="left",
        )
        priority_help.grid(row=4, column=0, sticky="ew", padx=16, pady=(12, 0))
        bind_responsive_wraplength(priority_help)

        priority_row = ctk.CTkFrame(card, fg_color="transparent")
        priority_row.grid(row=5, column=0, sticky="ew", padx=16, pady=(4, 4))
        priority_row.columnconfigure(1, weight=1)
        priority_row.columnconfigure(3, weight=1)
        ctk.CTkLabel(
            priority_row, text=self._config.text("nbs_tab.area_slope_priority_label"),
            text_color=self._colors.get("text_secondary"),
        ).grid(row=0, column=0, sticky="w")
        self._mass_slope_entry = ctk.CTkEntry(priority_row)
        self._mass_slope_entry.grid(row=0, column=1, sticky="ew", padx=(8, 16))
        ctk.CTkLabel(
            priority_row, text=self._config.text("nbs_tab.area_soil_priority_label"),
            text_color=self._colors.get("text_secondary"),
        ).grid(row=0, column=2, sticky="w")
        self._mass_soil_entry = ctk.CTkEntry(priority_row)
        self._mass_soil_entry.grid(row=0, column=3, sticky="ew", padx=(8, 0))

        controls = ctk.CTkFrame(card, fg_color="transparent")
        controls.grid(row=6, column=0, sticky="ew", padx=16, pady=(12, 8))
        controls.columnconfigure(0, weight=1)
        self._mass_status_label = ctk.CTkLabel(
            controls, text="", text_color=self._colors.get("text_secondary"), anchor="w", justify="left"
        )
        self._mass_status_label.grid(row=0, column=0, sticky="w")
        bind_responsive_wraplength(self._mass_status_label)
        self._mass_preview_button = ctk.CTkButton(
            controls, text=self._config.text("nbs_tab.area_preview_button"),
            fg_color="transparent", border_width=1, border_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"), hover_color=self._colors.get("window_bg"),
            command=self._on_mass_preview_clicked, width=90, state="disabled",
        )
        self._mass_preview_button.grid(row=0, column=1, sticky="e", padx=(0, 8))
        self._mass_apply_button = ctk.CTkButton(
            controls, text=self._config.text("nbs_tab.mass_apply_button"), command=self._on_mass_apply_clicked,
            state="disabled",
        )
        self._mass_apply_button.grid(row=0, column=2, sticky="e")

        log_frame = ctk.CTkFrame(card, fg_color=self._colors.get("surface"))
        log_frame.grid(row=7, column=0, sticky="nsew", padx=16, pady=(0, 16))
        card.rowconfigure(7, weight=1)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self._mass_log = ctk.CTkTextbox(log_frame, wrap="word", state="disabled", height=140)
        self._mass_log.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    # -- estado del proyecto ----------------------------------------------------

    def set_project(self, project_dir: Path) -> None:
        self._project_dir = project_dir
        self._targets = []
        self._area_source_rows = []
        self._mass_allocations = {}
        self._enabled_state.pack(fill="both", expand=True)
        self._disabled_state.pack_forget()

        txtinout_dir = project_dir / "TxtInOut"
        self._subbasins = sorted(s.subbasin_id for s in discover_subbasins(txtinout_dir))
        self._subbasin_selector.configure(values=[str(s) for s in self._subbasins])
        self._area_subbasin_selector.configure(values=[str(s) for s in self._subbasins])
        if self._subbasins:
            self._subbasin_selector.current(0)
            self._on_subbasin_selected()
            self._area_subbasin_selector.current(0)
            self._on_area_subbasin_selected()
        else:
            self._hru_listbox.delete(0, "end")
            self._area_coverage_selector.configure(values=[])
            self._area_coverage_selector.set("")

        self._apply_status_label.configure(text="", text_color=self._colors.get("text_secondary"))
        self._set_apply_log("")
        self._refresh_targets_label()

        self._area_total_entry.delete(0, "end")
        self._area_slope_entry.delete(0, "end")
        self._area_soil_entry.delete(0, "end")
        self._area_status_label.configure(text="", text_color=self._colors.get("text_secondary"))
        self._set_area_log("")
        self._refresh_area_rows_tree()

        self._mass_csv_field.set_value(self._config.text("nbs_tab.mass_csv_not_loaded"))
        self._mass_slope_entry.delete(0, "end")
        self._mass_soil_entry.delete(0, "end")
        self._mass_status_label.configure(text="", text_color=self._colors.get("text_secondary"))
        self._set_mass_log("")
        self._update_mass_apply_button_state()

        self._refresh_library()

    # -- biblioteca de NbS --------------------------------------------------------

    def _refresh_library(self) -> None:
        if self._project_dir is None:
            return
        self._library = load_library(self._project_dir)

        for item in self._library_tree.get_children():
            self._library_tree.delete(item)
        for definition in self._library:
            mode = self._config.text("nbs_tab.mode_new") if definition.new_coverage is not None else self._config.text(
                "nbs_tab.mode_existing"
            )
            self._library_tree.insert(
                "", "end", iid=definition.name,
                values=(
                    definition.name,
                    f"{definition.target_lulc} — {name_for(definition.target_lulc)}",
                    mode,
                    len(definition.operations),
                    definition.description,
                ),
            )

        self._nbs_selector.configure(values=[d.name for d in self._library])
        self._area_nbs_selector.configure(values=[d.name for d in self._library])
        self._mass_nbs_selector.configure(values=[d.name for d in self._library])
        if self._library:
            self._nbs_selector.current(0)
            self._area_nbs_selector.current(0)
            self._mass_nbs_selector.current(0)
        else:
            self._nbs_selector.set("")
            self._area_nbs_selector.set("")
            self._mass_nbs_selector.set("")
        self._delete_button.configure(state="disabled")
        self._edit_button.configure(state="disabled")

    def _on_new_nbs_clicked(self) -> None:
        if self._project_dir is None:
            return
        NbSWizardWindow(self, self._config, self._project_dir, on_created=self._refresh_library)

    def _on_open_library_folder_clicked(self) -> None:
        if self._project_dir is None:
            return
        os.startfile(tool_outputs_dir(self._project_dir))  # solo Windows: target de distribución del proyecto

    def _on_library_selection_changed(self) -> None:
        has_selection = bool(self._library_tree.selection())
        self._delete_button.configure(state="normal" if has_selection else "disabled")
        self._edit_button.configure(state="normal" if has_selection else "disabled")

    def _on_edit_clicked(self) -> None:
        selection = self._library_tree.selection()
        if not selection or self._project_dir is None:
            return
        definition = next((d for d in self._library if d.name == selection[0]), None)
        if definition is None:
            return
        NbSWizardWindow(self, self._config, self._project_dir, on_created=self._refresh_library, existing=definition)

    def _on_delete_clicked(self) -> None:
        selection = self._library_tree.selection()
        if not selection or self._project_dir is None:
            return
        name = selection[0]
        ConfirmDialog(
            self, self._config,
            message=self._config.text("nbs_tab.confirm_delete").format(name=name),
            on_confirm=lambda: self._delete_nbs(name),
        )

    def _delete_nbs(self, name: str) -> None:
        if self._project_dir is None:
            return
        delete_definition(self._project_dir, name)
        self._refresh_library()

    # -- selección de HRU objetivo ------------------------------------------------

    def _on_subbasin_selected(self) -> None:
        if self._project_dir is None or not self._subbasin_selector.get():
            return
        subbasin_id = int(self._subbasin_selector.get())
        txtinout_dir = self._project_dir / "TxtInOut"
        hru_ids = sorted(list_subbasin_hru_ids(txtinout_dir, subbasin_id))
        self._hru_listbox.delete(0, "end")
        for hru_id in hru_ids:
            self._hru_listbox.insert("end", str(hru_id))

    def _on_add_targets_clicked(self) -> None:
        if not self._subbasin_selector.get():
            return
        subbasin_id = int(self._subbasin_selector.get())
        selected = self._hru_listbox.curselection()
        for index in selected:
            hru_id = int(self._hru_listbox.get(index))
            pair = (subbasin_id, hru_id)
            if pair not in self._targets:
                self._targets.append(pair)
        self._refresh_targets_label()

    def _on_clear_targets_clicked(self) -> None:
        self._targets = []
        self._refresh_targets_label()

    def _refresh_targets_label(self) -> None:
        if not self._targets:
            self._targets_label.configure(text=self._config.text("nbs_tab.no_targets"))
            return
        text = ", ".join(f"{sub}/{hru}" for sub, hru in self._targets)
        self._targets_label.configure(text=self._config.text("nbs_tab.targets_count").format(count=len(self._targets)) + " " + text)

    # -- aplicar NbS (hilo de fondo) ------------------------------------------------

    def _on_apply_clicked(self) -> None:
        if self._project_dir is None or not self._targets:
            self._apply_status_label.configure(
                text=self._config.text("nbs_tab.no_targets_error"), text_color=self._colors.get("error")
            )
            return
        name = self._nbs_selector.get()
        # Releído de disco acá (no self._library, poblado solo por
        # _refresh_library en set_project/crear/editar/borrar) -- pedido
        # explícito del usuario, 2026-08-11: si edita nbs_library.json a
        # mano mientras la app está abierta, Apply debe usar esa NbS tal
        # como quedó en el archivo, no una copia en memoria desactualizada.
        definition = next((d for d in load_library(self._project_dir) if d.name == name), None)
        if definition is None:
            self._apply_status_label.configure(
                text=self._config.text("nbs_tab.no_nbs_selected_error"), text_color=self._colors.get("error")
            )
            return

        message = self._config.text("nbs_tab.confirm_apply").format(name=definition.name, count=len(self._targets))
        ConfirmDialog(self, self._config, message=message, on_confirm=lambda: self._start_apply(definition))

    def _start_apply(self, definition: NbSDefinition) -> None:
        project_dir = self._project_dir
        targets = list(self._targets)

        self._apply_button.configure(state="disabled")
        self._area_preview_button.configure(state="disabled")
        self._area_apply_button.configure(state="disabled")
        self._mass_preview_button.configure(state="disabled")
        self._mass_apply_button.configure(state="disabled")
        self._apply_status_label.configure(
            text=self._config.text("nbs_tab.applying"), text_color=self._colors.get("text_secondary")
        )
        self._set_apply_log("")
        self._on_run_state_changed(True)

        def work(_report_progress):
            return apply_nbs(project_dir, definition, targets)

        run_in_background(self, work, on_progress=lambda _m: None, on_done=self._on_apply_done, on_error=self._on_apply_error)

    def _write_apply_report(self, report: NbSApplyReport) -> str:
        """Escribe el CSV de auditoría de esta aplicación (subbasin/hru/
        status/hru_fr/message) y devuelve su ruta como texto para el log --
        compartido por Apply manual y Apply by area, ambos usan el mismo
        NbSApplyReport."""
        csv_path = write_apply_report_csv(self._project_dir, report, datetime.now())
        return str(csv_path)

    def _on_apply_done(self, report: NbSApplyReport) -> None:
        self._apply_status_label.configure(
            text=self._config.text("nbs_tab.apply_summary").format(
                applied=report.applied_count, total=len(report.results), plant_id=report.plant_id, cpnm=report.cpnm
            ),
            text_color=self._colors.get("success") if report.error_count == 0 else self._colors.get("warning"),
        )
        lines = [self._config.text("nbs_tab.apply_report_saved").format(path=self._write_apply_report(report))]
        for result in report.results:
            if result.status == "applied":
                lines.append(self._config.text("nbs_tab.log_line_ok").format(subbasin=result.subbasin, hru=result.hru))
            else:
                lines.append(
                    self._config.text("nbs_tab.log_line_error").format(
                        subbasin=result.subbasin, hru=result.hru, error=result.message
                    )
                )
        self._set_apply_log("\n".join(lines))
        self._finish_apply()

    def _on_apply_error(self, error: Exception) -> None:
        self._apply_status_label.configure(
            text=self._config.text("nbs_tab.apply_error").format(error=str(error)), text_color=self._colors.get("error")
        )
        self._finish_apply()

    def _finish_apply(self) -> None:
        self._apply_button.configure(state="normal")
        self._area_preview_button.configure(state="normal")
        self._update_area_apply_button_state()
        self._mass_preview_button.configure(state="normal")
        self._update_mass_apply_button_state()
        self._on_run_state_changed(False)

    def _set_apply_log(self, text: str) -> None:
        self._apply_log.configure(state="normal")
        self._apply_log.delete("1.0", "end")
        self._apply_log.insert("1.0", text)
        self._apply_log.configure(state="disabled")

    # -- aplicar NbS por área (hilo de fondo) ---------------------------------------

    def _on_area_subbasin_selected(self) -> None:
        self._area_source_rows = []
        self._refresh_area_rows_tree()
        self._refresh_area_coverage_options()

    def _refresh_area_coverage_options(self) -> None:
        self._area_coverage_request_id += 1
        request_id = self._area_coverage_request_id

        if self._project_dir is None or not self._area_subbasin_selector.get():
            self._area_coverage_selector.configure(values=[])
            self._area_coverage_selector.set("")
            return

        project_dir = self._project_dir
        subbasin_id = int(self._area_subbasin_selector.get())

        # load_subbasin_hru_files parsea el contenido de cada .hru de la
        # subcuenca (no solo el nombre de archivo) -- con un modelo real
        # una subcuenca puede tener cientos/miles de HRU, así que esto
        # corre en hilo de fondo (patrón obligatorio de CLAUDE.md) en vez
        # de bloquear la ventana como antes. request_id descarta el
        # resultado si el usuario ya cambió de subcuenca/proyecto mientras
        # corría.
        self._area_coverage_selector.configure(values=[])
        self._area_coverage_selector.set("")
        self._area_status_label.configure(
            text=self._config.text("nbs_tab.area_loading_coverages"), text_color=self._colors.get("text_secondary")
        )

        def work(_report_progress):
            txtinout_dir = project_dir / "TxtInOut"
            hru_files = load_subbasin_hru_files(txtinout_dir, subbasin_id)
            return subbasin_land_uses(hru_files)

        def on_done(options: list[str]) -> None:
            if request_id != self._area_coverage_request_id:
                return
            self._area_coverage_selector.configure(values=options)
            if options:
                self._area_coverage_selector.current(0)
            else:
                self._area_coverage_selector.set("")
            self._area_status_label.configure(text="", text_color=self._colors.get("text_secondary"))

        def on_error(error: Exception) -> None:
            if request_id != self._area_coverage_request_id:
                return
            self._area_status_label.configure(
                text=self._config.text("nbs_tab.apply_error").format(error=str(error)),
                text_color=self._colors.get("error"),
            )

        run_in_background(self, work, on_progress=lambda _m: None, on_done=on_done, on_error=on_error)

    def _on_add_source_row_clicked(self) -> None:
        coverage = self._area_coverage_selector.get()
        if not coverage:
            self._area_status_label.configure(
                text=self._config.text("nbs_tab.area_no_coverage_selected_error"), text_color=self._colors.get("error")
            )
            return
        try:
            pct = float(self._area_percent_entry.get())
            if pct <= 0:
                raise ValueError
        except ValueError:
            self._area_status_label.configure(
                text=self._config.text("nbs_tab.area_invalid_percent_error"), text_color=self._colors.get("error")
            )
            return
        if any(name == coverage for name, _ in self._area_source_rows):
            self._area_status_label.configure(
                text=self._config.text("nbs_tab.area_duplicate_coverage_error").format(coverage=coverage),
                text_color=self._colors.get("error"),
            )
            return

        current_total = sum(p for _, p in self._area_source_rows)
        prospective_total = current_total + pct
        if prospective_total - 100 > _AREA_PCT_SUM_TOLERANCE:
            self._area_status_label.configure(
                text=self._config.text("nbs_tab.area_percent_exceeds_total_error").format(
                    pct=pct, total=prospective_total
                ),
                text_color=self._colors.get("error"),
            )
            return

        self._area_source_rows.append((coverage, pct))
        self._area_percent_entry.delete(0, "end")
        self._area_status_label.configure(text="", text_color=self._colors.get("text_secondary"))
        self._refresh_area_rows_tree()

    def _on_remove_source_row_clicked(self) -> None:
        selection = self._area_rows_tree.selection()
        if not selection:
            return
        index = int(selection[0])
        del self._area_source_rows[index]
        self._refresh_area_rows_tree()

    def _refresh_area_rows_tree(self) -> None:
        for item in self._area_rows_tree.get_children():
            self._area_rows_tree.delete(item)
        for index, (coverage, pct) in enumerate(self._area_source_rows):
            self._area_rows_tree.insert("", "end", iid=str(index), values=(coverage, f"{pct:.1f}"))

        total = sum(pct for _, pct in self._area_source_rows)
        label = self._config.text("nbs_tab.area_total_percent_label").format(pct=total)
        complete = abs(total - 100) <= _AREA_PCT_SUM_TOLERANCE
        color = self._colors.get("success") if complete else self._colors.get("text_secondary")
        self._area_total_pct_label.configure(text=label, text_color=color)
        self._update_area_apply_button_state()

    def _update_area_apply_button_state(self) -> None:
        """Habilita 'Apply by area' solo cuando el % acumulado de coberturas
        fuente llega a 100 (misma tolerancia que valida el backend) --
        pedido explícito del usuario, 2026-08-12: antes solo se avisaba con
        el color de la etiqueta y el click fallaba recién al intentar
        calcular el plan."""
        total = sum(pct for _, pct in self._area_source_rows)
        complete = abs(total - 100) <= _AREA_PCT_SUM_TOLERANCE
        self._area_apply_button.configure(state="normal" if complete else "disabled")

    def _run_area_plan(self, on_ready: Callable[[NbSDefinition, AreaAllocationPlan], None]) -> None:
        """Valida los inputs (barato) en el hilo principal y calcula el plan
        (load_subbasin_hru_files + plan_area_allocation) en hilo de fondo --
        mismo motivo que _refresh_area_coverage_options: load_subbasin_hru_files
        parsea el contenido de cada .hru de la subcuenca, y con un modelo real
        eso puede tardar lo suficiente como para congelar la ventana si corre
        en el hilo de UI al hacer clic en Preview/Apply by area."""
        if self._project_dir is None:
            return

        name = self._area_nbs_selector.get()
        # Mismo criterio que el Apply manual: releído de disco, no self._library.
        definition = next((d for d in load_library(self._project_dir) if d.name == name), None)
        if definition is None:
            self._area_status_label.configure(
                text=self._config.text("nbs_tab.no_nbs_selected_error"), text_color=self._colors.get("error")
            )
            return

        if not self._area_subbasin_selector.get():
            return
        subbasin_id = int(self._area_subbasin_selector.get())

        errors = validate_source_allocations(self._area_source_rows)
        if errors:
            self._area_status_label.configure(text=" ".join(errors), text_color=self._colors.get("error"))
            return

        try:
            total_area_ha = float(self._area_total_entry.get())
            if total_area_ha <= 0:
                raise ValueError
        except ValueError:
            self._area_status_label.configure(
                text=self._config.text("nbs_tab.area_invalid_total_area_error"), text_color=self._colors.get("error")
            )
            return

        project_dir = self._project_dir
        source_allocations = list(self._area_source_rows)
        slope_priority = parse_priority_text(self._area_slope_entry.get())
        soil_priority = parse_priority_text(self._area_soil_entry.get())

        self._area_preview_button.configure(state="disabled")
        self._area_apply_button.configure(state="disabled")
        self._area_status_label.configure(
            text=self._config.text("nbs_tab.area_loading_coverages"), text_color=self._colors.get("text_secondary")
        )

        def work(_report_progress):
            txtinout_dir = project_dir / "TxtInOut"
            hru_files = load_subbasin_hru_files(txtinout_dir, subbasin_id)
            sub_entry = next((s for s in discover_subbasins(txtinout_dir) if s.subbasin_id == subbasin_id), None)
            if sub_entry is None:
                return None
            subbasin_area_ha = parse_sub_file(sub_entry.sub_file, subbasin_id).area_km2 * 100
            return plan_area_allocation(
                subbasin_id, hru_files, subbasin_area_ha,
                total_area_ha=total_area_ha, source_allocations=source_allocations,
                slope_priority=slope_priority, soil_priority=soil_priority,
            )

        def on_done(plan: AreaAllocationPlan | None) -> None:
            self._area_preview_button.configure(state="normal")
            self._update_area_apply_button_state()
            if plan is None:
                return
            self._area_status_label.configure(text="", text_color=self._colors.get("text_secondary"))
            on_ready(definition, plan)

        def on_error(error: Exception) -> None:
            self._area_preview_button.configure(state="normal")
            self._update_area_apply_button_state()
            self._area_status_label.configure(
                text=self._config.text("nbs_tab.apply_error").format(error=str(error)),
                text_color=self._colors.get("error"),
            )

        run_in_background(self, work, on_progress=lambda _m: None, on_done=on_done, on_error=on_error)

    def _render_area_plan_preview(self, plan: AreaAllocationPlan) -> None:
        lines = [
            self._config.text("nbs_tab.area_preview_header").format(
                subbasin=plan.subbasin, area=plan.total_area_ha, sub_area=plan.subbasin_area_ha
            )
        ]
        for result in plan.by_source:
            lines.append(
                self._config.text("nbs_tab.area_preview_line").format(
                    coverage=result.source_lulc, requested=result.requested_ha, selected=result.selected_ha,
                    count=len(result.selected_hru_ids), hru_ids=result.selected_hru_ids,
                )
            )
            if result.status == "no_source_hru":
                lines.append(self._config.text("nbs_tab.area_preview_no_source_line"))
            elif result.deficit_ha > 0:
                lines.append(self._config.text("nbs_tab.area_preview_deficit_line").format(deficit=result.deficit_ha))
        self._set_area_log("\n".join(lines))

    def _on_area_preview_clicked(self) -> None:
        self._run_area_plan(self._render_area_plan_preview_ready)

    def _render_area_plan_preview_ready(self, _definition: NbSDefinition, plan: AreaAllocationPlan) -> None:
        self._render_area_plan_preview(plan)

    def _on_area_apply_clicked(self) -> None:
        self._run_area_plan(self._confirm_area_apply)

    def _confirm_area_apply(self, definition: NbSDefinition, plan: AreaAllocationPlan) -> None:
        targets = plan.targets
        if not targets:
            self._area_status_label.configure(
                text=self._config.text("nbs_tab.area_no_targets_error"), text_color=self._colors.get("error")
            )
            return

        self._render_area_plan_preview(plan)
        message = self._config.text("nbs_tab.area_confirm_apply").format(
            name=definition.name, count=len(targets),
            area=plan.total_area_ha - plan.total_deficit_ha, subbasin=plan.subbasin,
        )
        ConfirmDialog(self, self._config, message=message, on_confirm=lambda: self._start_area_apply(definition, targets))

    def _start_area_apply(self, definition: NbSDefinition, targets: list[tuple[int, int]]) -> None:
        project_dir = self._project_dir

        self._apply_button.configure(state="disabled")
        self._area_preview_button.configure(state="disabled")
        self._area_apply_button.configure(state="disabled")
        self._mass_preview_button.configure(state="disabled")
        self._mass_apply_button.configure(state="disabled")
        self._area_status_label.configure(
            text=self._config.text("nbs_tab.area_applying"), text_color=self._colors.get("text_secondary")
        )
        self._on_run_state_changed(True)

        def work(_report_progress):
            return apply_nbs(project_dir, definition, targets)

        run_in_background(
            self, work, on_progress=lambda _m: None, on_done=self._on_area_apply_done, on_error=self._on_area_apply_error
        )

    def _on_area_apply_done(self, report: NbSApplyReport) -> None:
        self._area_status_label.configure(
            text=self._config.text("nbs_tab.area_apply_summary").format(
                applied=report.applied_count, total=len(report.results), plant_id=report.plant_id, cpnm=report.cpnm
            ),
            text_color=self._colors.get("success") if report.error_count == 0 else self._colors.get("warning"),
        )
        lines = [self._config.text("nbs_tab.apply_report_saved").format(path=self._write_apply_report(report))]
        for result in report.results:
            if result.status == "applied":
                lines.append(self._config.text("nbs_tab.log_line_ok").format(subbasin=result.subbasin, hru=result.hru))
            else:
                lines.append(
                    self._config.text("nbs_tab.log_line_error").format(
                        subbasin=result.subbasin, hru=result.hru, error=result.message
                    )
                )
        self._set_area_log("\n".join(lines))
        self._finish_area_apply()

    def _on_area_apply_error(self, error: Exception) -> None:
        self._area_status_label.configure(
            text=self._config.text("nbs_tab.apply_error").format(error=str(error)), text_color=self._colors.get("error")
        )
        self._finish_area_apply()

    def _finish_area_apply(self) -> None:
        self._apply_button.configure(state="normal")
        self._area_preview_button.configure(state="normal")
        self._update_area_apply_button_state()
        self._mass_preview_button.configure(state="normal")
        self._update_mass_apply_button_state()
        self._on_run_state_changed(False)

    def _set_area_log(self, text: str) -> None:
        self._area_log.configure(state="normal")
        self._area_log.delete("1.0", "end")
        self._area_log.insert("1.0", text)
        self._area_log.configure(state="disabled")

    # -- aplicar NbS por área masiva (todas las subcuencas, hilo de fondo) ----------

    def _on_mass_download_template_clicked(self) -> None:
        if self._project_dir is None:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile="nbs_mass_apply_template.csv",
        )
        if not path:
            return

        project_dir = self._project_dir
        destination = Path(path)

        self._set_mass_controls_enabled(False)
        self._mass_status_label.configure(
            text=self._config.text("nbs_tab.mass_generating_template"), text_color=self._colors.get("text_secondary")
        )
        self._on_run_state_changed(True)

        def work(_report_progress):
            return write_mass_allocation_template_csv(project_dir / "TxtInOut", destination)

        def on_done(result_path: Path) -> None:
            self._mass_status_label.configure(
                text=self._config.text("nbs_tab.mass_template_success").format(path=str(result_path)),
                text_color=self._colors.get("success"),
            )
            self._finish_mass_operation()

        def on_error(error: Exception) -> None:
            self._mass_status_label.configure(
                text=self._config.text("nbs_tab.apply_error").format(error=str(error)),
                text_color=self._colors.get("error"),
            )
            self._finish_mass_operation()

        run_in_background(self, work, on_progress=lambda _m: None, on_done=on_done, on_error=on_error)

    def _finish_mass_operation(self) -> None:
        self._set_mass_controls_enabled(True)
        self._on_run_state_changed(False)

    def _set_mass_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self._mass_download_button.configure(state=state)
        self._mass_load_csv_button.configure(state=state)
        if enabled:
            self._update_mass_apply_button_state()
        else:
            self._mass_preview_button.configure(state="disabled")
            self._mass_apply_button.configure(state="disabled")

    def _on_mass_load_csv_clicked(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
        if not path:
            return

        try:
            allocations, errors = parse_mass_allocation_csv(Path(path))
        except ValueError as error:
            self._mass_status_label.configure(
                text=self._config.text("nbs_tab.apply_error").format(error=str(error)),
                text_color=self._colors.get("error"),
            )
            return

        self._mass_allocations = allocations
        self._mass_csv_field.set_value(path)
        self._mass_status_label.configure(
            text=self._config.text("nbs_tab.mass_load_csv_success").format(count=len(allocations)),
            text_color=self._colors.get("success") if not errors else self._colors.get("warning"),
        )
        self._set_mass_log(
            "\n".join(self._config.text("nbs_tab.mass_load_csv_error_line").format(error=e) for e in errors)
        )
        self._update_mass_apply_button_state()

    def _update_mass_apply_button_state(self) -> None:
        has_allocations = bool(self._mass_allocations)
        self._mass_preview_button.configure(state="normal" if has_allocations else "disabled")
        self._mass_apply_button.configure(state="normal" if has_allocations else "disabled")

    def _run_mass_plan(self, on_ready: Callable[[NbSDefinition, MassAreaAllocationResult], None]) -> None:
        """Mismo motivo que _run_area_plan para correr en hilo de fondo:
        plan_mass_area_allocation llama load_subbasin_hru_files por cada
        subcuenca del CSV, y con un modelo real eso puede tardar lo
        suficiente como para congelar la ventana si corriera en el hilo de
        UI."""
        if self._project_dir is None or not self._mass_allocations:
            return

        name = self._mass_nbs_selector.get()
        # Mismo criterio que Apply manual/por área: releído de disco, no self._library.
        definition = next((d for d in load_library(self._project_dir) if d.name == name), None)
        if definition is None:
            self._mass_status_label.configure(
                text=self._config.text("nbs_tab.no_nbs_selected_error"), text_color=self._colors.get("error")
            )
            return

        project_dir = self._project_dir
        allocations = dict(self._mass_allocations)
        slope_priority = parse_priority_text(self._mass_slope_entry.get())
        soil_priority = parse_priority_text(self._mass_soil_entry.get())

        self._mass_preview_button.configure(state="disabled")
        self._mass_apply_button.configure(state="disabled")
        self._mass_status_label.configure(
            text=self._config.text("nbs_tab.mass_computing_plan"), text_color=self._colors.get("text_secondary")
        )

        def work(_report_progress):
            return plan_mass_area_allocation(
                project_dir, allocations, slope_priority=slope_priority, soil_priority=soil_priority
            )

        def on_done(result: MassAreaAllocationResult) -> None:
            self._update_mass_apply_button_state()
            self._mass_status_label.configure(text="", text_color=self._colors.get("text_secondary"))
            on_ready(definition, result)

        def on_error(error: Exception) -> None:
            self._update_mass_apply_button_state()
            self._mass_status_label.configure(
                text=self._config.text("nbs_tab.apply_error").format(error=str(error)),
                text_color=self._colors.get("error"),
            )

        run_in_background(self, work, on_progress=lambda _m: None, on_done=on_done, on_error=on_error)

    def _render_mass_plan_preview(self, result: MassAreaAllocationResult) -> None:
        lines: list[str] = []
        for plan in result.plans:
            lines.append(
                self._config.text("nbs_tab.area_preview_header").format(
                    subbasin=plan.subbasin, area=plan.total_area_ha, sub_area=plan.subbasin_area_ha
                )
            )
            for source_result in plan.by_source:
                lines.append(
                    self._config.text("nbs_tab.area_preview_line").format(
                        coverage=source_result.source_lulc, requested=source_result.requested_ha,
                        selected=source_result.selected_ha, count=len(source_result.selected_hru_ids),
                        hru_ids=source_result.selected_hru_ids,
                    )
                )
                if source_result.status == "no_source_hru":
                    lines.append(self._config.text("nbs_tab.area_preview_no_source_line"))
                elif source_result.deficit_ha > 0:
                    lines.append(
                        self._config.text("nbs_tab.area_preview_deficit_line").format(deficit=source_result.deficit_ha)
                    )
        for subbasin_id, reason in result.skipped.items():
            lines.append(self._config.text("nbs_tab.mass_skipped_line").format(subbasin=subbasin_id, reason=reason))
        self._set_mass_log("\n".join(lines) if lines else self._config.text("nbs_tab.mass_no_targets_error"))

    def _on_mass_preview_clicked(self) -> None:
        self._run_mass_plan(self._render_mass_plan_preview_ready)

    def _render_mass_plan_preview_ready(self, _definition: NbSDefinition, result: MassAreaAllocationResult) -> None:
        self._render_mass_plan_preview(result)

    def _on_mass_apply_clicked(self) -> None:
        self._run_mass_plan(self._confirm_mass_apply)

    def _confirm_mass_apply(self, definition: NbSDefinition, result: MassAreaAllocationResult) -> None:
        targets = result.targets
        if not targets:
            self._mass_status_label.configure(
                text=self._config.text("nbs_tab.mass_no_targets_error"), text_color=self._colors.get("error")
            )
            return

        self._render_mass_plan_preview(result)
        message = self._config.text("nbs_tab.mass_confirm_apply").format(
            name=definition.name, count=len(targets), subbasins=len(result.plans)
        )
        ConfirmDialog(self, self._config, message=message, on_confirm=lambda: self._start_mass_apply(definition, targets))

    def _start_mass_apply(self, definition: NbSDefinition, targets: list[tuple[int, int]]) -> None:
        project_dir = self._project_dir

        self._apply_button.configure(state="disabled")
        self._area_preview_button.configure(state="disabled")
        self._area_apply_button.configure(state="disabled")
        self._mass_preview_button.configure(state="disabled")
        self._mass_apply_button.configure(state="disabled")
        self._mass_status_label.configure(
            text=self._config.text("nbs_tab.mass_applying"), text_color=self._colors.get("text_secondary")
        )
        self._on_run_state_changed(True)

        def work(_report_progress):
            return apply_nbs(project_dir, definition, targets)

        run_in_background(
            self, work, on_progress=lambda _m: None, on_done=self._on_mass_apply_done, on_error=self._on_mass_apply_error
        )

    def _on_mass_apply_done(self, report: NbSApplyReport) -> None:
        self._mass_status_label.configure(
            text=self._config.text("nbs_tab.area_apply_summary").format(
                applied=report.applied_count, total=len(report.results), plant_id=report.plant_id, cpnm=report.cpnm
            ),
            text_color=self._colors.get("success") if report.error_count == 0 else self._colors.get("warning"),
        )
        lines = [self._config.text("nbs_tab.apply_report_saved").format(path=self._write_apply_report(report))]
        for result in report.results:
            if result.status == "applied":
                lines.append(self._config.text("nbs_tab.log_line_ok").format(subbasin=result.subbasin, hru=result.hru))
            else:
                lines.append(
                    self._config.text("nbs_tab.log_line_error").format(
                        subbasin=result.subbasin, hru=result.hru, error=result.message
                    )
                )
        self._set_mass_log("\n".join(lines))
        self._finish_mass_apply()

    def _on_mass_apply_error(self, error: Exception) -> None:
        self._mass_status_label.configure(
            text=self._config.text("nbs_tab.apply_error").format(error=str(error)), text_color=self._colors.get("error")
        )
        self._finish_mass_apply()

    def _finish_mass_apply(self) -> None:
        self._apply_button.configure(state="normal")
        self._area_preview_button.configure(state="normal")
        self._update_area_apply_button_state()
        self._mass_preview_button.configure(state="normal")
        self._update_mass_apply_button_state()
        self._on_run_state_changed(False)

    def _set_mass_log(self, text: str) -> None:
        self._mass_log.configure(state="normal")
        self._mass_log.delete("1.0", "end")
        self._mass_log.insert("1.0", text)
        self._mass_log.configure(state="disabled")
