"""Barra de coberturas (% de área) por subcuenca o para toda la cuenca.

Función de render pura: recibe una Series ya calculada (land_use -> %) y
colores/labels ya resueltos, devuelve una Figure de matplotlib. Sin
CustomTkinter, sin ConfigManager, sin acceso a disco — ui/tab_summary.py
resuelve esos valores y embebe la Figure con FigureCanvasTkAgg.
"""
from __future__ import annotations

import pandas as pd
from matplotlib.figure import Figure

_FIGHEIGHT = 3.6
_MIN_FIGWIDTH = 6.4
_WIDTH_PER_CATEGORY = 0.42
_DPI = 100
_BAR_WIDTH = 0.6
# Umbral relativo (fracción de la barra más alta) bajo el cual una barra no
# lleva etiqueta de valor: con muchas coberturas reales (15+), etiquetar
# cada barra —incluidas las de 0.0%— satura el gráfico y las hace
# ilegibles (visto con datos reales del modelo Buffalo, 17 coberturas).
_LABEL_THRESHOLD_FRACTION = 0.08


def build_land_use_figure(
    percentages: pd.Series,
    *,
    bar_color: str,
    grid_color: str,
    text_color: str,
    muted_color: str,
    y_axis_label: str,
    title: str | None = None,
) -> Figure:
    """percentages: índice = código de cobertura, valores = % de área (0-100)."""
    labels = list(percentages.index)
    values = percentages.to_numpy()
    positions = range(len(labels))

    fig_width = max(_MIN_FIGWIDTH, _WIDTH_PER_CATEGORY * len(labels))
    figure = Figure(figsize=(fig_width, _FIGHEIGHT), dpi=_DPI)
    ax = figure.add_subplot(111)
    figure.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")

    ax.bar(positions, values, width=_BAR_WIDTH, color=bar_color, zorder=3)

    if title:
        ax.set_title(title, color=text_color, fontsize=10, loc="left", pad=10)

    ax.set_xticks(list(positions))
    ax.set_xticklabels(labels, color=text_color, fontsize=9, rotation=45, ha="right")
    ax.set_ylabel(y_axis_label, color=muted_color, fontsize=9)
    ax.tick_params(axis="y", colors=muted_color, labelsize=8)
    ax.tick_params(axis="x", length=0)

    ax.yaxis.grid(True, color=grid_color, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for spine_name in ("top", "right", "left"):
        ax.spines[spine_name].set_visible(False)
    ax.spines["bottom"].set_color(grid_color)

    max_value = float(values.max()) if len(values) else 0.0
    ax.set_ylim(0, max_value * 1.2 if max_value > 0 else 1.0)

    label_threshold = max_value * _LABEL_THRESHOLD_FRACTION
    for x, value in zip(positions, values):
        if value < label_threshold:
            continue
        ax.annotate(
            f"{value:.1f}%",
            xy=(x, value),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            fontsize=8,
            color=text_color,
        )

    figure.tight_layout()
    return figure
