"""Ventana de síntesis que se abre sola al terminar cualquiera de los tres
flujos de Apply de la pestaña NbS (manual, por área, por área en todas las
subcuencas) -- pedido explícito del usuario, 2026-08-14: antes solo veía una
línea de conteo ("applied 45/50 HRU...") y tenía que abrir el CSV de
auditoría (scenarios.nbs_apply.write_apply_report_csv) para revisar HRU por
HRU si algo necesitaba corrección.

Puramente de presentación: no calcula nada, solo tabula
``NbSApplyReport.results`` (ya calculado por ``scenarios.nbs_apply.apply_nbs``
antes de que esta ventana se abra) en una tabla filtrable. Nunca toca disco
salvo "Open report folder" (abre la carpeta del CSV ya escrito, mismo
patrón ``os.startfile`` que el resto de la app).

Modal (``grab_set()``), mismo criterio que el resto de las ventanas Toplevel
de la app (ver ui/scenario_comparison_window.py) -- no hay un precedente de
ventana no-modal en el proyecto, y esto evita que el usuario dispare un
segundo Apply mientras revisa el resultado del anterior.
"""
from __future__ import annotations

import os
from pathlib import Path

import customtkinter as ctk

from config.settings import ConfigManager
from scenarios.nbs_apply import NbSApplyReport

from .widgets import build_scrollable_treeview, palette

_STATUS_APPLIED = "applied"
_TAG_ERROR = "error_row"


class NbSApplySummaryWindow(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        config: ConfigManager,
        *,
        report: NbSApplyReport,
        csv_path: Path,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self._config = config
        self._colors = palette(config)
        self._report = report
        self._csv_path = Path(csv_path)
        self._errors_only = False

        self.title(config.text("nbs_apply_summary_window.title").format(name=report.nbs_name))
        self.configure(fg_color=self._colors.get("window_bg"))
        self.transient(master)
        self.geometry("640x520")

        self._build()
        self._refresh_rows()
        self.grab_set()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 4))
        header.columnconfigure(0, weight=1)

        error_count = self._report.error_count
        counts_text = self._config.text("nbs_apply_summary_window.counts").format(
            applied=self._report.applied_count, total=len(self._report.results), errors=error_count,
        )
        self._counts_label = ctk.CTkLabel(
            header, text=counts_text,
            text_color=self._colors.get("success") if error_count == 0 else self._colors.get("warning"),
            font=ctk.CTkFont(size=14, weight="bold"), anchor="w",
        )
        self._counts_label.grid(row=0, column=0, sticky="w")

        report_row = ctk.CTkFrame(self, fg_color="transparent")
        report_row.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        report_row.columnconfigure(0, weight=1)
        ctk.CTkLabel(
            report_row,
            text=self._config.text("nbs_tab.apply_report_saved").format(path=str(self._csv_path)),
            text_color=self._colors.get("text_secondary"), anchor="w", justify="left",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            report_row, text=self._config.text("nbs_apply_summary_window.open_folder_button"),
            command=self._on_open_folder_clicked, width=140,
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))

        columns = ("subbasin", "hru", "status", "hru_fr", "message")
        self._tree, tree_container = build_scrollable_treeview(self, self._config, columns=columns, height=14)
        tree_container.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 8))
        self._tree.tag_configure(_TAG_ERROR, foreground=self._colors.get("error"))

        headings = (
            ("subbasin", "nbs_apply_summary_window.column_subbasin", 90),
            ("hru", "nbs_apply_summary_window.column_hru", 70),
            ("status", "nbs_apply_summary_window.column_status", 90),
            ("hru_fr", "nbs_apply_summary_window.column_hru_fr", 90),
            ("message", "nbs_apply_summary_window.column_message", 340),
        )
        for column, label_key, width in headings:
            self._tree.heading(column, text=self._config.text(label_key))
            self._tree.column(column, width=width, stretch=(column == "message"), anchor="w")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))
        footer.columnconfigure(0, weight=1)
        self._errors_only_check = ctk.CTkCheckBox(
            footer, text=self._config.text("nbs_apply_summary_window.errors_only_checkbox"),
            command=self._on_errors_only_toggled,
        )
        self._errors_only_check.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            footer, text=self._config.text("nbs_apply_summary_window.close_button"), command=self.destroy, width=100,
        ).grid(row=0, column=1, sticky="e")

    def _on_errors_only_toggled(self) -> None:
        self._errors_only = bool(self._errors_only_check.get())
        self._refresh_rows()

    def _refresh_rows(self) -> None:
        self._tree.delete(*self._tree.get_children())
        status_labels = {
            _STATUS_APPLIED: self._config.text("nbs_apply_summary_window.status_applied"),
        }
        for result in self._report.results:
            if self._errors_only and result.status == _STATUS_APPLIED:
                continue
            status_text = status_labels.get(result.status, self._config.text("nbs_apply_summary_window.status_error"))
            hru_fr_text = f"{result.hru_fr:.4f}" if result.hru_fr is not None else ""
            tags = () if result.status == _STATUS_APPLIED else (_TAG_ERROR,)
            self._tree.insert(
                "", "end",
                values=(result.subbasin, result.hru, status_text, hru_fr_text, result.message),
                tags=tags,
            )

    def _on_open_folder_clicked(self) -> None:
        os.startfile(self._csv_path.parent)  # solo Windows: target de distribución del proyecto
