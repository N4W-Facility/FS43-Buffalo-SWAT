import pandas as pd

from viz.land_use_chart import build_land_use_figure

_COLORS = dict(
    bar_color="#2383E2",
    grid_color="#E2E5EA",
    text_color="#1F2430",
    muted_color="#6B7280",
    y_axis_label="% of area",
)


def test_build_land_use_figure_has_one_bar_per_category() -> None:
    percentages = pd.Series({"AGRL": 60.0, "FRST": 25.0, "PAST": 15.0})

    figure = build_land_use_figure(percentages, **_COLORS)

    ax = figure.axes[0]
    assert len(ax.patches) == 3
    assert [tick.get_text() for tick in ax.get_xticklabels()] == ["AGRL", "FRST", "PAST"]


def test_build_land_use_figure_sets_title_when_given() -> None:
    percentages = pd.Series({"AGRL": 60.0, "FRST": 40.0})

    figure = build_land_use_figure(percentages, title="Subbasin 3 — 5.0 km²", **_COLORS)

    assert figure.axes[0].get_title(loc="left") == "Subbasin 3 — 5.0 km²"


def test_build_land_use_figure_handles_empty_series() -> None:
    percentages = pd.Series(dtype=float)

    figure = build_land_use_figure(percentages, **_COLORS)

    assert len(figure.axes[0].patches) == 0
