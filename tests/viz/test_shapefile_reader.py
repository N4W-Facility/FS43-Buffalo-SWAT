from pathlib import Path

import pytest
import shapefile

from viz.shapefile_reader import ShapefileReadError, read_reach_shapes, read_subbasin_shapes


def _write_subbasin_shp(path: Path) -> None:
    with shapefile.Writer(str(path), shapeType=shapefile.POLYGON) as writer:
        writer.field("GRIDCODE", "N")
        writer.poly([[(0, 0), (0, 1), (1, 1), (1, 0), (0, 0)]])
        writer.record(GRIDCODE=1)
        writer.poly([[(1, 0), (1, 1), (2, 1), (2, 0), (1, 0)]])
        writer.record(GRIDCODE=2)


def _write_reach_shp(path: Path) -> None:
    with shapefile.Writer(str(path), shapeType=shapefile.POLYLINE) as writer:
        writer.field("ARCID", "N")
        writer.line([[(0, 0), (1, 1)]])
        writer.record(ARCID=1)
        writer.line([[(1, 1), (2, 0)]])
        writer.record(ARCID=2)


def test_read_subbasin_shapes_returns_id_and_rings(tmp_path: Path) -> None:
    shp_path = tmp_path / "subs1.shp"
    _write_subbasin_shp(shp_path)

    shapes = read_subbasin_shapes(shp_path)

    assert [s.id_value for s in shapes] == [1, 2]
    assert shapes[0].rings[0][0] == (0.0, 0.0)


def test_read_reach_shapes_returns_id_and_rings(tmp_path: Path) -> None:
    shp_path = tmp_path / "riv1.shp"
    _write_reach_shp(shp_path)

    shapes = read_reach_shapes(shp_path)

    assert [s.id_value for s in shapes] == [1, 2]
    assert shapes[0].rings[0] == [(0.0, 0.0), (1.0, 1.0)]


def test_read_subbasin_shapes_raises_when_file_missing(tmp_path: Path) -> None:
    with pytest.raises(ShapefileReadError):
        read_subbasin_shapes(tmp_path / "missing.shp")


def test_read_subbasin_shapes_raises_when_id_field_missing(tmp_path: Path) -> None:
    shp_path = tmp_path / "subs1.shp"
    with shapefile.Writer(str(shp_path), shapeType=shapefile.POLYGON) as writer:
        writer.field("OTHER", "N")
        writer.poly([[(0, 0), (0, 1), (1, 1), (1, 0), (0, 0)]])
        writer.record(OTHER=1)

    with pytest.raises(ShapefileReadError):
        read_subbasin_shapes(shp_path)
