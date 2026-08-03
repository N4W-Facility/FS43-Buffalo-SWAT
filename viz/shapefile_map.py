"""Mapa estático de subcuencas + reach, con la subcuenca/tramo seleccionado
resaltado. Función de render pura (recibe geometría ya leída por
viz.shapefile_reader y colores ya resueltos, devuelve una Figure de
matplotlib) -- igual convención que viz/land_use_chart.py: sin pyplot, sin
acceso a disco, sin CustomTkinter.

Sin interacción dinámica (pedido explícito del usuario): el resaltado solo
cambia cuando ui/tab_results.py vuelve a llamar a esta función tras un
cambio en el selector de reach/subcuenca -- no hay click-to-select sobre
el mapa en sí.
"""
from __future__ import annotations

from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon

from .shapefile_reader import ShapeRecord

_FIGSIZE = (4.2, 4.2)
_DPI = 100
_REACH_LINEWIDTH = 1.0
_REACH_HIGHLIGHT_LINEWIDTH = 2.4
_SUBBASIN_LINEWIDTH = 0.6


def build_shapefile_map_figure(
    subbasin_shapes: list[ShapeRecord],
    reach_shapes: list[ShapeRecord],
    highlighted_id: int | None,
    *,
    fill_color: str,
    highlight_fill_color: str,
    border_color: str,
    reach_color: str,
    highlight_reach_color: str,
    background_color: str,
    title: str | None = None,
) -> Figure:
    figure = Figure(figsize=_FIGSIZE, dpi=_DPI)
    ax = figure.add_subplot(111)
    figure.patch.set_facecolor(background_color)
    ax.set_facecolor(background_color)

    for shape in subbasin_shapes:
        is_highlighted = highlighted_id is not None and shape.id_value == highlighted_id
        for ring in shape.rings:
            polygon = Polygon(
                ring,
                closed=True,
                facecolor=highlight_fill_color if is_highlighted else fill_color,
                edgecolor=border_color,
                linewidth=_SUBBASIN_LINEWIDTH,
                zorder=2 if is_highlighted else 1,
            )
            ax.add_patch(polygon)

    for shape in reach_shapes:
        is_highlighted = highlighted_id is not None and shape.id_value == highlighted_id
        for ring in shape.rings:
            xs = [point[0] for point in ring]
            ys = [point[1] for point in ring]
            line = Line2D(
                xs,
                ys,
                color=highlight_reach_color if is_highlighted else reach_color,
                linewidth=_REACH_HIGHLIGHT_LINEWIDTH if is_highlighted else _REACH_LINEWIDTH,
                zorder=4 if is_highlighted else 3,
            )
            ax.add_line(line)

    if title:
        ax.set_title(title, color=border_color, fontsize=10, loc="left", pad=8)

    ax.set_aspect("equal", adjustable="datalim")
    ax.autoscale_view()
    ax.set_axis_off()

    figure.tight_layout()
    return figure
