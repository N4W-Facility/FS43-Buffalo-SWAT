"""Smoke test end-to-end de la sección "NbS area batch (percentage series)"
de la pestaña Batch (scenarios/nbs_area_batch.py + engine/nbs_area_batch_run.py
+ su UI en ui/tab_batch.py) -- mismo patrón de root de Tk real (oculto, sin
mainloop) y de subprocess.Popen mockeado que
tests/ui/test_nbs_mass_apply_tab_smoke.py / tests/engine/test_batch_run.py,
para no depender de un swat2012.exe real.

No mockea apply_nbs, plan_mass_area_allocation ni run_nbs_area_batch: el
objetivo es confirmar que la configuración cargada en la UI llega completa
hasta la escritura real de .hru/.mgt de la copia de escenario. Sí mockea
ConfirmDialog (auto-confirma), run_in_background (corre sincrónico) y
subprocess.Popen (swat2012.exe falso)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import customtkinter as ctk
import pandas as pd
import pytest

from config.settings import AppPaths, ConfigManager
from scenarios.nbs import NbSDefinition, add_or_replace
from scenarios.nbs_mass_apply import SubbasinAreaAllocation
from swat_io.hru.parser import parse_hru_file
from ui.tab_batch import BatchTab

_PLANT_DAT = (
    "   1  AGRL   4\r\n"
    "  33.50   0.45    3.00   0.15   0.05   0.50   0.95   0.64    1.00   2.00\r\n"
    "  30.00   11.00   0.0199   0.0032   0.0440   0.0164   0.0128   0.0060   0.0022   0.0018\r\n"
    "  0.250   0.2000   0.0050   4.00   0.750    8.50    660.00    36.00   0.0500   0.000\r\n"
    "  0.000     0    0.00   0.650   0.100\r\n"
    "   6  FRST   7\r\n"
    "  15.00   0.76    5.00   0.05   0.05   0.40   0.95   0.99    6.00   3.50\r\n"
    "  20.00    0.00   0.0015   0.0003   0.0060   0.0020   0.0015   0.0007   0.0004   0.0003\r\n"
    "  0.010   0.0010   0.0020   4.00   0.750    8.00    660.00    16.00   0.0500   0.750\r\n"
    "  0.300    50  1000.00   0.650   0.100\r\n"
)

_HRU_TEMPLATE = (
    "Subbasin:{sub}   Hru:{hru}   Luse:AGRL   Soil: 1013090         Slope: 0-9999\n"
    "        1.0000    | HRU_FR : Fraction of subbasin area contained in HRU\n"
    "        0.1500    | OV_N : Manning's \"n\" value for overland flow\n"
    "        1.0000    | CANMX : Maximum canopy storage (mm)\n"
    "     5000.0000    | RSDIN : Initial residue cover (kg/ha)\n"
)

_MGT_TEMPLATE = (
    " .mgt file HRU:{hru} Subbasin:{sub} HRU:{hru} Luse:AGRL\n"
    "               0    | NMGT:Management code\n"
    "Initial Plant Growth Parameters\n"
    "               0    | IGRO: Land cover status: 0-none growing; 1-growing\n"
    "               0    | PLANT_ID: Land cover ID number (IGRO = 1)\n"
    "            0.00    | LAI_INIT: Initial leaf are index (IGRO = 1)\n"
    "            0.00    | BIO_INIT: Initial biomass (kg/ha) (IGRO = 1)\n"
    "            0.00    | PHU_PLT: Number of heat units to bring plant to maturity (IGRO = 1)\n"
    "General Management Parameters\n"
    "            0.20    | BIOMIX: Biological mixing efficiency\n"
    "           83.00    | CN2: Initial SCS CN II value\n"
    "            1.00    | USLE_P: USLE support practice factor\n"
    "            0.00    | BIO_MIN: Minimum biomass for grazing (kg/ha)\n"
    "           0.000    | FILTERW: width of edge of field filter strip (m)\n"
    "Management Operations:\n"
    "               1    | NROT: number of years of rotation\n"
    "Operation Schedule:\n"
    "  5 15           1   19          1084.00000   0.00     0.00000 0.00   0.00  0.00\n"
    "                17\n"
)

_SOL_TEMPLATE = " .Sol file HRU:{hru} Subbasin:{sub} HRU:{hru}\n Soil Name: Test\n Soil Hydrologic Group: C\n"

_SUB = "Subbasin:{sub}\n        1.0000    | SUB_KM : Subbasin area (km2)\n"  # 1 km2 = 100 ha


class _FakeStream:
    def __init__(self, lines=()):
        self._iterator = iter(lines)

    def __iter__(self):
        return self._iterator

    def close(self) -> None:
        pass


class _FakePopen:
    def __init__(self, args, *, returncode: int = 0, **kwargs):
        self.args = args
        self._returncode = returncode
        self.stdout = _FakeStream()
        self.stderr = _FakeStream()
        self.returncode: int | None = None

    def wait(self) -> int:
        self.returncode = self._returncode
        return self.returncode


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
def swat_executable(tmp_path: Path) -> Path:
    exe = tmp_path / "rev670_64rel.exe"
    exe.write_text("fake binary")
    return exe


@pytest.fixture
def project(tmp_path: Path) -> Path:
    txtinout = tmp_path / "project" / "TxtInOut"
    txtinout.mkdir(parents=True)
    (txtinout / "plant.dat").write_text(_PLANT_DAT, encoding="utf-8", newline="")
    (txtinout / "000010000.sub").write_text(_SUB.format(sub=1), encoding="utf-8")
    (txtinout / "000010000.pnd").write_text("", encoding="utf-8")
    (txtinout / "000010001.hru").write_text(_HRU_TEMPLATE.format(sub=1, hru=1), encoding="utf-8")
    (txtinout / "000010001.mgt").write_text(_MGT_TEMPLATE.format(sub=1, hru=1), encoding="utf-8")
    (txtinout / "000010001.sol").write_text(_SOL_TEMPLATE.format(sub=1, hru=1), encoding="utf-8")
    return tmp_path / "project"


def _install_synchronous_mocks(monkeypatch) -> None:
    import ui.tab_batch as tab_batch_module

    monkeypatch.setattr(tab_batch_module, "ConfirmDialog", lambda master, cfg, *, message, on_confirm: on_confirm())
    monkeypatch.setattr(
        tab_batch_module, "run_in_background",
        lambda widget, work, *, on_progress, on_done, on_error, **_kw: on_done(work(lambda _m: None)),
    )


def _nbs_definition() -> NbSDefinition:
    return NbSDefinition(
        name="Restore forest", target_lulc="FRST", new_coverage=None,
        hru_params={"CANMX": 3.0, "OV_N": 0.12}, mgt_initial={"IGRO": 0}, cn2_by_hsg={"C": 88.33}, operations=[],
    )


def test_run_button_disabled_until_destination_csv_and_nbs_are_set(
    hidden_root, config, project, swat_executable, monkeypatch
) -> None:
    add_or_replace(project, _nbs_definition())
    _install_synchronous_mocks(monkeypatch)
    config.paths = AppPaths(swat_executable=swat_executable)

    tab = BatchTab(hidden_root, config)
    tab.set_project(project)
    assert tab._nbs_batch_run_button.cget("state") == "disabled"

    tab._nbs_batch_destination_dir = project.parent / "batch_out"
    tab._nbs_batch_allocations = {}
    tab._update_nbs_batch_run_button_state()
    assert tab._nbs_batch_run_button.cget("state") == "disabled"  # sin CSV cargado todavía

    csv_path = project / "matrix.csv"
    pd.DataFrame([{"subbasin": 1, "area_ha": 100, "AGRL": 100}]).to_csv(csv_path, index=False)
    monkeypatch.setattr("ui.tab_batch.filedialog.askopenfilename", lambda **_kw: str(csv_path))
    tab._on_nbs_batch_load_csv_clicked()

    assert tab._nbs_batch_run_button.cget("state") == "normal"


def test_full_series_run_writes_independent_scenarios(
    hidden_root, config, project, swat_executable, monkeypatch
) -> None:
    add_or_replace(project, _nbs_definition())
    _install_synchronous_mocks(monkeypatch)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen(a[0], returncode=0))
    config.paths = AppPaths(swat_executable=swat_executable)

    tab = BatchTab(hidden_root, config)
    tab.set_project(project)

    destination_dir = project.parent / "batch_out"
    tab._nbs_batch_destination_dir = destination_dir
    tab._nbs_batch_dest_field.set_value(str(destination_dir))

    tab._nbs_batch_allocations = {1: SubbasinAreaAllocation(area_ha=100.0, sources=[("AGRL", 100.0)])}
    tab._nbs_batch_pct_entry.insert(0, "50,100")

    tab._on_nbs_batch_run_clicked()

    for pct in ("50", "100"):
        hru_file = parse_hru_file(destination_dir / f"scenario_{pct}pct" / "TxtInOut" / "000010001.hru")
        assert hru_file.metadata.land_use == "FRST"

    # El proyecto de referencia nunca se toca.
    original = parse_hru_file(project / "TxtInOut" / "000010001.hru")
    assert original.metadata.land_use == "AGRL"

    assert tab._nbs_batch_status_label.cget("text") != ""
