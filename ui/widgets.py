"""Piezas de UI compartidas entre pestañas.

Cero literales: todo texto viene de config.text(key), todo color de
config.theme["AppPalette"]. Ningún widget de este módulo sabe qué pestaña
lo usa.
"""
from __future__ import annotations

from tkinter import ttk

import customtkinter as ctk

from config.settings import ConfigManager

_PLACEHOLDER_VALUE = "—"  # em dash: valor aún no calculado
_COMBOBOX_STYLE_NAME = "Swat.TCombobox"


def _patch_ctk_scrollable_frame_wheel_crash() -> None:
    """Workaround de un bug real de customtkinter (visto contra la app real,
    2026-08-13): ``CTkScrollableFrame._mouse_wheel_all`` pasa ``event.widget``
    directo a ``_check_if_valid_scroll``, que asume que siempre es un objeto
    tkinter con ``.master``. Tkinter en cambio entrega un string cuando el
    widget bajo el mouse no tiene wrapper Python -- pasa con sub-widgets
    internos de ``ttk.Combobox``/``ttk.Treeview`` y con el canvas interno de
    ``FigureCanvasTkAgg`` (matplotlib), todos presentes en esta app dentro
    de pestañas con ``CTkScrollableFrame`` (ver CLAUDE.md, sección sobre la
    barra de pestañas). Sin este parche, mover la rueda del mouse sobre
    esos widgets tira ``AttributeError: 'str' object has no attribute
    'master'`` en cada evento de scroll. Se parcha en tiempo de ejecución
    (no se edita site-packages) para que el fix sobreviva a reinstalar
    dependencias -- mismo motivo por el que este módulo ya trae otro
    workaround de CTk (ver ``bind_responsive_wraplength``). Idempotente por
    construcción: el módulo solo se importa una vez por proceso."""
    original = ctk.CTkScrollableFrame._check_if_valid_scroll

    def _check_if_valid_scroll_safe(self, widget):
        if isinstance(widget, str):
            try:
                widget = self._parent_canvas.nametowidget(widget)
            except Exception:  # noqa: BLE001 - resolver el nombre puede fallar de varias formas (TclError, KeyError); cualquier falla acá significa "no es un scroll válido"
                return False
        return original(self, widget)

    ctk.CTkScrollableFrame._check_if_valid_scroll = _check_if_valid_scroll_safe


_patch_ctk_scrollable_frame_wheel_crash()


def palette(config: ConfigManager) -> dict:
    return config.theme.get("AppPalette", {})


def bind_responsive_wraplength(label: ctk.CTkLabel) -> None:
    """Reajusta wraplength al ancho real del contenedor del label en cada
    resize, en vez de un valor fijo en pixeles -- para que párrafos de
    ayuda/estado se reajusten con el ancho de la ventana en vez de
    desbordar en pantallas chicas o dejar espacio vacío sin usar en
    pantallas grandes.

    Se engancha a label.master (no al label mismo): CTkLabel.bind()
    redirige el evento a sus widgets internos (canvas + tk.Label), cuyo
    tamaño cambia como consecuencia de wraplength -- enganchado ahí se
    arma un bucle de retroalimentación (Configure -> cambia wraplength ->
    cambia tamaño interno -> nuevo Configure) que congela la ventana
    apenas se dibuja. El contenedor (la fila del grid con
    columnconfigure(weight=1)) cambia de ancho solo por el layout externo
    (redimensionar la ventana), nunca por el contenido del label, así que
    no hay ciclo.

    ``add="+"`` (2026-08-11, pestaña NbS): varios labels pueden compartir
    el mismo ``master`` (ej. una columna de campos dentro de un mismo paso
    del wizard) -- sin ``add="+"``, cada llamada a ``bind()`` sobre el
    mismo widget+evento reemplaza la anterior en vez de acumularse, y solo
    el último label enganchado quedaría responsive."""
    label.master.bind(
        "<Configure>", lambda event: label.configure(wraplength=max(event.width - 4, 1)), add="+"
    )


def style_combobox(config: ConfigManager) -> str:
    """Configura (si hace falta) y devuelve el nombre de estilo ttk
    compartido para los selectores largos de la app (subcuenca, HRU).

    ttk.Combobox en vez de CTkOptionMenu: el desplegable de CTkOptionMenu
    no tiene alto máximo ni scroll -- con muchos ítems (subcuencas, HRU)
    crece sin límite y se sale de la pantalla. El desplegable de
    ttk.Combobox usa el control nativo del SO, que scrollea solo. Mismo
    motivo por el que las tablas usan ttk.Treeview en vez de un widget CTk.
    Idempotente: llamarla varias veces desde distintos widgets solo
    reconfigura el mismo estilo compartido, no crea uno nuevo por widget.

    Dos capas a pelar del look "Windows 98" por defecto de clam:
    1. El campo cerrado: clam dibuja un bisel de 3 tonos (lightcolor
       arriba/izq, darkcolor abajo/der) aunque no se pida relieve
       explícito -- si no se igualan light/dark al fondo, se ve un borde
       hundido tipo Win95/98 sin importar qué color de borde se use.
    2. El desplegable abierto: la lista de opciones NO es un widget ttk,
       es un tk.Listbox plano -- style.configure no la toca en absoluto.
       Sin esto se queda con los grises/borde hundido nativos del SO,
       que es la parte más "retro" del combo y la que más contrasta con
       el resto de la UI (CTk plana, sin biseles).
    """
    colors = palette(config)
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(
        _COMBOBOX_STYLE_NAME,
        relief="flat",
        borderwidth=1,
        padding=(8, 6),
        arrowsize=12,
        fieldbackground=colors.get("surface"),
        background=colors.get("surface"),
        foreground=colors.get("text_primary"),
        arrowcolor=colors.get("text_secondary"),
        bordercolor=colors.get("border"),
        lightcolor=colors.get("surface"),
        darkcolor=colors.get("surface"),
    )
    style.map(
        _COMBOBOX_STYLE_NAME,
        fieldbackground=[("readonly", colors.get("surface")), ("disabled", colors.get("window_bg"))],
        foreground=[("disabled", colors.get("disabled"))],
        background=[("readonly", colors.get("surface")), ("active", colors.get("window_bg"))],
        bordercolor=[("focus", colors.get("accent")), ("hover", colors.get("accent"))],
        arrowcolor=[("disabled", colors.get("disabled")), ("hover", colors.get("accent"))],
        lightcolor=[("focus", colors.get("surface"))],
        darkcolor=[("focus", colors.get("surface"))],
    )

    root = style.master
    root.option_add("*TCombobox*Listbox.background", colors.get("surface"))
    root.option_add("*TCombobox*Listbox.foreground", colors.get("text_primary"))
    root.option_add("*TCombobox*Listbox.selectBackground", colors.get("accent"))
    root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
    root.option_add("*TCombobox*Listbox.borderWidth", 0)
    root.option_add("*TCombobox*Listbox.relief", "flat")
    root.option_add("*TCombobox*Listbox.activeStyle", "none")

    return _COMBOBOX_STYLE_NAME


_TREEVIEW_ROW_HEIGHT = 26


def style_treeview(config: ConfigManager, *, style_prefix: str = "Swat") -> tuple[str, str, str]:
    """Configura (si hace falta) y devuelve (estilo_treeview,
    estilo_scrollbar_vertical, estilo_scrollbar_horizontal) para tablas
    ttk.Treeview compartidas -- extraído (2026-08-11, pestaña NbS) del
    ``_style_ttk`` que HRUsTab y WetlandsTab ya traían cada una por su
    lado, para que las tablas nuevas (NbS) no repitan la misma
    configuración clam sin bisel una tercera vez. Idempotente igual que
    style_combobox: llamarla varias veces con el mismo style_prefix solo
    reconfigura el mismo estilo compartido.

    Nota para las tablas existentes de HRUs/Wetlands: siguen con su propio
    ``_style_ttk`` (``HRU.Treeview`` / equivalente en Wetlands) -- no se
    tocaron para no arriesgar una tabla ya probada; esta función es para
    tablas nuevas."""
    colors = palette(config)
    style = ttk.Style()
    style.theme_use("clam")

    treeview_style = f"{style_prefix}.Treeview"
    style.configure(
        treeview_style,
        background=colors.get("surface"),
        fieldbackground=colors.get("surface"),
        foreground=colors.get("text_primary"),
        rowheight=_TREEVIEW_ROW_HEIGHT,
        borderwidth=0,
    )
    style.configure(
        f"{treeview_style}.Heading",
        background=colors.get("window_bg"),
        foreground=colors.get("text_primary"),
        relief="flat",
        borderwidth=0,
    )
    style.map(f"{treeview_style}.Heading", background=[("active", colors.get("window_bg"))])

    scrollbar_styles: list[str] = []
    for orientation, layout_sticky in (("Vertical", "ns"), ("Horizontal", "ew")):
        scrollbar_style = f"{style_prefix}.{orientation}.TScrollbar"
        style.layout(
            scrollbar_style,
            [
                (
                    f"{orientation}.Scrollbar.trough",
                    {
                        "children": [(f"{orientation}.Scrollbar.thumb", {"expand": 1, "sticky": layout_sticky})],
                        "sticky": layout_sticky,
                    },
                )
            ],
        )
        style.configure(
            scrollbar_style,
            background=colors.get("border"),
            troughcolor=colors.get("window_bg"),
            borderwidth=0,
            relief="flat",
        )
        style.map(scrollbar_style, background=[("active", colors.get("accent"))])
        scrollbar_styles.append(scrollbar_style)

    return treeview_style, scrollbar_styles[0], scrollbar_styles[1]


def build_scrollable_treeview(
    parent: ctk.CTkBaseClass,
    config: ConfigManager,
    *,
    columns: tuple[str, ...],
    height: int = 8,
    style_prefix: str = "Swat",
) -> tuple[ttk.Treeview, ctk.CTkFrame]:
    """Arma un ttk.Treeview con scroll vertical Y horizontal ya cableado.

    CTk no scrollea un ttk.Treeview por su cuenta, y sin scroll horizontal
    una tabla con celdas de texto largo (ej. el resumen de una operación
    de manejo) queda con contenido cortado y sin forma de verlo completo
    (bug real reportado por el usuario en la pestaña NbS, 2026-08-11). El
    llamador debe fijar ``stretch=False`` en cada columna
    (``tree.column(col, width=..., stretch=False)``) para que el ancho
    total pueda exceder el área visible y el scroll horizontal tenga algo
    que hacer -- con el ``stretch=True`` por defecto de ttk, las columnas
    siempre se encogen para caber, y el scroll horizontal queda inútil.

    Devuelve ``(tree, container)``: el llamador hace
    ``container.grid(...)`` (nunca ``tree.grid`` directo) y configura
    columnas/headings sobre ``tree``.
    """
    treeview_style, v_style, h_style = style_treeview(config, style_prefix=style_prefix)

    container = ctk.CTkFrame(parent, fg_color="transparent")
    container.rowconfigure(0, weight=1)
    container.columnconfigure(0, weight=1)

    tree = ttk.Treeview(container, style=treeview_style, columns=columns, show="headings", height=height)
    tree.grid(row=0, column=0, sticky="nsew")

    v_scroll = ttk.Scrollbar(container, orient="vertical", style=v_style, command=tree.yview)
    v_scroll.grid(row=0, column=1, sticky="ns")
    h_scroll = ttk.Scrollbar(container, orient="horizontal", style=h_style, command=tree.xview)
    h_scroll.grid(row=1, column=0, sticky="ew")
    tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

    return tree, container


class ReadOnlyField(ctk.CTkFrame):
    """Label secundario en mayúscula + valor en texto primario debajo."""

    def __init__(self, master: ctk.CTkBaseClass, config: ConfigManager, label_key: str, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        colors = palette(config)

        self._label = ctk.CTkLabel(
            self,
            text=config.text(label_key).upper(),
            text_color=colors.get("text_secondary"),
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        )
        self._label.pack(fill="x")

        self._value = ctk.CTkLabel(
            self,
            text="",
            text_color=colors.get("text_primary"),
            anchor="w",
            justify="left",
        )
        self._value.pack(fill="x", pady=(2, 0))

    def set_value(self, value: str) -> None:
        self._value.configure(text=value)


class SectionHeader(ctk.CTkFrame):
    """Título de grupo a la izquierda + timestamp secundario a la derecha."""

    def __init__(self, master: ctk.CTkBaseClass, config: ConfigManager, title_key: str, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        colors = palette(config)
        self.columnconfigure(0, weight=1)

        self._title = ctk.CTkLabel(
            self,
            text=config.text(title_key),
            text_color=colors.get("text_primary"),
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        )
        self._title.grid(row=0, column=0, sticky="w")

        self._timestamp = ctk.CTkLabel(
            self,
            text="",
            text_color=colors.get("text_secondary"),
            anchor="e",
        )
        self._timestamp.grid(row=0, column=1, sticky="e")

    def set_timestamp(self, text: str) -> None:
        self._timestamp.configure(text=text)


class StatCard(ctk.CTkFrame):
    """Tarjeta: valor grande arriba, label secundario debajo."""

    def __init__(self, master: ctk.CTkBaseClass, config: ConfigManager, label_key: str, **kwargs) -> None:
        kwargs.setdefault("corner_radius", 10)
        super().__init__(master, **kwargs)
        colors = palette(config)

        self._value = ctk.CTkLabel(
            self,
            text=_PLACEHOLDER_VALUE,
            text_color=colors.get("text_primary"),
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        self._value.pack(padx=16, pady=(14, 0))

        self._label = ctk.CTkLabel(
            self,
            text=config.text(label_key),
            text_color=colors.get("text_secondary"),
            font=ctk.CTkFont(size=11),
        )
        self._label.pack(padx=16, pady=(2, 14))

    def set_value(self, text: str | None) -> None:
        self._value.configure(text=text if text else _PLACEHOLDER_VALUE)
