"""Smoke test con un root de Tk real (oculto, sin mainloop) para
SubResultsTab -- mismo patrón que test_nbs_tab_smoke.py: no es un test de
lógica de negocio (eso lo cubre tests/swat_io/test_sub_output_parser.py),
es para atrapar errores que solo aparecen al construir/mutar widgets de
verdad y al correr Organize por el hilo de fondo real
(ui.tasks.run_in_background).
"""
from __future__ import annotations

import time
from pathlib import Path

import customtkinter as ctk
import pytest

from config.settings import ConfigManager
from scenarios.project import ProjectMetadata
from swat_io.sub_output_parser import SUB_VARIABLE_COLUMNS, sub_timeseries_dir
from ui.tab_sub_results import SubResultsTab

_CIO = (
    "               2    | NBYR : Number of years simulated\n"
    "            2016    | IYR : Beginning year of simulation\n"
    "               1    | IDAF : Beginning julian day of simulation\n"
    "             365    | IDAL : Ending julian day of simulation\n"
    "               2    | IPRINT: print code (month, day, year)\n"
    "               0    | NYSKIP: number of years to skip output printing/summarization\n"
)

_VARIABLE_WIDTHS = [10] * 19 + [11] + [10] * 5
assert len(_VARIABLE_WIDTHS) == len(SUB_VARIABLE_COLUMNS)


def _row(sub: int, mon: int, *, area: float = 1.0) -> str:
    values = [area] + [0.0] * (len(SUB_VARIABLE_COLUMNS) - 1)
    mon_field = str(mon).rjust(5)
    var_fields = "".join(f"{v:.4E}".rjust(w) for v, w in zip(values, _VARIABLE_WIDTHS))
    return f"BIGSUB{sub:5d}{0:9d}{mon_field}{var_fields}\n"


_SUB_PRELUDE = (
    "1  1\n"
    "    SWAT Sep 7    VER 2018/Rev 670\n"
    "\n"
    "    General Input/Output section (file.cio):\n"
    "    8/26/2021 12:00:00 AM ARCGIS-SWAT interface AV\n"
    "\n"
    "\n"
    "\n"
    "       SUB      GIS  MON   AREAkm2  PRECIPmm SNOMELTmm ...\n"
)


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


@pytest.fixture
def project(tmp_path: Path) -> Path:
    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    (txtinout / "file.cio").write_text(_CIO, encoding="utf-8")
    rows = [_row(1, 2016, area=20.21), _row(1, 2017, area=20.21), _row(2, 2016, area=16.06), _row(2, 2017, area=16.06)]
    (txtinout / "output.sub").write_text(_SUB_PRELUDE + "".join(rows), encoding="utf-8")
    return tmp_path


def _pump(root, predicate, *, timeout_s: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.02)


def test_sub_results_tab_set_project_without_output_disables_organize(hidden_root, config, tmp_path) -> None:
    (tmp_path / "TxtInOut").mkdir()
    tab = SubResultsTab(hidden_root, config)
    tab.set_project(tmp_path, ProjectMetadata())

    assert str(tab._organize_button.cget("state")) == "disabled"


def test_sub_results_tab_organize_populates_selectors_and_chart(hidden_root, config, project) -> None:
    tab = SubResultsTab(hidden_root, config)
    tab.set_project(project, ProjectMetadata())
    assert str(tab._organize_button.cget("state")) == "normal"

    tab._on_organize_clicked()
    _pump(hidden_root, lambda: "Organized" in tab._status_label.cget("text") or "error" in tab._status_label.cget("text").lower())

    assert "Organized" in tab._status_label.cget("text")
    assert set(tab._subbasin_selector.cget("values")) == {"1", "2"}
    assert tab._chart_canvas is not None

    written = sub_timeseries_dir(project)
    assert (written / "sub_1.csv").is_file()
    assert (written / "sub_2.csv").is_file()


def test_sub_results_tab_without_shapefile_shows_map_hint(hidden_root, config, project) -> None:
    tab = SubResultsTab(hidden_root, config)
    tab.set_project(project, ProjectMetadata())

    assert tab._map_hint_label.cget("text") == config.text("sub_results_tab.map_missing_hint")
