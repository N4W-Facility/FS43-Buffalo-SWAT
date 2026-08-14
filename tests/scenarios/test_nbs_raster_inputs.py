"""Tests de scenarios.nbs_raster_inputs sobre la misma fixture chica y
determinista que tests/raster_io/test_crosstab.py (duplicada acá a
propósito -- tests/ no es un paquete, ver ese archivo para el motivo) más
un TxtInOut sintético mínimo, para probar el cruce CDL->CPNM y el formato
de salida contra scenarios.nbs_mass_apply.parse_mass_allocation_csv (que
es quien realmente lo va a leer después)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
import shapefile
from rasterio.crs import CRS
from rasterio.transform import from_origin

from scenarios.nbs_mass_apply import parse_mass_allocation_csv
from scenarios.nbs_raster_inputs import (
    compute_restoration_area_csvs,
    discover_project_coverages,
    scan_restoration_inputs,
)

_CRS = CRS.from_epsg(32617)
_PIXEL_SIZE = 10.0
_WIDTH, _HEIGHT = 20, 10

_HRU = (
    "Subbasin:1   Hru:1   Luse:AGRL   Soil: 1013090         Slope: 0-9999\n"
    "        1.0000    | HRU_FR : Fraction of subbasin area contained in HRU\n"
)


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


def _build_project(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    shp_path = _write_fixture_shapefile(tmp_path / "subs.shp")
    land_cover_path = _write_fixture_land_cover_raster(tmp_path / "land_cover.tif")
    restoration_path = _write_fixture_restoration_raster(tmp_path / "restoration.tif")
    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    (txtinout / "000010001.hru").write_text(_HRU, encoding="utf-8")
    return tmp_path, shp_path, land_cover_path, restoration_path


def test_scan_restoration_inputs_finds_classes_and_codes(tmp_path: Path) -> None:
    project_dir, shp_path, land_cover_path, restoration_path = _build_project(tmp_path)

    scan = scan_restoration_inputs(shp_path, land_cover_path, restoration_path)

    assert {c.value for c in scan.restoration_classes} == {1}
    assert {c.code for c in scan.land_cover_codes} == {1, 2, 99}


def test_discover_project_coverages_reads_real_hru_files(tmp_path: Path) -> None:
    project_dir, shp_path, land_cover_path, restoration_path = _build_project(tmp_path)

    assert discover_project_coverages(project_dir) == ["AGRL"]


def test_compute_writes_csv_that_parse_mass_allocation_csv_accepts(tmp_path: Path) -> None:
    project_dir, shp_path, land_cover_path, restoration_path = _build_project(tmp_path)
    crosswalk = {1: "FRSD", 2: "PAST"}  # código 99 queda sin mapear a propósito

    result = compute_restoration_area_csvs(project_dir, shp_path, land_cover_path, restoration_path, crosswalk)

    assert len(result.outputs) == 1
    output = result.outputs[0]
    assert output.restoration_value == 1
    assert output.csv_path.exists()

    allocations, errors = parse_mass_allocation_csv(output.csv_path)
    assert errors == []

    # Subcuenca 1: 80 px código 1 (mapeado a FRSD) -> 0.8 ha, 100% FRSD.
    assert allocations[1].area_ha == 0.8
    assert allocations[1].sources == [("FRSD", 100.0)]

    # Subcuenca 2: 50 px código 2 (PAST, mapeado) + 50 px código 99 (sin
    # mapear, excluido) -> area_ha solo cuenta lo mapeado.
    assert allocations[2].area_ha == 0.5
    assert allocations[2].sources == [("PAST", 100.0)]
    assert output.excluded_ha_by_subbasin[2] == 0.5
    assert 1 not in output.excluded_ha_by_subbasin  # nada excluido en subcuenca 1


def test_compute_with_no_mapped_codes_writes_no_rows(tmp_path: Path) -> None:
    project_dir, shp_path, land_cover_path, restoration_path = _build_project(tmp_path)

    result = compute_restoration_area_csvs(project_dir, shp_path, land_cover_path, restoration_path, {123: "FRSD"})

    assert len(result.outputs) == 1
    assert result.outputs[0].subbasin_count == 0
