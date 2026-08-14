"""Prueba de integración de raster_io completo (prj + grid + subbasin_zones
+ crosstab) sobre una fixture chica y determinista, autocontenida en este
archivo -- tests/ no es un paquete (sin __init__.py), así que un import
cruzado entre archivos de test dependería del orden de inserción en
sys.path de pytest, más frágil que repetir este helper chico (mismo
criterio ya documentado en tests/ui/test_scenario_comparison_window_smoke.py).

Layout de la fixture (subcuenca 1 = izquierda, subcuenca 2 = derecha):

    extensión: x en [500000, 500200), y en [4500000, 4500100), EPSG:32617
    2 subcuencas (GRIDCODE 1 y 2), cada una de 100m x 100m
    cobertura y restauración: mismos 10m de píxel (20 x 10 px), sin
    reproyección real de por medio (eso ya se validó contra rasters
    reales); acá se aisla la lógica de cruce/exclusión.

    cobertura (por columna, uniforme en todas las filas):
        columnas  0- 9 (subcuenca 1): código 1
        columnas 10-14 (subcuenca 2): código 2
        columnas 15-19 (subcuenca 2): código 99 (deliberadamente sin cruce)

    restauración: clase 1 en todo el raster, salvo columnas 0-1 (dentro de
    subcuenca 1) en 0 (background) -- para probar que el background se
    excluye del cruce.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
import shapefile
from rasterio.crs import CRS
from rasterio.transform import from_origin

from raster_io.crosstab import compute_crosstab
from raster_io.grid import compute_target_grid
from raster_io.prj import read_shapefile_crs
from raster_io.subbasin_zones import shapefile_bbox, subbasin_geometries

_CRS = CRS.from_epsg(32617)
_PIXEL_SIZE = 10.0
_WIDTH, _HEIGHT = 20, 10
PIXEL_AREA_HA = (_PIXEL_SIZE**2) / 10000


def _write_fixture_shapefile(path: Path) -> Path:
    writer = shapefile.Writer(str(path), shapeType=shapefile.POLYGON)
    writer.field("GRIDCODE", "N", 10)
    writer.poly([[(500000.0, 4500000.0), (500100.0, 4500000.0), (500100.0, 4500100.0), (500000.0, 4500100.0), (500000.0, 4500000.0)]])
    writer.record(GRIDCODE=1)
    writer.poly([[(500100.0, 4500000.0), (500200.0, 4500000.0), (500200.0, 4500100.0), (500100.0, 4500100.0), (500100.0, 4500000.0)]])
    writer.record(GRIDCODE=2)
    writer.close()
    path.with_suffix(".prj").write_text(_CRS.to_wkt(), encoding="utf-8")
    return path


def _write_raster(path: Path, data: np.ndarray) -> Path:
    transform = from_origin(500000.0, 4500100.0, _PIXEL_SIZE, _PIXEL_SIZE)
    with rasterio.open(
        path, "w", driver="GTiff", height=data.shape[0], width=data.shape[1], count=1,
        dtype=data.dtype, crs=_CRS, transform=transform,
    ) as dst:
        dst.write(data, 1)
    return path


def _write_fixture_land_cover_raster(path: Path) -> Path:
    data = np.zeros((_HEIGHT, _WIDTH), dtype="uint8")
    data[:, 0:10] = 1
    data[:, 10:15] = 2
    data[:, 15:20] = 99
    return _write_raster(path, data)


def _write_fixture_restoration_raster(path: Path) -> Path:
    data = np.ones((_HEIGHT, _WIDTH), dtype="uint8")
    data[:, 0:2] = 0
    return _write_raster(path, data)


def build_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    shp_path = _write_fixture_shapefile(tmp_path / "subs.shp")
    land_cover_path = _write_fixture_land_cover_raster(tmp_path / "land_cover.tif")
    restoration_path = _write_fixture_restoration_raster(tmp_path / "restoration.tif")
    return shp_path, land_cover_path, restoration_path


def test_crosstab_counts_match_hand_computed_areas(tmp_path: Path) -> None:
    shp_path, land_cover_path, restoration_path = build_fixture(tmp_path)

    crs = read_shapefile_crs(shp_path)
    bbox = shapefile_bbox(shp_path)
    grid = compute_target_grid(bbox, crs, [land_cover_path, restoration_path])
    geometries = subbasin_geometries(shp_path)

    # block_size chico a propósito, para forzar varios bloques sobre una
    # grilla de 20x10 y ejercitar de verdad el loop de bloques.
    result = compute_crosstab(land_cover_path, restoration_path, geometries, grid, block_size=4)

    assert result.pixel_area_ha == PIXEL_AREA_HA

    # Subcuenca 1: columnas 2-9 (8 cols, las 0-1 son background) x 10 filas
    # = 80 px, todas código 1.
    assert result.counts[(1, 1, 1)] == 80
    assert (1, 1, 99) not in result.counts  # sin código 99 en subcuenca 1

    # Subcuenca 2: columnas 10-14 (código 2) y 15-19 (código 99), sin
    # background acá, 10 filas cada una -> 50 px cada código.
    assert result.counts[(2, 1, 2)] == 50
    assert result.counts[(2, 1, 99)] == 50

    # El background (restauración=0) nunca aparece en el resultado.
    assert all(restoration_class != 0 for _sub, restoration_class, _code in result.counts)


def test_crosstab_progress_callback_reaches_100_percent(tmp_path: Path) -> None:
    shp_path, land_cover_path, restoration_path = build_fixture(tmp_path)
    crs = read_shapefile_crs(shp_path)
    grid = compute_target_grid(shapefile_bbox(shp_path), crs, [land_cover_path, restoration_path])
    geometries = subbasin_geometries(shp_path)

    calls: list[tuple[int, int]] = []
    compute_crosstab(
        land_cover_path, restoration_path, geometries, grid, block_size=4, on_progress=lambda i, n: calls.append((i, n))
    )

    assert calls
    assert calls[-1][0] == calls[-1][1]  # último callback = todos los bloques procesados
