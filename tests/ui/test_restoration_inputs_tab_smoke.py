"""Smoke tests con un root de Tk real (oculto, sin mainloop) para
RestorationInputsTab -- mismo patrón que el resto de esta suite. Mockea
filedialog y run_in_background (corre sincrónico) para no depender de
diálogos reales ni threading real; el motor de cruce en sí (raster_io +
scenarios.nbs_raster_inputs) ya tiene su propia cobertura en
tests/raster_io/ y tests/scenarios/test_nbs_raster_inputs.py -- acá solo
se prueba que los widgets se arman/actualizan bien con datos reales de esa
capa."""
from __future__ import annotations

from pathlib import Path

import customtkinter as ctk
import numpy as np
import pytest
import rasterio
import shapefile
from rasterio.crs import CRS
from rasterio.transform import from_origin

from config.settings import ConfigManager
from scenarios.project import ProjectMetadata
from ui.tab_restoration_inputs import RestorationInputsTab

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


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "TxtInOut").mkdir()
    (tmp_path / "TxtInOut" / "000010001.hru").write_text(_HRU, encoding="utf-8")

    shp_path = _write_fixture_shapefile(tmp_path / "subs.shp")

    land_cover = np.zeros((_HEIGHT, _WIDTH), dtype="uint8")
    land_cover[:, 0:10] = 1
    land_cover[:, 10:20] = 2
    _write_raster(tmp_path / "land_cover.tif", land_cover)

    restoration = np.ones((_HEIGHT, _WIDTH), dtype="uint8")
    _write_raster(tmp_path / "restoration.tif", restoration)

    return tmp_path


@pytest.fixture(scope="module")
def config() -> ConfigManager:
    cfg = ConfigManager()
    cfg.load_all()
    return cfg


@pytest.fixture(scope="module")
def hidden_root():
    root = ctk.CTk()
    root.withdraw()
    yield root
    root.destroy()


def _install_synchronous_run_in_background(monkeypatch) -> None:
    import ui.tab_restoration_inputs as tab_module

    monkeypatch.setattr(
        tab_module, "run_in_background",
        lambda widget, work, *, on_progress, on_done, on_error, **_kw: on_done(work(lambda _m: None)),
    )


def test_tab_builds_disabled_without_project(hidden_root, config) -> None:
    RestorationInputsTab(hidden_root, config, on_run_state_changed=lambda _running: None)


def test_set_project_shows_no_shapefile_hint_when_unconfigured(hidden_root, config, project: Path) -> None:
    tab = RestorationInputsTab(hidden_root, config, on_run_state_changed=lambda _running: None)
    tab.set_project(project, ProjectMetadata())

    assert tab._no_shapefile_label.cget("text") != ""


def test_set_project_prefills_raster_fields_from_metadata(hidden_root, config, project: Path) -> None:
    tab = RestorationInputsTab(hidden_root, config, on_run_state_changed=lambda _running: None)
    metadata = ProjectMetadata(
        subbasin_shp_path=str(project / "subs.shp"),
        land_cover_raster_path=str(project / "land_cover.tif"),
        restoration_raster_path=str(project / "restoration.tif"),
    )

    tab.set_project(project, metadata)

    assert tab._land_cover_field._value.cget("text") == str(project / "land_cover.tif")
    assert tab._no_shapefile_label.cget("text") == ""


def test_scan_populates_restoration_classes_and_crosswalk_rows(hidden_root, config, project: Path, monkeypatch) -> None:
    _install_synchronous_run_in_background(monkeypatch)

    tab = RestorationInputsTab(hidden_root, config, on_run_state_changed=lambda _running: None)
    metadata = ProjectMetadata(
        subbasin_shp_path=str(project / "subs.shp"),
        land_cover_raster_path=str(project / "land_cover.tif"),
        restoration_raster_path=str(project / "restoration.tif"),
    )
    tab.set_project(project, metadata)

    tab._on_scan_clicked()

    assert "1" in tab._restoration_classes_label.cget("text")
    assert set(tab._crosswalk_selectors.keys()) == {1, 2}
    assert tab._compute_button.cget("state") == "normal"


def test_compute_writes_csv_and_enables_open_folder(hidden_root, config, project: Path, monkeypatch) -> None:
    _install_synchronous_run_in_background(monkeypatch)

    tab = RestorationInputsTab(hidden_root, config, on_run_state_changed=lambda _running: None)
    metadata = ProjectMetadata(
        subbasin_shp_path=str(project / "subs.shp"),
        land_cover_raster_path=str(project / "land_cover.tif"),
        restoration_raster_path=str(project / "restoration.tif"),
    )
    tab.set_project(project, metadata)
    tab._on_scan_clicked()

    skip_label = config.text("restoration_inputs_tab.crosswalk_skip_option")
    for code, selector in tab._crosswalk_selectors.items():
        selector.set("AGRL" if code == 1 else skip_label)

    tab._on_compute_clicked()

    assert tab._open_folder_button.cget("state") == "normal"
    output_dir = project / "tool_outputs" / "restoration_inputs"
    csv_files = list(output_dir.glob("*.csv"))
    assert len(csv_files) == 1

    import pandas as pd

    df = pd.read_csv(csv_files[0])
    assert list(df.columns) == ["subbasin", "area_ha", "AGRL"]
    assert set(df["subbasin"]) == {1}  # subcuenca 2 quedó sin mapear (skip) -> excluida
