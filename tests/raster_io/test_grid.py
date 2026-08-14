from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin

from raster_io.grid import NoOverlapError, compute_target_grid

_CRS = CRS.from_epsg(32617)


def _write_raster(path: Path, *, origin, pixel_size: float, width: int, height: int) -> None:
    transform = from_origin(origin[0], origin[1], pixel_size, pixel_size)
    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=1, dtype="uint8", crs=_CRS, transform=transform,
    ) as dst:
        dst.write(np.zeros((height, width), dtype="uint8"), 1)


def test_target_resolution_is_the_finer_of_the_two_rasters(tmp_path: Path) -> None:
    coarse = tmp_path / "coarse_30m.tif"
    fine = tmp_path / "fine_10m.tif"
    # Ambos cubren la misma extensión real (300m x 300m) a distinta resolución.
    _write_raster(coarse, origin=(500000, 4500300), pixel_size=30.0, width=10, height=10)
    _write_raster(fine, origin=(500000, 4500300), pixel_size=10.0, width=30, height=30)

    shapefile_bbox = (500000.0, 4500000.0, 500300.0, 4500300.0)
    grid = compute_target_grid(shapefile_bbox, _CRS, [coarse, fine])

    assert grid.pixel_size == pytest.approx(10.0)
    assert grid.width == 30
    assert grid.height == 30


def test_target_grid_is_the_intersection_of_all_bounds(tmp_path: Path) -> None:
    raster_path = tmp_path / "raster.tif"
    # Raster cubre x en [500000, 500200); el shapefile solo llega hasta x=500100.
    _write_raster(raster_path, origin=(500000, 4500100), pixel_size=10.0, width=20, height=10)
    shapefile_bbox = (500000.0, 4500000.0, 500100.0, 4500100.0)

    grid = compute_target_grid(shapefile_bbox, _CRS, [raster_path])

    assert grid.width == 10  # acotado por el shapefile, no por el raster completo
    assert grid.height == 10


def test_no_overlap_raises(tmp_path: Path) -> None:
    raster_path = tmp_path / "far_away.tif"
    _write_raster(raster_path, origin=(9000000, 4500100), pixel_size=10.0, width=10, height=10)
    shapefile_bbox = (500000.0, 4500000.0, 500100.0, 4500100.0)

    with pytest.raises(NoOverlapError):
        compute_target_grid(shapefile_bbox, _CRS, [raster_path])
