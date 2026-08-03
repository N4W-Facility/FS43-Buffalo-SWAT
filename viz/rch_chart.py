"""Serie de tiempo de una variable de output.rch para un reach. Función de
render pura: recibe una Series ya filtrada (índice = date, valores = la
variable elegida) y colores ya resueltos, devuelve una Figure de
matplotlib -- misma convención que viz/land_use_chart.py (sin pyplot, sin
acceso a disco, sin CustomTkinter).
"""
from __future__ import annotations

import pandas as pd
from matplotlib.figure import Figure

_FIGSIZE = (7.4, 3.6)
_DPI = 100


def build_rch_timeseries_figure(
    series: pd.Series,
    *,
    line_color: str,
    grid_color: str,
    text_color: str,
    muted_color: str,
    y_axis_label: str,
    title: str | None = None,
) -> Figure:
    """series: índice = date (datetime-like), valores = la variable elegida, ya ordenada por fecha."""
    figure = Figure(figsize=_FIGSIZE, dpi=_DPI)
    ax = figure.add_subplot(111)
    figure.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")

    ax.plot(series.index, series.to_numpy(), color=line_color, linewidth=1.6)

    if title:
        ax.set_title(title, color=text_color, fontsize=10, loc="left", pad=10)

    ax.set_ylabel(y_axis_label, color=muted_color, fontsize=9)
    ax.tick_params(axis="x", colors=muted_color, labelsize=8, rotation=30)
    ax.tick_params(axis="y", colors=muted_color, labelsize=8)

    ax.yaxis.grid(True, color=grid_color, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for spine_name in ("top", "right", "left"):
        ax.spines[spine_name].set_visible(False)
    ax.spines["bottom"].set_color(grid_color)

    figure.tight_layout()
    return figure
