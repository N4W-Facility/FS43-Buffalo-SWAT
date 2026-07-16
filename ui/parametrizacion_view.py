from __future__ import annotations

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from config.settings import ConfigManager
from scenarios.draft import draft_csv_path, import_draft_csv, init_draft, read_draft, update_draft_value
from scenarios.models import Project
from ui.form_builder import build_wetland_form


class ParametrizacionView(ctk.CTkFrame):
    def __init__(self, master, config: ConfigManager, project: Project, scenario_name: str) -> None:
        super().__init__(master)
        self.config = config
        self.project = project
        self.scenario_name = scenario_name
        self.layout_def = config.load_layout("wetland_pond")

        self.draft_path = draft_csv_path(project, scenario_name)
        if not self.draft_path.exists():
            init_draft(project, scenario_name)
        self.draft = read_draft(self.draft_path)
        self.selected_id = self.draft.index[0]

        self._build_widgets()
        self._populate_list()
        self._select_row(self.selected_id)

    def _build_widgets(self) -> None:
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=8, pady=8)
        self.count_label = ctk.CTkLabel(top, text="")
        self.count_label.pack(side="left")
        ctk.CTkButton(
            top, text=self.config.text("wetland.import_csv"), command=self._on_import_csv
        ).pack(side="right")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=8, pady=8)

        self.list_frame = ctk.CTkScrollableFrame(body, width=280)
        self.list_frame.pack(side="left", fill="y", padx=(0, 8))

        self.form_frame = ctk.CTkFrame(body)
        self.form_frame.pack(side="left", fill="both", expand=True)

        self.error_label = ctk.CTkLabel(self, text="", text_color="#B3261E")
        self.error_label.pack(fill="x", padx=8)

    def _populate_list(self) -> None:
        for child in self.list_frame.winfo_children():
            child.destroy()
        with_wetland = int((self.draft["wet_fr"] > 0).sum())
        total = len(self.draft)
        self.count_label.configure(
            text=self.config.text("wetland.count").format(with_wetland=with_wetland, total=total)
        )
        for subbasin_id, row in self.draft.iterrows():
            marker = "●" if row["wet_fr"] > 0 else "○"
            text = f"{marker} Sub {subbasin_id} — WET_FR {row['wet_fr']:.3f}"
            ctk.CTkButton(
                self.list_frame,
                text=text,
                fg_color="transparent",
                anchor="w",
                command=lambda sid=subbasin_id: self._select_row(sid),
            ).pack(fill="x", pady=2)

    def _select_row(self, subbasin_id: int) -> None:
        self.selected_id = subbasin_id
        for child in self.form_frame.winfo_children():
            child.destroy()
        row = self.draft.loc[subbasin_id]
        initial_values = {field["id"]: row[field["id"]] for field in self.layout_def["fields"]}
        build_wetland_form(
            self.form_frame, self.config, self.layout_def, initial_values,
            on_commit=self._on_field_commit, on_error=self._on_field_error,
        )

    def _on_field_commit(self, field_id: str, value: float) -> None:
        self.draft = update_draft_value(self.draft_path, self.selected_id, field_id, value, self.layout_def)
        self.error_label.configure(text="")
        self._populate_list()

    def _on_field_error(self, field_id: str, message: str) -> None:
        self.error_label.configure(text=f"{field_id}: {message}")

    def _on_import_csv(self) -> None:
        path = filedialog.askopenfilename(parent=self)
        if not path:
            return
        try:
            self.draft = import_draft_csv(self.draft_path, Path(path), self.layout_def)
        except ValueError as exc:
            self.error_label.configure(text=self.config.text("wetland.import_error").format(error=str(exc)))
            return
        self.error_label.configure(text=self.config.text("wetland.import_success"))
        self._populate_list()
        self._select_row(self.selected_id)
