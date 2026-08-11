"""Wizard de creación de una NbS (Solución basada en la Naturaleza):
nombre -> cobertura (existente o nueva) -> fisiología (si es nueva) ->
copiar de una configuración existente -> parámetros .hru -> condición
inicial .mgt + CN2 por HSG -> calendario de manejo -> revisión y guardado.

Ventana modal con pasos Next/Back (decisión explícita del usuario, dado el
número de decisiones condicionales del flujo) -- ver CLAUDE.md. Guardar
siempre agrega/reemplaza una entrada en la biblioteca JSON de NbS del
proyecto (scenarios.nbs); si la cobertura es nueva, además sincroniza de
inmediato el registro correspondiente en el plant.dat real del proyecto
(``scenarios.nbs_apply.sync_new_coverage_to_plant_dat`` -- pedido
explícito del usuario, 2026-08-11: antes plant.dat solo se tocaba al
aplicar la NbS a HRU reales, ver ui/tab_nbs.py/scenarios.nbs_apply). El
resto de lo que la NbS define (.hru/.mgt/calendario) sigue sin tocar
TxtInOut hasta que se aplique.
"""
from __future__ import annotations

from pathlib import Path
from tkinter import ttk
from typing import Callable

import customtkinter as ctk

from config.cpnm_names import name_for
from config.nbs_parameter_labels import IDC_CLASSES, label_for
from config.settings import ConfigManager
from scenarios.nbs import (
    HYDROLOGIC_SOIL_GROUPS,
    NbSDefinition,
    NbSNewCoverage,
    NbSOperation,
    add_or_replace,
    load_library,
)
from scenarios.nbs_analysis import scan_existing_parameter_combinations
from scenarios.nbs_apply import NbSApplyError, sync_new_coverage_to_plant_dat, validate_nbs_definition
from swat_io.mgt.operation_specs import MGT_OPERATION_NAMES
from swat_io.plant.models import LINE2_FIELDS, LINE3_FIELDS, LINE4_FIELDS, LINE5_FIELDS
from swat_io.plant.parser import parse_plant_dat_file

from .dialog_confirm import ConfirmDialog
from .nbs_operation_dialog import NbSOperationDialog
from .tasks import run_in_background
from .widgets import build_scrollable_treeview, palette, style_combobox

_WINDOW_SIZE = "680x720"

_HRU_PARAM_REQUIRED = ("CANMX", "OV_N")
_HRU_PARAM_ALL = ("CANMX", "OV_N", "RSDIN")

_PHYSIOLOGY_GROUPS: list[tuple[str, list[str]]] = [
    ("Line 2 — Biomass / canopy / roots", LINE2_FIELDS),
    ("Line 3 — Temperature / nutrients", LINE3_FIELDS),
    ("Line 4 — Stress / erosion / CO2 / residue / dormancy", LINE4_FIELDS),
    ("Line 5 — Tree canopy / roots", LINE5_FIELDS),
]

_STEP_TITLE_KEYS = {
    "name": "nbs_wizard.step_name_title",
    "coverage": "nbs_wizard.step_coverage_title",
    "physiology": "nbs_wizard.step_physiology_title",
    "copy_from_existing": "nbs_wizard.step_copy_title",
    "hru_params": "nbs_wizard.step_hru_title",
    "mgt_initial": "nbs_wizard.step_mgt_title",
    "operations": "nbs_wizard.step_operations_title",
    "review": "nbs_wizard.step_review_title",
}


class NbSWizardWindow(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        config: ConfigManager,
        project_dir: Path,
        *,
        on_created: Callable[[], None] = lambda: None,
        existing: NbSDefinition | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self._config = config
        self._colors = palette(config)
        self._project_dir = project_dir
        self._txtinout_dir = project_dir / "TxtInOut"
        self._on_created = on_created
        # Nombre original si se está editando una NbS ya guardada -- excluido
        # del chequeo de "nombre ya usado" en _collect_step_name para poder
        # guardar sin cambiar el nombre (ver ese método más abajo).
        self._editing_original_name = existing.name if existing is not None else None
        # ICNUM ya sincronizado en plant.dat para la cobertura nueva de esta
        # NbS (None si nunca se creó, o si se está creando desde cero) --
        # se reusa para (a) no autorrechazar el propio CPNM como "ya
        # tomado" en _collect_step_coverage al reeditar sin cambiarlo, y
        # (b) pasarlo a sync_new_coverage_to_plant_dat en _create_nbs para
        # actualizar el mismo registro en vez de crear uno nuevo.
        self._own_icnum = (
            existing.new_coverage.icnum if existing is not None and existing.new_coverage is not None else None
        )

        self.title(config.text("nbs_wizard.edit_title") if existing is not None else config.text("nbs_wizard.title"))
        self.configure(fg_color=self._colors.get("window_bg"))
        self.geometry(_WINDOW_SIZE)
        self.transient(master)

        self._plant_dat = parse_plant_dat_file(self._txtinout_dir / "plant.dat")

        self._state: dict = {
            "name": "",
            "description": "",
            "coverage_mode": "existing",
            "target_cpnm": "",
            "new_idc": 7,
            "physiology": {},
            "hru_params": {"CANMX": None, "OV_N": None, "RSDIN": None},
            "mgt_initial": {"IGRO": None, "LAI_INIT": None, "BIO_INIT": None, "PHU_PLT": None},
            "cn2_by_hsg": {},
            "operations": [],
        }
        if existing is not None:
            self._state["name"] = existing.name
            self._state["description"] = existing.description
            self._state["coverage_mode"] = "new" if existing.new_coverage is not None else "existing"
            self._state["target_cpnm"] = existing.target_lulc
            if existing.new_coverage is not None:
                self._state["new_idc"] = existing.new_coverage.idc
                self._state["physiology"] = dict(existing.new_coverage.physiology)
            self._state["hru_params"] = dict(existing.hru_params)
            self._state["mgt_initial"] = dict(existing.mgt_initial)
            self._state["cn2_by_hsg"] = dict(existing.cn2_by_hsg)
            self._state["operations"] = [
                NbSOperation(mgt_op=op.mgt_op, month=op.month, day=op.day, husc=op.husc, fields=dict(op.fields))
                for op in existing.operations
            ]

        self._step_index = 0
        self._combinations: list = []

        self._header_label = ctk.CTkLabel(
            self, font=ctk.CTkFont(size=16, weight="bold"), text_color=self._colors.get("accent"), anchor="w"
        )
        self._header_label.pack(fill="x", padx=20, pady=(20, 4))

        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.pack(fill="both", expand=True, padx=20, pady=4)

        self._status_label = ctk.CTkLabel(self, text="", anchor="w", wraplength=self._content_wraplength(), justify="left")
        self._status_label.pack(fill="x", padx=20, pady=(4, 0))

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=20, pady=20)
        self._back_button = ctk.CTkButton(
            actions, text=config.text("nbs_wizard.back"),
            fg_color="transparent", border_width=1, border_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"), hover_color=self._colors.get("window_bg"),
            command=self._on_back_clicked,
        )
        self._back_button.pack(side="left")
        ctk.CTkButton(
            actions, text=config.text("action.cancel"),
            fg_color="transparent", border_width=1, border_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"), hover_color=self._colors.get("window_bg"),
            command=self.destroy,
        ).pack(side="right")
        self._next_button = ctk.CTkButton(actions, text=config.text("nbs_wizard.next"), command=self._on_next_clicked)
        self._next_button.pack(side="right", padx=(0, 8))

        self._render_step()
        self.grab_set()

    # -- helpers de estado --------------------------------------------------

    def _set_status(self, text: str, *, error: bool = True) -> None:
        self._status_label.configure(text=text, text_color=self._colors.get("error" if error else "success"))

    def _step_sequence(self) -> list[str]:
        seq = ["name", "coverage"]
        if self._state["coverage_mode"] == "new":
            seq.append("physiology")
        seq += ["copy_from_existing", "hru_params", "mgt_initial", "operations", "review"]
        return seq

    def _current_step_key(self) -> str:
        return self._step_sequence()[self._step_index]

    def _content_wraplength(self) -> int:
        """Ancho de wraplength para labels de ayuda de este paso, calculado
        contra el ancho real actual de la ventana en vez de un valor fijo
        adivinado (bug real reportado por el usuario: texto mal ajustado
        cuando el ancho real no coincidía con lo asumido). No se usa
        bind_responsive_wraplength (ui.widgets) acá a propósito:
        _render_step destruye y reconstruye los labels de cada paso en
        cada Next/Back, y esa utilidad engancha un bind persistente sobre
        el master -- como aquí el master (self._content) sobrevive entre
        pasos, cada visita a un paso agregaría un bind nuevo apuntando a
        labels ya destruidos de la visita anterior (TclError tarde o
        temprano). Recalcular el ancho una vez por render, sin bind
        persistente, evita el problema."""
        width = self.winfo_width()
        if width <= 100:  # la ventana todavía no terminó de dibujarse (winfo_width no confiable)
            width = int(_WINDOW_SIZE.split("x")[0])
        return max(width - 80, 200)

    def _render_step(self) -> None:
        for child in self._content.winfo_children():
            child.destroy()
        self._status_label.configure(text="")

        seq = self._step_sequence()
        key = seq[self._step_index]
        self._header_label.configure(
            text=f"{self._step_index + 1}/{len(seq)} — {self._config.text(_STEP_TITLE_KEYS[key])}"
        )
        self._back_button.configure(state="normal" if self._step_index > 0 else "disabled")
        if key == "review":
            review_text = (
                self._config.text("nbs_wizard.save_button")
                if self._editing_original_name is not None
                else self._config.text("nbs_wizard.create_button")
            )
        else:
            review_text = self._config.text("nbs_wizard.next")
        self._next_button.configure(text=review_text)

        getattr(self, f"_build_step_{key}")()

    def _on_next_clicked(self) -> None:
        key = self._current_step_key()
        if not getattr(self, f"_collect_step_{key}")():
            return
        if key == "review":
            self._create_nbs()
            return
        self._step_index += 1
        self._render_step()

    def _on_back_clicked(self) -> None:
        if self._step_index == 0:
            return
        self._step_index -= 1
        self._render_step()

    # -- paso: nombre ---------------------------------------------------------

    def _build_step_name(self) -> None:
        self._content.columnconfigure(0, weight=1)

        label = ctk.CTkLabel(
            self._content, text=self._config.text("nbs_wizard.name_label"),
            text_color=self._colors.get("text_secondary"), anchor="w",
        )
        label.grid(row=0, column=0, sticky="w")
        self._name_entry = ctk.CTkEntry(self._content)
        self._name_entry.insert(0, self._state["name"])
        self._name_entry.grid(row=1, column=0, sticky="ew", pady=(4, 16))

        desc_label = ctk.CTkLabel(
            self._content, text=self._config.text("nbs_wizard.description_label"),
            text_color=self._colors.get("text_secondary"), anchor="w",
        )
        desc_label.grid(row=2, column=0, sticky="w")
        self._description_text = ctk.CTkTextbox(self._content, height=120)
        self._description_text.insert("1.0", self._state["description"])
        self._description_text.grid(row=3, column=0, sticky="ew")

    def _collect_step_name(self) -> bool:
        name = self._name_entry.get().strip()
        if not name:
            self._set_status(self._config.text("nbs_wizard.name_required"))
            return False
        existing_names = {d.name for d in load_library(self._project_dir) if d.name != self._editing_original_name}
        if name in existing_names:
            self._set_status(self._config.text("nbs_wizard.name_taken").format(name=name))
            return False
        self._state["name"] = name
        self._state["description"] = self._description_text.get("1.0", "end").strip()
        return True

    # -- paso: cobertura ------------------------------------------------------

    def _build_step_coverage(self) -> None:
        self._content.columnconfigure(0, weight=1)

        mode_frame = ctk.CTkFrame(self._content, fg_color="transparent")
        mode_frame.grid(row=0, column=0, sticky="w", pady=(0, 12))
        self._coverage_mode_var = ctk.StringVar(value=self._state["coverage_mode"])
        ctk.CTkRadioButton(
            mode_frame, text=self._config.text("nbs_wizard.coverage_existing"),
            variable=self._coverage_mode_var, value="existing", command=self._render_coverage_body,
        ).pack(side="left", padx=(0, 16))
        ctk.CTkRadioButton(
            mode_frame, text=self._config.text("nbs_wizard.coverage_new"),
            variable=self._coverage_mode_var, value="new", command=self._render_coverage_body,
        ).pack(side="left")

        self._coverage_body = ctk.CTkFrame(self._content, fg_color="transparent")
        self._coverage_body.grid(row=1, column=0, sticky="ew")
        self._coverage_body.columnconfigure(0, weight=1)
        self._render_coverage_body()

    def _sorted_plant_records(self):
        return sorted(self._plant_dat.records, key=lambda r: r.cpnm)

    def _render_coverage_body(self) -> None:
        for child in self._coverage_body.winfo_children():
            child.destroy()

        if self._coverage_mode_var.get() == "existing":
            label = ctk.CTkLabel(
                self._coverage_body, text=self._config.text("nbs_wizard.existing_cpnm_label"),
                text_color=self._colors.get("text_secondary"), anchor="w",
            )
            label.grid(row=0, column=0, sticky="w")

            records = self._sorted_plant_records()
            self._existing_cpnm_codes = [r.cpnm for r in records]
            values = [f"{r.cpnm} — {name_for(r.cpnm)}" for r in records]
            style = style_combobox(self._config)
            self._existing_cpnm_selector = ttk.Combobox(
                self._coverage_body, style=style, state="readonly", values=values, width=42
            )
            if self._state["target_cpnm"] in self._existing_cpnm_codes:
                self._existing_cpnm_selector.current(self._existing_cpnm_codes.index(self._state["target_cpnm"]))
            elif values:
                self._existing_cpnm_selector.current(0)
            self._existing_cpnm_selector.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        else:
            cpnm_label = ctk.CTkLabel(
                self._coverage_body, text=self._config.text("nbs_wizard.new_cpnm_label"),
                text_color=self._colors.get("text_secondary"), anchor="w",
            )
            cpnm_label.grid(row=0, column=0, sticky="w")
            self._new_cpnm_entry = ctk.CTkEntry(self._coverage_body, placeholder_text="RFOR")
            if self._state["coverage_mode"] == "new":
                self._new_cpnm_entry.insert(0, self._state["target_cpnm"])
            self._new_cpnm_entry.grid(row=1, column=0, sticky="ew", pady=(4, 12))

            idc_label = ctk.CTkLabel(
                self._coverage_body, text=self._config.text("nbs_wizard.idc_label"),
                text_color=self._colors.get("text_secondary"), anchor="w",
            )
            idc_label.grid(row=2, column=0, sticky="w")
            self._idc_codes = sorted(IDC_CLASSES)
            style = style_combobox(self._config)
            self._idc_selector = ttk.Combobox(
                self._coverage_body, style=style, state="readonly",
                values=[IDC_CLASSES[c] for c in self._idc_codes], width=42,
            )
            self._idc_selector.current(
                self._idc_codes.index(self._state["new_idc"]) if self._state["new_idc"] in self._idc_codes else 6
            )
            self._idc_selector.grid(row=3, column=0, sticky="ew", pady=(4, 0))

    def _collect_step_coverage(self) -> bool:
        mode = self._coverage_mode_var.get()
        self._state["coverage_mode"] = mode
        if mode == "existing":
            index = self._existing_cpnm_selector.current()
            if index < 0:
                self._set_status(self._config.text("nbs_wizard.existing_cpnm_required"))
                return False
            self._state["target_cpnm"] = self._existing_cpnm_codes[index]
        else:
            cpnm = self._new_cpnm_entry.get().strip().upper()
            if len(cpnm) != 4:
                self._set_status(self._config.text("nbs_wizard.cpnm_length_error"))
                return False
            taken_by = self._plant_dat.get_record_by_cpnm(cpnm)
            if taken_by is not None and taken_by.icnum != self._own_icnum:
                self._set_status(self._config.text("nbs_wizard.cpnm_taken_error").format(cpnm=cpnm))
                return False
            self._state["target_cpnm"] = cpnm
            self._state["new_idc"] = self._idc_codes[self._idc_selector.current()]
        return True

    # -- paso: fisiología (solo cobertura nueva) -------------------------------

    def _build_step_physiology(self) -> None:
        self._content.columnconfigure(0, weight=1)
        self._content.rowconfigure(2, weight=1)

        copy_label = ctk.CTkLabel(
            self._content, text=self._config.text("nbs_wizard.physiology_copy_label"),
            text_color=self._colors.get("text_secondary"), anchor="w",
        )
        copy_label.grid(row=0, column=0, sticky="w")

        records = self._sorted_plant_records()
        none_option = self._config.text("nbs_wizard.physiology_copy_none")
        self._phys_copy_codes: list[str | None] = [None] + [r.cpnm for r in records]
        values = [none_option] + [f"{r.cpnm} — {name_for(r.cpnm)}" for r in records]
        style = style_combobox(self._config)
        self._phys_copy_selector = ttk.Combobox(self._content, style=style, state="readonly", values=values, width=42)
        self._phys_copy_selector.current(0)
        self._phys_copy_selector.grid(row=1, column=0, sticky="ew", pady=(4, 8))
        self._phys_copy_selector.bind("<<ComboboxSelected>>", lambda _e: self._on_physiology_copy_selected())

        self._phys_scroll = ctk.CTkScrollableFrame(self._content, fg_color="transparent")
        self._phys_scroll.grid(row=2, column=0, sticky="nsew")
        self._phys_scroll.columnconfigure(0, weight=1)
        self._phys_entries: dict[str, ctk.CTkEntry] = {}
        self._render_physiology_fields()

    def _render_physiology_fields(self) -> None:
        for child in self._phys_scroll.winfo_children():
            child.destroy()
        self._phys_entries = {}
        row = 0
        for group_title, names in _PHYSIOLOGY_GROUPS:
            group_label = ctk.CTkLabel(
                self._phys_scroll, text=group_title, text_color=self._colors.get("text_primary"),
                font=ctk.CTkFont(size=12, weight="bold"), anchor="w",
            )
            group_label.grid(row=row, column=0, sticky="w", pady=(10 if row else 0, 4))
            row += 1
            for name in names:
                label = ctk.CTkLabel(
                    self._phys_scroll, text=label_for(name), text_color=self._colors.get("text_secondary"),
                    anchor="w", wraplength=self._content_wraplength(), justify="left",
                )
                label.grid(row=row, column=0, sticky="w", pady=(6, 2))
                row += 1
                entry = ctk.CTkEntry(self._phys_scroll)
                value = self._state["physiology"].get(name)
                if value is not None:
                    entry.insert(0, str(value))
                entry.grid(row=row, column=0, sticky="ew")
                row += 1
                self._phys_entries[name] = entry

    def _on_physiology_copy_selected(self) -> None:
        index = self._phys_copy_selector.current()
        cpnm = self._phys_copy_codes[index] if index >= 0 else None
        if cpnm is None:
            return
        record = self._plant_dat.get_record_by_cpnm(cpnm)
        if record is None:
            return
        for name, entry in self._phys_entries.items():
            entry.delete(0, "end")
            value = record.fields.get(name)
            if value is not None:
                entry.insert(0, str(value))

    def _collect_step_physiology(self) -> bool:
        values: dict[str, float | int] = {}
        for name, entry in self._phys_entries.items():
            raw = entry.get().strip()
            if not raw:
                self._set_status(self._config.text("nbs_wizard.physiology_missing").format(field=label_for(name)))
                return False
            try:
                values[name] = int(raw) if name == "MAT_YRS" else float(raw)
            except ValueError:
                self._set_status(self._config.text("nbs_wizard.physiology_invalid").format(field=label_for(name)))
                return False
        self._state["physiology"] = values
        return True

    # -- paso: copiar de configuración existente ------------------------------

    def _build_step_copy_from_existing(self) -> None:
        self._content.columnconfigure(0, weight=1)
        self._content.rowconfigure(2, weight=1)

        records = self._sorted_plant_records()
        self._copy_scan_codes = [r.cpnm for r in records]
        values = [f"{r.cpnm} — {name_for(r.cpnm)}" for r in records]

        row0 = ctk.CTkFrame(self._content, fg_color="transparent")
        row0.grid(row=0, column=0, sticky="ew")
        row0.columnconfigure(0, weight=1)
        style = style_combobox(self._config)
        self._copy_scan_selector = ttk.Combobox(row0, style=style, state="readonly", values=values, width=38)
        default_cpnm = self._state["target_cpnm"] if self._state["target_cpnm"] in self._copy_scan_codes else None
        if default_cpnm is not None:
            self._copy_scan_selector.current(self._copy_scan_codes.index(default_cpnm))
        elif values:
            self._copy_scan_selector.current(0)
        self._copy_scan_selector.grid(row=0, column=0, sticky="ew")
        self._scan_button = ctk.CTkButton(
            row0, text=self._config.text("nbs_wizard.copy_scan_button"), command=self._on_scan_clicked, width=100
        )
        self._scan_button.grid(row=0, column=1, padx=(8, 0))

        self._copy_status_label = ctk.CTkLabel(
            self._content, text=self._config.text("nbs_wizard.copy_hint"),
            text_color=self._colors.get("text_secondary"), anchor="w", justify="left", wraplength=self._content_wraplength(),
        )
        self._copy_status_label.grid(row=1, column=0, sticky="ew", pady=(8, 8))

        columns = ("count", "subbasins", "canmx", "ov_n", "cn2", "ops")
        self._combo_tree, combo_tree_container = build_scrollable_treeview(
            self._content, self._config, columns=columns, height=8, style_prefix="NbSCombo"
        )
        headings = (
            ("count", "nbs_wizard.copy_col_count", 90),
            ("subbasins", "nbs_wizard.copy_col_subbasins", 90),
            ("canmx", "nbs_wizard.copy_col_canmx", 90),
            ("ov_n", "nbs_wizard.copy_col_ov_n", 90),
            ("cn2", "nbs_wizard.copy_col_cn2", 220),
            ("ops", "nbs_wizard.copy_col_ops", 90),
        )
        for col, key, width in headings:
            self._combo_tree.heading(col, text=self._config.text(key))
            self._combo_tree.column(col, width=width, anchor="center", stretch=False)
        combo_tree_container.grid(row=2, column=0, sticky="nsew")

        use_button = ctk.CTkButton(
            self._content, text=self._config.text("nbs_wizard.copy_use_button"), command=self._on_use_combination_clicked
        )
        use_button.grid(row=3, column=0, sticky="nw", pady=(8, 0))

    def _on_scan_clicked(self) -> None:
        index = self._copy_scan_selector.current()
        if index < 0:
            return
        cpnm = self._copy_scan_codes[index]
        self._scan_button.configure(state="disabled")
        self._copy_status_label.configure(text=self._config.text("nbs_wizard.copy_scanning"))
        for item in self._combo_tree.get_children():
            self._combo_tree.delete(item)

        txtinout_dir = self._txtinout_dir

        def work(_report_progress):
            return scan_existing_parameter_combinations(txtinout_dir, cpnm)

        run_in_background(self, work, on_progress=lambda _m: None, on_done=self._on_scan_done, on_error=self._on_scan_error)

    def _on_scan_done(self, combinations: list) -> None:
        self._combinations = combinations
        self._scan_button.configure(state="normal")
        if not combinations:
            self._copy_status_label.configure(text=self._config.text("nbs_wizard.copy_no_results"))
            return
        self._copy_status_label.configure(
            text=self._config.text("nbs_wizard.copy_results_hint").format(count=len(combinations))
        )
        for i, combo in enumerate(combinations):
            cn2_summary = ", ".join(f"{hsg}:{value:.1f}" for hsg, value in sorted(combo.cn2_by_hsg.items()))
            self._combo_tree.insert(
                "", "end", iid=str(i),
                values=(
                    combo.hru_count, len(combo.subbasins),
                    combo.hru_params.get("CANMX"), combo.hru_params.get("OV_N"),
                    cn2_summary, len(combo.operations),
                ),
            )

    def _on_scan_error(self, error: Exception) -> None:
        self._scan_button.configure(state="normal")
        self._copy_status_label.configure(text=self._config.text("nbs_wizard.copy_scan_error").format(error=str(error)))

    def _on_use_combination_clicked(self) -> None:
        selection = self._combo_tree.selection()
        if not selection:
            self._set_status(self._config.text("nbs_wizard.copy_selection_required"))
            return
        combo = self._combinations[int(selection[0])]
        self._state["hru_params"] = dict(combo.hru_params)
        self._state["mgt_initial"] = dict(combo.mgt_initial)
        self._state["cn2_by_hsg"] = dict(combo.cn2_by_hsg)
        self._state["operations"] = [
            NbSOperation(mgt_op=op.mgt_op, month=op.month, day=op.day, husc=op.husc, fields=dict(op.fields))
            for op in combo.operations
        ]
        self._set_status(self._config.text("nbs_wizard.copy_applied"), error=False)

    def _collect_step_copy_from_existing(self) -> bool:
        return True  # siempre opcional -- los pasos siguientes validan lo que falte

    # -- paso: parámetros .hru ------------------------------------------------

    def _build_step_hru_params(self) -> None:
        self._content.columnconfigure(0, weight=1)
        self._hru_param_entries: dict[str, ctk.CTkEntry] = {}
        for row, name in enumerate(_HRU_PARAM_ALL):
            required = name in _HRU_PARAM_REQUIRED
            suffix = "" if required else self._config.text("nbs_wizard.optional_suffix")
            label = ctk.CTkLabel(
                self._content, text=label_for(name) + suffix, text_color=self._colors.get("text_secondary"),
                anchor="w", wraplength=self._content_wraplength(), justify="left",
            )
            label.grid(row=row * 2, column=0, sticky="w", pady=(10 if row else 0, 2))
            entry = ctk.CTkEntry(self._content)
            value = self._state["hru_params"].get(name)
            if value is not None:
                entry.insert(0, str(value))
            entry.grid(row=row * 2 + 1, column=0, sticky="ew")
            self._hru_param_entries[name] = entry

    def _collect_step_hru_params(self) -> bool:
        values: dict[str, float | None] = {}
        for name, entry in self._hru_param_entries.items():
            raw = entry.get().strip()
            if not raw:
                if name in _HRU_PARAM_REQUIRED:
                    self._set_status(self._config.text("nbs_wizard.field_required").format(field=label_for(name)))
                    return False
                values[name] = None
                continue
            try:
                values[name] = float(raw)
            except ValueError:
                self._set_status(self._config.text("nbs_wizard.field_invalid").format(field=label_for(name)))
                return False
        self._state["hru_params"] = values
        return True

    # -- paso: condición inicial .mgt + CN2 por HSG ---------------------------

    def _build_step_mgt_initial(self) -> None:
        self._content.columnconfigure(0, weight=1)

        igro_label = ctk.CTkLabel(
            self._content, text=label_for("IGRO"), text_color=self._colors.get("text_secondary"), anchor="w",
            wraplength=self._content_wraplength(), justify="left",
        )
        igro_label.grid(row=0, column=0, sticky="w")
        style = style_combobox(self._config)
        self._igro_selector = ttk.Combobox(self._content, style=style, state="readonly", values=["0", "1"], width=10)
        self._igro_selector.current(1 if self._state["mgt_initial"].get("IGRO") == 1 else 0)
        self._igro_selector.grid(row=1, column=0, sticky="w", pady=(4, 12))
        self._igro_selector.bind("<<ComboboxSelected>>", lambda _e: self._render_initial_fields())

        self._initial_fields_frame = ctk.CTkFrame(self._content, fg_color="transparent")
        self._initial_fields_frame.grid(row=2, column=0, sticky="ew")
        self._initial_fields_frame.columnconfigure(0, weight=1)
        self._initial_entries: dict[str, ctk.CTkEntry] = {}
        self._render_initial_fields()

        separator = ctk.CTkFrame(self._content, height=1, fg_color=self._colors.get("border"))
        separator.grid(row=3, column=0, sticky="ew", pady=16)

        cn2_title = ctk.CTkLabel(
            self._content, text=self._config.text("nbs_wizard.cn2_title"), text_color=self._colors.get("text_primary"),
            font=ctk.CTkFont(size=13, weight="bold"), anchor="w",
        )
        cn2_title.grid(row=4, column=0, sticky="w")
        cn2_hint = ctk.CTkLabel(
            self._content, text=self._config.text("nbs_wizard.cn2_hint"), text_color=self._colors.get("text_secondary"),
            anchor="w", justify="left", wraplength=self._content_wraplength(),
        )
        cn2_hint.grid(row=5, column=0, sticky="w", pady=(2, 8))

        cn2_frame = ctk.CTkFrame(self._content, fg_color="transparent")
        cn2_frame.grid(row=6, column=0, sticky="ew")
        self._cn2_entries: dict[str, ctk.CTkEntry] = {}
        for col, hsg in enumerate(HYDROLOGIC_SOIL_GROUPS):
            cn2_frame.columnconfigure(col, weight=1)
            label = ctk.CTkLabel(cn2_frame, text=f"HSG {hsg}", text_color=self._colors.get("text_secondary"))
            label.grid(row=0, column=col, sticky="w", padx=(0 if col == 0 else 8, 0))
            entry = ctk.CTkEntry(cn2_frame, width=80)
            value = self._state["cn2_by_hsg"].get(hsg)
            if value is not None:
                entry.insert(0, str(value))
            entry.grid(row=1, column=col, sticky="w", padx=(0 if col == 0 else 8, 0))
            self._cn2_entries[hsg] = entry

    def _render_initial_fields(self) -> None:
        for child in self._initial_fields_frame.winfo_children():
            child.destroy()
        self._initial_entries = {}
        if self._igro_selector.get() != "1":
            return
        for row, name in enumerate(("LAI_INIT", "BIO_INIT", "PHU_PLT")):
            label = ctk.CTkLabel(
                self._initial_fields_frame, text=label_for(name), text_color=self._colors.get("text_secondary"),
                anchor="w", wraplength=self._content_wraplength(), justify="left",
            )
            label.grid(row=row * 2, column=0, sticky="w", pady=(6 if row else 0, 2))
            entry = ctk.CTkEntry(self._initial_fields_frame)
            value = self._state["mgt_initial"].get(name)
            if value is not None:
                entry.insert(0, str(value))
            entry.grid(row=row * 2 + 1, column=0, sticky="ew")
            self._initial_entries[name] = entry

    def _collect_step_mgt_initial(self) -> bool:
        igro = int(self._igro_selector.get())
        mgt_initial: dict[str, float | int | None] = {"IGRO": igro, "LAI_INIT": None, "BIO_INIT": None, "PHU_PLT": None}
        if igro == 1:
            for name, entry in self._initial_entries.items():
                raw = entry.get().strip()
                if not raw:
                    self._set_status(self._config.text("nbs_wizard.field_required").format(field=label_for(name)))
                    return False
                try:
                    mgt_initial[name] = float(raw)
                except ValueError:
                    self._set_status(self._config.text("nbs_wizard.field_invalid").format(field=label_for(name)))
                    return False
        self._state["mgt_initial"] = mgt_initial

        cn2_by_hsg: dict[str, float] = {}
        for hsg, entry in self._cn2_entries.items():
            raw = entry.get().strip()
            if raw:
                try:
                    cn2_by_hsg[hsg] = float(raw)
                except ValueError:
                    self._set_status(self._config.text("nbs_wizard.field_invalid").format(field=f"CN2 ({hsg})"))
                    return False
        if not cn2_by_hsg:
            self._set_status(self._config.text("nbs_wizard.cn2_required"))
            return False
        self._state["cn2_by_hsg"] = cn2_by_hsg
        return True

    # -- paso: calendario de manejo -------------------------------------------

    def _build_step_operations(self) -> None:
        self._content.columnconfigure(0, weight=1)
        self._content.rowconfigure(1, weight=1)

        hint = ctk.CTkLabel(
            self._content, text=self._config.text("nbs_wizard.operations_hint"),
            text_color=self._colors.get("text_secondary"), anchor="w", justify="left", wraplength=self._content_wraplength(),
        )
        hint.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        columns = ("type", "schedule", "summary")
        self._ops_tree, ops_tree_container = build_scrollable_treeview(
            self._content, self._config, columns=columns, height=10, style_prefix="NbSOps"
        )
        self._ops_tree.heading("type", text=self._config.text("nbs_wizard.ops_col_type"))
        self._ops_tree.heading("schedule", text=self._config.text("nbs_wizard.ops_col_schedule"))
        self._ops_tree.heading("summary", text=self._config.text("nbs_wizard.ops_col_summary"))
        self._ops_tree.column("type", width=220, stretch=False)
        self._ops_tree.column("schedule", width=100, anchor="center", stretch=False)
        self._ops_tree.column("summary", width=480, stretch=False)
        ops_tree_container.grid(row=1, column=0, sticky="nsew")
        self._refresh_ops_tree()

        buttons = ctk.CTkFrame(self._content, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="w", pady=(8, 0))
        ctk.CTkButton(
            buttons, text=self._config.text("nbs_wizard.ops_add_button"), command=self._on_add_operation_clicked, width=90
        ).pack(side="left")
        ctk.CTkButton(
            buttons, text=self._config.text("nbs_wizard.ops_remove_button"),
            fg_color="transparent", border_width=1, border_color=self._colors.get("border"),
            text_color=self._colors.get("text_primary"), hover_color=self._colors.get("window_bg"),
            command=self._on_remove_operation_clicked, width=90,
        ).pack(side="left", padx=(8, 0))

    def _refresh_ops_tree(self) -> None:
        for item in self._ops_tree.get_children():
            self._ops_tree.delete(item)
        for i, op in enumerate(self._state["operations"]):
            type_text = f"{op.mgt_op} — {MGT_OPERATION_NAMES.get(op.mgt_op, '?')}"
            schedule_text = f"HUSC {op.husc}" if op.husc is not None else f"{op.month}/{op.day}"
            summary = ", ".join(f"{k}={v}" for k, v in op.fields.items() if v is not None)
            self._ops_tree.insert("", "end", iid=str(i), values=(type_text, schedule_text, summary))

    def _on_add_operation_clicked(self) -> None:
        def on_confirm(operation: NbSOperation) -> None:
            self._state["operations"].append(operation)
            self._refresh_ops_tree()

        NbSOperationDialog(self, self._config, on_confirm=on_confirm)

    def _on_remove_operation_clicked(self) -> None:
        selection = self._ops_tree.selection()
        if not selection:
            return
        index = int(selection[0])
        del self._state["operations"][index]
        self._refresh_ops_tree()

    def _collect_step_operations(self) -> bool:
        return True  # el calendario puede quedar vacío -- no se fuerza un mínimo de operaciones

    # -- paso: revisión y guardado ---------------------------------------------

    def _build_step_review(self) -> None:
        self._content.columnconfigure(0, weight=1)
        mode_label = (
            self._config.text("nbs_wizard.coverage_new")
            if self._state["coverage_mode"] == "new"
            else self._config.text("nbs_wizard.coverage_existing")
        )
        lines = [
            self._config.text("nbs_wizard.review_name").format(name=self._state["name"]),
            self._config.text("nbs_wizard.review_target").format(
                cpnm=self._state["target_cpnm"], name=name_for(self._state["target_cpnm"])
            ),
            self._config.text("nbs_wizard.review_mode").format(mode=mode_label),
            self._config.text("nbs_wizard.review_hru_params").format(
                canmx=self._state["hru_params"].get("CANMX"),
                ov_n=self._state["hru_params"].get("OV_N"),
                rsdin=self._state["hru_params"].get("RSDIN"),
            ),
            self._config.text("nbs_wizard.review_igro").format(igro=self._state["mgt_initial"].get("IGRO")),
            self._config.text("nbs_wizard.review_cn2").format(
                cn2=", ".join(f"{hsg}={v}" for hsg, v in sorted(self._state["cn2_by_hsg"].items()))
            ),
            self._config.text("nbs_wizard.review_ops").format(count=len(self._state["operations"])),
        ]
        text = ctk.CTkTextbox(self._content, height=300)
        text.insert("1.0", "\n".join(lines))
        text.configure(state="disabled")
        text.grid(row=0, column=0, sticky="ew")

    def _collect_step_review(self) -> bool:
        return True

    def _create_nbs(self) -> None:
        new_coverage = None
        if self._state["coverage_mode"] == "new":
            new_coverage = NbSNewCoverage(
                cpnm=self._state["target_cpnm"], idc=self._state["new_idc"],
                physiology=dict(self._state["physiology"]), icnum=self._own_icnum,
            )

        definition = NbSDefinition(
            name=self._state["name"],
            target_lulc=self._state["target_cpnm"],
            new_coverage=new_coverage,
            hru_params=dict(self._state["hru_params"]),
            mgt_initial=dict(self._state["mgt_initial"]),
            cn2_by_hsg=dict(self._state["cn2_by_hsg"]),
            operations=list(self._state["operations"]),
            description=self._state["description"],
        )

        errors = validate_nbs_definition(definition, self._plant_dat)
        if errors:
            self._set_status("; ".join(errors))
            return

        if new_coverage is not None:
            ConfirmDialog(
                self, self._config,
                message=self._config.text("nbs_wizard.plant_dat_confirm").format(cpnm=new_coverage.cpnm),
                on_confirm=lambda: self._finish_save(definition),
            )
        else:
            self._finish_save(definition)

    def _finish_save(self, definition: NbSDefinition) -> None:
        if definition.new_coverage is not None:
            try:
                sync_new_coverage_to_plant_dat(self._project_dir, definition)
            except NbSApplyError as exc:
                self._set_status(str(exc))
                return
        add_or_replace(self._project_dir, definition)
        self._on_created()
        self.destroy()
