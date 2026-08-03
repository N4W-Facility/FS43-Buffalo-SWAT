import pandas as pd

from viz.rch_chart import build_rch_timeseries_figure

_COLORS = dict(
    line_color="#2383E2",
    grid_color="#E2E5EA",
    text_color="#1F2430",
    muted_color="#6B7280",
    y_axis_label="FLOW_OUT",
)


def test_build_rch_timeseries_figure_plots_one_line() -> None:
    series = pd.Series(
        [0.32, 0.33, 0.37], index=pd.to_datetime(["2017-01-01", "2018-01-01", "2019-01-01"])
    )

    figure = build_rch_timeseries_figure(series, **_COLORS)

    ax = figure.axes[0]
    assert len(ax.lines) == 1
    assert list(ax.lines[0].get_ydata()) == [0.32, 0.33, 0.37]


def test_build_rch_timeseries_figure_sets_title_when_given() -> None:
    series = pd.Series([1.0], index=pd.to_datetime(["2017-01-01"]))

    figure = build_rch_timeseries_figure(series, title="Reach 1 — FLOW_OUT", **_COLORS)

    assert figure.axes[0].get_title(loc="left") == "Reach 1 — FLOW_OUT"


def test_build_rch_timeseries_figure_handles_empty_series() -> None:
    series = pd.Series(dtype=float)

    figure = build_rch_timeseries_figure(series, **_COLORS)

    assert len(figure.axes[0].lines) == 1
    assert len(figure.axes[0].lines[0].get_ydata()) == 0
