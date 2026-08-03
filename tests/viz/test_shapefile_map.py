from viz.shapefile_map import build_shapefile_map_figure
from viz.shapefile_reader import ShapeRecord

_COLORS = dict(
    fill_color="#FFFFFF",
    highlight_fill_color="#2383E2",
    border_color="#E2E5EA",
    reach_color="#6B7280",
    highlight_reach_color="#D64545",
    background_color="#FFFFFF",
)

_SUBBASINS = [
    ShapeRecord(id_value=1, rings=[[(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)]]),
    ShapeRecord(id_value=2, rings=[[(1.0, 0.0), (1.0, 1.0), (2.0, 1.0), (2.0, 0.0)]]),
]
_REACHES = [
    ShapeRecord(id_value=1, rings=[[(0.0, 0.0), (1.0, 1.0)]]),
    ShapeRecord(id_value=2, rings=[[(1.0, 1.0), (2.0, 0.0)]]),
]


def test_build_shapefile_map_figure_draws_one_patch_per_subbasin_and_one_line_per_reach() -> None:
    figure = build_shapefile_map_figure(_SUBBASINS, _REACHES, highlighted_id=1, **_COLORS)

    ax = figure.axes[0]
    assert len(ax.patches) == 2
    assert len(ax.lines) == 2


def test_build_shapefile_map_figure_highlights_selected_id() -> None:
    figure = build_shapefile_map_figure(_SUBBASINS, _REACHES, highlighted_id=1, **_COLORS)

    ax = figure.axes[0]
    highlighted_patch = next(p for p in ax.patches if p.get_facecolor()[:3] != (1.0, 1.0, 1.0))
    assert highlighted_patch is not None


def test_build_shapefile_map_figure_handles_no_highlight() -> None:
    figure = build_shapefile_map_figure(_SUBBASINS, _REACHES, highlighted_id=None, **_COLORS)

    ax = figure.axes[0]
    assert len(ax.patches) == 2
