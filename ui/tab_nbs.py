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
from pathlib import Path
from tkinter import ttk
from typing import Callable

import customtkinter as ctk

from config.cpnm_names import name_for
from config.settings import ConfigManager
from scenarios.hru_draft import list_subbasin_hru_ids
from scenarios.nbs import NbSDefinition, delete_definition, load_library
from scenarios.nbs_apply import NbSApplyReport, apply_nbs
from swat_io.discovery import discover_subbasins
from swat_io.tool_outputs import tool_outputs_dir

from .dialog_confirm import ConfirmDialog
from .nbs_wizard_window import NbSWizardWindow
from .tasks import run_in_background
from .widgets import bind_responsive_wraplength, build_scrollable_treeview, palette, style_combobox


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
        frame = ctk.CTkFrame(self, fg_color="transparent")
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

    # -- estado del proyecto ----------------------------------------------------

    def set_project(self, project_dir: Path) -> None:
        self._project_dir = project_dir
        self._targets = []
        self._enabled_state.pack(fill="both", expand=True)
        self._disabled_state.pack_forget()

        txtinout_dir = project_dir / "TxtInOut"
        self._subbasins = sorted(s.subbasin_id for s in discover_subbasins(txtinout_dir))
        self._subbasin_selector.configure(values=[str(s) for s in self._subbasins])
        if self._subbasins:
            self._subbasin_selector.current(0)
            self._on_subbasin_selected()
        else:
            self._hru_listbox.delete(0, "end")

        self._apply_status_label.configure(text="", text_color=self._colors.get("text_secondary"))
        self._set_apply_log("")
        self._refresh_targets_label()
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
        if self._library:
            self._nbs_selector.current(0)
        else:
            self._nbs_selector.set("")
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
        self._apply_status_label.configure(
            text=self._config.text("nbs_tab.applying"), text_color=self._colors.get("text_secondary")
        )
        self._set_apply_log("")
        self._on_run_state_changed(True)

        def work(_report_progress):
            return apply_nbs(project_dir, definition, targets)

        run_in_background(self, work, on_progress=lambda _m: None, on_done=self._on_apply_done, on_error=self._on_apply_error)

    def _on_apply_done(self, report: NbSApplyReport) -> None:
        self._apply_status_label.configure(
            text=self._config.text("nbs_tab.apply_summary").format(
                applied=report.applied_count, total=len(report.results), plant_id=report.plant_id, cpnm=report.cpnm
            ),
            text_color=self._colors.get("success") if report.error_count == 0 else self._colors.get("warning"),
        )
        lines = []
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
        self._on_run_state_changed(False)

    def _set_apply_log(self, text: str) -> None:
        self._apply_log.configure(state="normal")
        self._apply_log.delete("1.0", "end")
        self._apply_log.insert("1.0", text)
        self._apply_log.configure(state="disabled")
