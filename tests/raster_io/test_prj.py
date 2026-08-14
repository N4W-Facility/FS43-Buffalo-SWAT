from __future__ import annotations

from pathlib import Path

import pytest
from rasterio.crs import CRS

from raster_io.prj import PrjNotFoundError, read_shapefile_crs


def test_read_shapefile_crs_from_real_prj_wkt(tmp_path: Path) -> None:
    shp_path = tmp_path / "subs1.shp"
    (tmp_path / "subs1.prj").write_text(CRS.from_epsg(26917).to_wkt(), encoding="utf-8")

    crs = read_shapefile_crs(shp_path)

    assert crs.to_epsg() == 26917


def test_read_shapefile_crs_raises_without_prj(tmp_path: Path) -> None:
    shp_path = tmp_path / "subs1.shp"

    with pytest.raises(PrjNotFoundError):
        read_shapefile_crs(shp_path)
