"""Pestaña Wetlands (.pnd): tabla compilada de solo lectura, filas =
parámetro de humedal, columnas = subcuenca, para ver el panorama general
de un vistazo. El encabezado de cada columna es clickeable y abre
WetlandEditorWindow preseleccionada en esa subcuenca; al cerrarse esa
ventana, la tabla se refresca desde los .pnd reales.

Deshabilitada (vía TabBar.set_enabled) hasta que haya un proyecto abierto.
"""
from __future__ import annotations

from pathlib import Path
from tkinter import ttk

import customtkinter as ctk

from config.settings import ConfigManager
from scenarios.wetland_draft import build_wetland_draft
from swat_io.pnd_parser import _FIELD_TO_CODE

from .wetland_editor_window import WetlandEditorWindow
from .widgets import palette

_ROW_HEIGHT = 26
_ACRONYM_COLUMN_WIDTH = 130
_SUBBASIN_COLUMN_WIDTH = 90


class WetlandsTab(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, config: ConfigManager, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._config = config
        self._colors = palette(config)
        self._project_dir: Path | None = None

        self._disabled_state = self._build_disabled_state()
        self._enabled_state = self._build_enabled_state()
        self._disabled_state.pack(fill="both", expand=True)

    # -- construcción -------------------------------------------------------

    def _build_disabled_state(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        hint = ctk.CTkLabel(
            frame,
            text=self._config.text("summary.disabled_hint"),
            text_color=self._colors.get("text_secondary"),
        )
        hint.place(relx=0.5, rely=0.4, anchor="center")
        return frame

    def _build_enabled_state(self) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.columnconfigure(0, weight=1)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            header,
            text=self._config.text("wetlands_tab.title"),
            text_color=self._colors.get("accent"),
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        )
        title.grid(row=0, column=0, sticky="w")

        self._subbasin_selector = ctk.CTkOptionMenu(header, values=[])
        self._subbasin_selector.grid(row=0, column=1, sticky="e", padx=(0, 8))

        self._edit_button = ctk.CTkButton(
            header, text=self._config.text("action.edit"), command=self._on_edit_clicked
        )
        self._edit_button.grid(row=0, column=2, sticky="e")

        self._style_ttk()

        table_container = ctk.CTkFrame(frame, fg_color="transparent")
        table_container.grid(row=1, column=0, sticky="nsew")
        frame.rowconfigure(1, weight=1)
        table_container.rowconfigure(0, weight=1)
        table_container.columnconfigure(0, weight=1)

        self._tree = ttk.Treeview(table_container, style="Wetlands.Treeview", show="tree headings")
        self._tree.grid(row=0, column=0, sticky="nsew")

        v_scroll = ttk.Scrollbar(
            table_container, orient="vertical", style="Wetlands.Vertical.TScrollbar", command=self._tree.yview
        )
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll = ttk.Scrollbar(
            table_container, orient="horizontal", style="Wetlands.Horizontal.TScrollbar", command=self._tree.xview
        )
        h_scroll.grid(row=1, column=0, sticky="ew")
        self._tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        return frame

    def _style_ttk(self) -> None:
        """El look nativo de ttk (tema "default") dibuja las scrollbars con
        relieve 3D y flechas — no sigue la estética plana/moderna del resto
        de la app. "clam" es el tema ttk más reestilizable (permite quitar
        flechas y bordes), y coloreamos con los mismos tonos que ya usa la
        CTkScrollbar nativa en otras pestañas (idle=border, hover=accent)
        para que se vea consistente."""
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(
            "Wetlands.Treeview",
            background=self._colors.get("surface"),
            fieldbackground=self._colors.get("surface"),
            foreground=self._colors.get("text_primary"),
            rowheight=_ROW_HEIGHT,
            borderwidth=0,
        )
        style.configure(
            "Wetlands.Treeview.Heading",
            background=self._colors.get("window_bg"),
            foreground=self._colors.get("text_primary"),
            relief="flat",
            borderwidth=0,
        )
        style.map("Wetlands.Treeview.Heading", background=[("active", self._colors.get("window_bg"))])

        for orientation, layout_name in (("Vertical", "ns"), ("Horizontal", "ew")):
            style_name = f"Wetlands.{orientation}.TScrollbar"
            style.layout(
                style_name,
                [
                    (
                        f"{orientation}.Scrollbar.trough",
                        {
                            "children": [
                                (f"{orientation}.Scrollbar.thumb", {"expand": 1, "sticky": layout_name})
                            ],
                            "sticky": layout_name,
                        },
                    )
                ],
            )
            style.configure(
                style_name,
                background=self._colors.get("border"),
                troughcolor=self._colors.get("window_bg"),
                borderwidth=0,
                relief="flat",
            )
            style.map(style_name, background=[("active", self._colors.get("accent"))])

    # -- estado del proyecto -------------------------------------------------

    def set_project(self, project_dir: Path) -> None:
        self._project_dir = project_dir
        self._enabled_state.pack(fill="both", expand=True)
        self._disabled_state.pack_forget()
        self._refresh_table()

    def _refresh_table(self) -> None:
        if self._project_dir is None:
            return
        draft = build_wetland_draft(self._project_dir / "TxtInOut")  # index=subbasin_id, columns=field_id
        subbasin_ids = list(draft.index)

        subbasin_labels = [str(s) for s in subbasin_ids]
        self._subbasin_selector.configure(values=subbasin_labels)
        if subbasin_labels:
            self._subbasin_selector.set(subbasin_labels[0])

        self._tree.delete(*self._tree.get_children())
        self._tree["columns"] = subbasin_labels

        self._tree.heading("#0", text="")
        self._tree.column("#0", width=_ACRONYM_COLUMN_WIDTH, stretch=False, anchor="w")

        for subbasin_id in subbasin_ids:
            column_id = str(subbasin_id)
            self._tree.heading(column_id, text=column_id, command=lambda s=subbasin_id: self._open_editor(s))
            self._tree.column(column_id, width=_SUBBASIN_COLUMN_WIDTH, stretch=False, anchor="e")

        for field_id, code in _FIELD_TO_CODE.items():
            values = [f"{draft.loc[s, field_id]:.3f}" for s in subbasin_ids]
            self._tree.insert("", "end", iid=field_id, text=code, values=values)

    def _on_edit_clicked(self) -> None:
        selected = self._subbasin_selector.get()
        if not selected:
            return
        self._open_editor(int(selected))

    def _open_editor(self, subbasin_id: int) -> None:
        if self._project_dir is None:
            return
        editor = WetlandEditorWindow(self, self._config, self._project_dir, initial_subbasin=subbasin_id)
        self.wait_window(editor)
        self._refresh_table()
