"""Pestaña Restoration Inputs: prepara los CSV de entrada para "Apply an
NbS by area (all subbasins)" (pestaña NbS) y para NbS area batch (pestaña
Batch Scenarios) a partir de dos rasters reales -- uno de cobertura actual
(puede ser gigante, ej. un raster de todo un país) y uno de restauración/
NbS (categórico, extensión acotada a la cuenca) -- cruzados contra el
shapefile de subcuencas ya configurado en Project.

Todo el trabajo pesado vive en raster_io/ (sin UI) y
scenarios/nbs_raster_inputs.py (orquestación + formato de salida); esta
pestaña solo arma la UI y corre las dos operaciones largas
(Scan/Compute) en hilo de fondo -- ver CLAUDE.md, "Operaciones largas y UI
no bloqueante": aunque el rectángulo de trabajo real es chico (acotado a
cuenca ∩ raster de restauración, nunca al raster de cobertura completo),
sigue siendo E/S sobre un archivo potencialmente enorme en una unidad de
red, así que corre en background igual que el resto de las operaciones
que tocan un modelo real.

Ni Scan ni Compute tocan TxtInOut -- Compute solo escribe CSV nuevos en
tool_outputs/restoration_inputs/ -- así que, mismo criterio que "Organize
.rch"/".sub"/".hru output", ninguno de los dos pide confirmación.
"""
from __future__ import annotations

import os
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Callable

import customtkinter as ctk

from config.settings import ConfigManager
from scenarios.activity_log import log_action
from scenarios.nbs_raster_inputs import (
    RestorationComputeResult,
    RestorationScanResult,
    compute_restoration_area_csvs,
    discover_project_coverages,
    scan_restoration_inputs,
)
from scenarios.project import ProjectMetadata, save_project, validate_raster_path
from swat_io.tool_outputs import tool_outputs_dir

from .tasks import run_in_background
from .widgets import ReadOnlyField, bind_responsive_wraplength, palette, style_combobox

_SKIP_VALUE = ""


class RestorationInputsTab(ctk.CTkFrame):
    def __init__(
        self, master: ctk.CTkBaseClass, config: ConfigManager, *, on_run_state_changed: Callable[[bool], None], **kwargs
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._config = config
        self._colors = palette(config)
        self._on_run_state_changed = on_run_state_changed

        self._project_dir: Path | None = None
        self._metadata: ProjectMetadata = ProjectMetadata()
        self._scan_result: RestorationScanResult | None = None
        self._project_coverages: list[str] = []
        self._crosswalk_selectors: dict[int, ttk.Combobox] = {}

        self._disabled_state = self._build_disabled_state()
        self._enabled_state = self._build_enabled_state()
        self._disabled_state.pack(fill="both", expand=True)

    # -- construcción --------------------------------------------------------

    def _build_disabled_state(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        hint = ctk.CTkLabel(
            frame, text=self._config.text("summary.disabled_hint"), text_color=self._colors.get("text_secondary")
        )
        hint.place(relx=0.5, rely=0.4, anchor="center")
        return frame

    def _build_enabled_state(self) -> ctk.CTkFrame:
        frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        frame.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            frame, text=self._config.text("restoration_inputs_tab.title"), text_color=self._colors.get("accent"),
            font=ctk.CTkFont(size=18, weight="bold"), anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))

        subtitle = ctk.CTkLabel(
            frame, text=self._config.text("restoration_inputs_tab.subtitle"),
            text_color=self._colors.get("text_secondary"), anchor="w", justify="left",
        )
        subtitle.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        bind_responsive_wraplength(subtitle)

        self._build_rasters_card(frame, row=2)
        self._build_scan_card(frame, row=3)
        self._build_compute_card(frame, row=4)

        return frame

    def _build_rasters_card(self, parent: ctk.CTkFrame, *, row: int) -> None:
        card = ctk.CTkFrame(parent)
        card.grid(row=row, column=0, sticky="ew", pady=(0, 16))
        card.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card, text=self._config.text("restoration_inputs_tab.rasters_title"),
            text_color=self._colors.get("text_primary"), font=ctk.CTkFont(size=14, weight="bold"), anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))

        hint = ctk.CTkLabel(
            card, text=self._config.text("restoration_inputs_tab.rasters_hint"),
            text_color=self._colors.get("text_secondary"), anchor="w", justify="left",
        )
        hint.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        bind_responsive_wraplength(hint)

        self._land_cover_field, _btn = self._build_raster_row(
            card, row=2, label_key="restoration_inputs_tab.land_cover_raster_label",
            on_browse=self._on_browse_land_cover_clicked,
        )
        self._restoration_field, _btn2 = self._build_raster_row(
            card, row=3, label_key="restoration_inputs_tab.restoration_raster_label",
            on_browse=self._on_browse_restoration_clicked,
        )

        self._no_shapefile_label = ctk.CTkLabel(
            card, text="", text_color=self._colors.get("warning"), anchor="w", justify="left",
        )
        self._no_shapefile_label.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 16))
        bind_responsive_wraplength(self._no_shapefile_label)

    def _build_raster_row(
        self, master: ctk.CTkBaseClass, *, row: int, label_key: str, on_browse: Callable[[], None]
    ) -> tuple[ReadOnlyField, ctk.CTkButton]:
        row_frame = ctk.CTkFrame(master, fg_color="transparent")
        row_frame.grid(row=row, column=0, sticky="ew", padx=16, pady=(0, 8))
        row_frame.columnconfigure(0, weight=1)

        field = ReadOnlyField(row_frame, self._config, label_key)
        field.grid(row=0, column=0, sticky="ew")

        button = ctk.CTkButton(row_frame, text=self._config.text("config.browse"), command=on_browse, width=90)
        button.grid(row=0, column=1, sticky="ne", padx=(12, 0))
        return field, button

    def _build_scan_card(self, parent: ctk.CTkFrame, *, row: int) -> None:
        card = ctk.CTkFrame(parent)
        card.grid(row=row, column=0, sticky="ew", pady=(0, 16))
        card.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card, text=self._config.text("restoration_inputs_tab.scan_title"),
            text_color=self._colors.get("text_primary"), font=ctk.CTkFont(size=14, weight="bold"), anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))

        hint = ctk.CTkLabel(
            card, text=self._config.text("restoration_inputs_tab.scan_hint"),
            text_color=self._colors.get("text_secondary"), anchor="w", justify="left",
        )
        hint.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        bind_responsive_wraplength(hint)

        controls = ctk.CTkFrame(card, fg_color="transparent")
        controls.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))
        controls.columnconfigure(0, weight=1)
        self._scan_status_label = ctk.CTkLabel(
            controls, text="", text_color=self._colors.get("text_secondary"), anchor="w", justify="left",
        )
        self._scan_status_label.grid(row=0, column=0, sticky="w")
        bind_responsive_wraplength(self._scan_status_label)
        self._scan_button = ctk.CTkButton(
            controls, text=self._config.text("restoration_inputs_tab.scan_button"), command=self._on_scan_clicked
        )
        self._scan_button.grid(row=0, column=1, sticky="e")

        ctk.CTkLabel(
            card, text=self._config.text("restoration_inputs_tab.restoration_classes_title"),
            text_color=self._colors.get("text_primary"), font=ctk.CTkFont(weight="bold"), anchor="w",
        ).grid(row=3, column=0, sticky="w", padx=16, pady=(4, 0))
        self._restoration_classes_label = ctk.CTkLabel(
            card, text="", text_color=self._colors.get("text_secondary"), anchor="w", justify="left",
        )
        self._restoration_classes_label.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 12))
        bind_responsive_wraplength(self._restoration_classes_label)

        ctk.CTkLabel(
            card, text=self._config.text("restoration_inputs_tab.crosswalk_title"),
            text_color=self._colors.get("text_primary"), font=ctk.CTkFont(weight="bold"), anchor="w",
        ).grid(row=5, column=0, sticky="w", padx=16)
        crosswalk_hint = ctk.CTkLabel(
            card, text=self._config.text("restoration_inputs_tab.crosswalk_hint"),
            text_color=self._colors.get("text_secondary"), anchor="w", justify="left",
        )
        crosswalk_hint.grid(row=6, column=0, sticky="ew", padx=16, pady=(0, 4))
        bind_responsive_wraplength(crosswalk_hint)

        self._crosswalk_container = ctk.CTkScrollableFrame(card, fg_color=self._colors.get("surface"), height=220)
        self._crosswalk_container.grid(row=7, column=0, sticky="ew", padx=16, pady=(0, 16))
        self._crosswalk_container.columnconfigure(1, weight=1)

    def _build_compute_card(self, parent: ctk.CTkFrame, *, row: int) -> None:
        card = ctk.CTkFrame(parent)
        card.grid(row=row, column=0, sticky="ew")
        card.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card, text=self._config.text("restoration_inputs_tab.compute_title"),
            text_color=self._colors.get("text_primary"), font=ctk.CTkFont(size=14, weight="bold"), anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))

        hint = ctk.CTkLabel(
            card, text=self._config.text("restoration_inputs_tab.compute_hint"),
            text_color=self._colors.get("text_secondary"), anchor="w", justify="left",
        )
        hint.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        bind_responsive_wraplength(hint)

        controls = ctk.CTkFrame(card, fg_color="transparent")
        controls.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))
        controls.columnconfigure(0, weight=1)
        self._compute_status_label = ctk.CTkLabel(
            controls, text="", text_color=self._colors.get("text_secondary"), anchor="w", justify="left",
        )
        self._compute_status_label.grid(row=0, column=0, sticky="w")
        bind_responsive_wraplength(self._compute_status_label)
        self._open_folder_button = ctk.CTkButton(
            controls, text=self._config.text("restoration_inputs_tab.open_folder_button"),
            command=self._on_open_folder_clicked, fg_color="transparent", border_width=1,
            border_color=self._colors.get("border"), text_color=self._colors.get("text_primary"),
            hover_color=self._colors.get("window_bg"), state="disabled", width=140,
        )
        self._open_folder_button.grid(row=0, column=1, sticky="e", padx=(8, 8))
        self._compute_button = ctk.CTkButton(
            controls, text=self._config.text("restoration_inputs_tab.compute_button"),
            command=self._on_compute_clicked, state="disabled",
        )
        self._compute_button.grid(row=0, column=2, sticky="e")

        log_frame = ctk.CTkFrame(card, fg_color=self._colors.get("surface"))
        log_frame.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 16))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self._compute_log = ctk.CTkTextbox(log_frame, wrap="word", state="disabled", height=140)
        self._compute_log.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    # -- proyecto --------------------------------------------------------------

    def set_project(self, project_dir: Path, metadata: ProjectMetadata) -> None:
        self._project_dir = project_dir
        self._metadata = metadata
        self._enabled_state.pack(fill="both", expand=True)
        self._disabled_state.pack_forget()

        self._land_cover_field.set_value(metadata.land_cover_raster_path or "")
        self._restoration_field.set_value(metadata.restoration_raster_path or "")
        self._refresh_shapefile_hint()

        self._scan_result = None
        self._project_coverages = []
        self._crosswalk_selectors = {}
        for child in list(self._crosswalk_container.winfo_children()):
            child.destroy()
        self._restoration_classes_label.configure(text="")
        self._scan_status_label.configure(text="", text_color=self._colors.get("text_secondary"))
        self._compute_status_label.configure(text="", text_color=self._colors.get("text_secondary"))
        self._set_compute_log("")
        self._compute_button.configure(state="disabled")
        self._open_folder_button.configure(state="disabled")

    def _refresh_shapefile_hint(self) -> None:
        if not self._metadata.subbasin_shp_path:
            self._no_shapefile_label.configure(text=self._config.text("restoration_inputs_tab.no_shapefile_hint"))
        else:
            self._no_shapefile_label.configure(text="")

    # -- rasters --------------------------------------------------------------

    def _on_browse_land_cover_clicked(self) -> None:
        self._browse_raster(attr="land_cover_raster_path", field=self._land_cover_field)

    def _on_browse_restoration_clicked(self) -> None:
        self._browse_raster(attr="restoration_raster_path", field=self._restoration_field)

    def _browse_raster(self, *, attr: str, field: ReadOnlyField) -> None:
        if self._project_dir is None:
            return
        selected = filedialog.askopenfilename(filetypes=[("GeoTIFF", "*.tif *.tiff")])
        if not selected:
            return

        error_key = validate_raster_path(selected)
        if error_key is not None:
            self._scan_status_label.configure(text=self._config.text(error_key), text_color=self._colors.get("error"))
            return

        setattr(self._metadata, attr, str(Path(selected)))
        save_project(self._project_dir, self._metadata)
        field.set_value(getattr(self._metadata, attr))
        log_action(self._project_dir, "PROJECT", f"Set {attr} to '{selected}'.")

    # -- Scan -------------------------------------------------------------------

    def _on_scan_clicked(self) -> None:
        if self._project_dir is None:
            return
        if not (self._metadata.subbasin_shp_path and self._metadata.land_cover_raster_path and self._metadata.restoration_raster_path):
            self._scan_status_label.configure(
                text=self._config.text("restoration_inputs_tab.scan_missing_inputs"), text_color=self._colors.get("error")
            )
            return

        project_dir = self._project_dir
        shp_path = self._metadata.subbasin_shp_path
        land_cover_path = self._metadata.land_cover_raster_path
        restoration_path = self._metadata.restoration_raster_path

        self._scan_button.configure(state="disabled")
        self._compute_button.configure(state="disabled")
        self._scan_status_label.configure(
            text=self._config.text("restoration_inputs_tab.scanning"), text_color=self._colors.get("text_secondary")
        )
        self._on_run_state_changed(True)

        def work(_report_progress):
            scan = scan_restoration_inputs(shp_path, land_cover_path, restoration_path)
            coverages = discover_project_coverages(project_dir)
            return scan, coverages

        run_in_background(self, work, on_progress=lambda _m: None, on_done=self._on_scan_done, on_error=self._on_scan_error)

    def _on_scan_done(self, result: tuple[RestorationScanResult, list[str]]) -> None:
        scan, coverages = result
        self._scan_result = scan
        self._project_coverages = coverages

        self._scan_status_label.configure(
            text=self._config.text("restoration_inputs_tab.scan_summary").format(
                classes=len(scan.restoration_classes), codes=len(scan.land_cover_codes)
            ),
            text_color=self._colors.get("success"),
        )
        self._render_restoration_classes(scan.restoration_classes)
        self._render_crosswalk_rows(scan.land_cover_codes, coverages)
        self._finish_scan()
        self._compute_button.configure(state="normal" if scan.land_cover_codes else "disabled")

    def _on_scan_error(self, error: Exception) -> None:
        self._scan_status_label.configure(
            text=self._config.text("restoration_inputs_tab.scan_error").format(error=str(error)),
            text_color=self._colors.get("error"),
        )
        self._finish_scan()

    def _finish_scan(self) -> None:
        self._scan_button.configure(state="normal")
        self._on_run_state_changed(False)

    def _render_restoration_classes(self, classes) -> None:
        if not classes:
            self._restoration_classes_label.configure(text="")
            return
        lines = []
        for restoration_class in classes:
            if restoration_class.name:
                lines.append(
                    self._config.text("restoration_inputs_tab.restoration_class_row_named").format(
                        value=restoration_class.value, name=restoration_class.name,
                        pixels=f"{restoration_class.approx_pixel_count:,}",
                    )
                )
            else:
                lines.append(
                    self._config.text("restoration_inputs_tab.restoration_class_row").format(
                        value=restoration_class.value, pixels=f"{restoration_class.approx_pixel_count:,}"
                    )
                )
        self._restoration_classes_label.configure(text="\n".join(lines))

    def _render_crosswalk_rows(self, land_cover_codes, coverages: list[str]) -> None:
        for child in list(self._crosswalk_container.winfo_children()):
            child.destroy()
        self._crosswalk_selectors = {}

        style = style_combobox(self._config)
        values = [_SKIP_VALUE, *coverages]
        skip_label = self._config.text("restoration_inputs_tab.crosswalk_skip_option")
        display_values = [skip_label, *coverages]

        for row_index, land_cover_code in enumerate(land_cover_codes):
            label = ctk.CTkLabel(
                self._crosswalk_container,
                text=self._config.text("restoration_inputs_tab.crosswalk_row_label").format(
                    code=land_cover_code.code, pixels=f"{land_cover_code.approx_pixel_count:,}"
                ),
                text_color=self._colors.get("text_primary"), anchor="w",
            )
            label.grid(row=row_index, column=0, sticky="w", padx=(4, 8), pady=2)

            selector = ttk.Combobox(self._crosswalk_container, style=style, state="readonly", values=display_values, width=30)
            selector.set(skip_label)
            selector.grid(row=row_index, column=1, sticky="w", pady=2)
            self._crosswalk_selectors[land_cover_code.code] = selector

    def _current_crosswalk(self) -> dict[int, str]:
        skip_label = self._config.text("restoration_inputs_tab.crosswalk_skip_option")
        crosswalk: dict[int, str] = {}
        for code, selector in self._crosswalk_selectors.items():
            value = selector.get()
            if value and value != skip_label:
                crosswalk[code] = value
        return crosswalk

    # -- Compute ------------------------------------------------------------

    def _on_compute_clicked(self) -> None:
        if self._project_dir is None or self._scan_result is None:
            return
        crosswalk = self._current_crosswalk()
        if not crosswalk:
            self._compute_status_label.configure(
                text=self._config.text("restoration_inputs_tab.compute_missing_crosswalk"),
                text_color=self._colors.get("error"),
            )
            return

        project_dir = self._project_dir
        shp_path = self._metadata.subbasin_shp_path
        land_cover_path = self._metadata.land_cover_raster_path
        restoration_path = self._metadata.restoration_raster_path

        self._scan_button.configure(state="disabled")
        self._compute_button.configure(state="disabled")
        self._compute_status_label.configure(
            text=self._config.text("restoration_inputs_tab.computing"), text_color=self._colors.get("text_secondary")
        )
        self._set_compute_log("")
        self._on_run_state_changed(True)

        def work(report_progress):
            def on_progress(done: int, total: int) -> None:
                report_progress(f"Computing crosstab... block {done}/{total}")

            return compute_restoration_area_csvs(
                project_dir, shp_path, land_cover_path, restoration_path, crosswalk, on_progress=on_progress
            )

        run_in_background(
            self, work, on_progress=self._set_compute_log, on_done=self._on_compute_done, on_error=self._on_compute_error
        )

    def _on_compute_done(self, result: RestorationComputeResult) -> None:
        self._compute_status_label.configure(
            text=self._config.text("restoration_inputs_tab.compute_summary").format(count=len(result.outputs)),
            text_color=self._colors.get("success") if result.outputs else self._colors.get("warning"),
        )
        lines: list[str] = []
        for output in result.outputs:
            lines.append(
                self._config.text("restoration_inputs_tab.compute_log_class_line").format(
                    value=output.restoration_value, name=output.restoration_name or "",
                    subbasins=output.subbasin_count, path=output.csv_path,
                )
            )
            for subbasin, excluded_ha in sorted(output.excluded_ha_by_subbasin.items()):
                lines.append(
                    self._config.text("restoration_inputs_tab.compute_log_excluded_line").format(
                        subbasin=subbasin, ha=excluded_ha
                    )
                )
        self._set_compute_log("\n".join(lines))
        self._open_folder_button.configure(state="normal" if result.outputs else "disabled")
        self._finish_compute()
        log_action(
            self._project_dir, "PROJECT",
            f"Computed restoration inputs: {len(result.outputs)} restoration class CSV(s) written.",
        )

    def _on_compute_error(self, error: Exception) -> None:
        self._compute_status_label.configure(
            text=self._config.text("restoration_inputs_tab.compute_error").format(error=str(error)),
            text_color=self._colors.get("error"),
        )
        self._finish_compute()

    def _finish_compute(self) -> None:
        self._scan_button.configure(state="normal")
        self._compute_button.configure(state="normal" if self._scan_result and self._scan_result.land_cover_codes else "disabled")
        self._on_run_state_changed(False)

    def _set_compute_log(self, text: str) -> None:
        self._compute_log.configure(state="normal")
        self._compute_log.delete("1.0", "end")
        self._compute_log.insert("1.0", text)
        self._compute_log.configure(state="disabled")

    def _on_open_folder_clicked(self) -> None:
        if self._project_dir is None:
            return
        os.startfile(tool_outputs_dir(self._project_dir) / "restoration_inputs")  # solo Windows: target de distribución del proyecto
