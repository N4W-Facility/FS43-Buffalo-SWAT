"""Tests de engine.nbs_area_batch_run sobre un TxtInOut sintético
autocontenido en tmp_path -- mismo patrón de subprocess.Popen mockeado que
tests/engine/test_batch_run.py, para no depender de un swat2012.exe real."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pandas as pd
import pytest

from engine import nbs_area_batch_run
from engine.nbs_area_batch_run import NbSAreaScenarioResult, run_nbs_area_batch
from scenarios.nbs import NbSDefinition
from scenarios.nbs_area_batch import OutputOrganizeOptions
from scenarios.nbs_mass_apply import SubbasinAreaAllocation
from swat_io.hru.parser import parse_hru_file
from tests.helpers import write_synthetic_sub

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
    "Subbasin:{sub}   Hru:{hru}   Luse:{luse}   Soil: 1013090         Slope: 0-9999\n"
    "        {hru_fr:.4f}    | HRU_FR : Fraction of subbasin area contained in HRU\n"
    "        0.1500    | OV_N : Manning's \"n\" value for overland flow\n"
    "        1.0000    | CANMX : Maximum canopy storage (mm)\n"
    "     5000.0000    | RSDIN : Initial residue cover (kg/ha)\n"
)

_MGT_TEMPLATE = (
    " .mgt file HRU:{hru} Subbasin:{sub} HRU:{hru} Luse:{luse}\n"
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


def _write_hru_mgt_sol(txtinout: Path, sub: int, hru: int, luse: str, hru_fr: float) -> None:
    (txtinout / f"{sub:05d}{hru:04d}.hru").write_text(
        _HRU_TEMPLATE.format(sub=sub, hru=hru, luse=luse, hru_fr=hru_fr), encoding="utf-8"
    )
    (txtinout / f"{sub:05d}{hru:04d}.mgt").write_text(
        _MGT_TEMPLATE.format(sub=sub, hru=hru, luse=luse), encoding="utf-8"
    )
    (txtinout / f"{sub:05d}{hru:04d}.sol").write_text(_SOL_TEMPLATE.format(sub=sub, hru=hru), encoding="utf-8")


@pytest.fixture
def reference_project_dir(tmp_path: Path) -> Path:
    reference = tmp_path / "reference_project"
    txtinout = reference / "TxtInOut"
    txtinout.mkdir(parents=True)
    (txtinout / "plant.dat").write_text(_PLANT_DAT, encoding="utf-8", newline="")
    write_synthetic_sub(txtinout / "000010000.sub", area_km2=1.0)  # 100 ha
    (txtinout / "000010000.pnd").write_text("", encoding="utf-8")
    # AGRL solo tiene 60 ha disponibles -- deja lugar para probar el caso de déficit tolerado.
    _write_hru_mgt_sol(txtinout, 1, 1, "AGRL", 0.6)
    _write_hru_mgt_sol(txtinout, 1, 2, "PAST", 0.4)
    return reference


@pytest.fixture
def swat_executable(tmp_path: Path) -> Path:
    exe = tmp_path / "rev670_64rel.exe"
    exe.write_text("fake binary")
    return exe


@pytest.fixture
def nbs_definition() -> NbSDefinition:
    return NbSDefinition(
        name="Restore forest", target_lulc="FRST", new_coverage=None,
        hru_params={"CANMX": 3.0, "OV_N": 0.12}, mgt_initial={"IGRO": 0}, cn2_by_hsg={"C": 88.33}, operations=[],
    )


@pytest.fixture
def allocations() -> dict[int, SubbasinAreaAllocation]:
    return {1: SubbasinAreaAllocation(area_ha=100.0, sources=[("AGRL", 100.0)])}


@pytest.fixture(autouse=True)
def _stub_post_processing(monkeypatch: pytest.MonkeyPatch):
    calls: dict[str, list] = {"coberturas": [], "humedales": []}
    monkeypatch.setattr(nbs_area_batch_run, "generar_resumen_coberturas", lambda d: calls["coberturas"].append(d))
    monkeypatch.setattr(nbs_area_batch_run, "generar_resumen_humedales", lambda d: calls["humedales"].append(d))
    return calls


def test_runs_series_independently_from_base(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reference_project_dir: Path,
    swat_executable: Path,
    nbs_definition: NbSDefinition,
    allocations: dict,
):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen(a[0], returncode=0))
    destination_dir = tmp_path / "batch_out"

    results = run_nbs_area_batch(
        reference_project_dir, destination_dir, nbs_definition, allocations, [50.0, 100.0],
        swat_executable, "swatUser.exe",
    )

    assert [r.status for r in results] == ["ok", "ok"]
    assert [r.target_pct for r in results] == [50.0, 100.0]

    # Ambos pasos convierten la misma (única) HRU de AGRL -- no se puede partir.
    hru_50 = parse_hru_file(destination_dir / "scenario_50pct" / "TxtInOut" / "000010001.hru")
    hru_100 = parse_hru_file(destination_dir / "scenario_100pct" / "TxtInOut" / "000010001.hru")
    assert hru_50.metadata.land_use == "FRST"
    assert hru_100.metadata.land_use == "FRST"

    # 50%: 50 ha pedidas, 60 ha disponibles -> sin déficit. 100%: 100 ha pedidas, 60 disponibles -> déficit 40.
    assert results[0].total_deficit_ha == pytest.approx(0.0)
    assert results[1].total_deficit_ha == pytest.approx(40.0)
    assert results[0].applied_count == 1
    assert results[1].applied_count == 1


def test_never_modifies_reference_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reference_project_dir: Path,
    swat_executable: Path,
    nbs_definition: NbSDefinition,
    allocations: dict,
):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen(a[0], returncode=0))

    run_nbs_area_batch(
        reference_project_dir, tmp_path / "batch_out", nbs_definition, allocations, [50.0],
        swat_executable, "swatUser.exe",
    )

    original = parse_hru_file(reference_project_dir / "TxtInOut" / "000010001.hru")
    assert original.metadata.land_use == "AGRL"


def test_writes_step_area_report_and_apply_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reference_project_dir: Path,
    swat_executable: Path,
    nbs_definition: NbSDefinition,
    allocations: dict,
):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen(a[0], returncode=0))
    destination_dir = tmp_path / "batch_out"

    results = run_nbs_area_batch(
        reference_project_dir, destination_dir, nbs_definition, allocations, [100.0],
        swat_executable, "swatUser.exe",
    )

    scenario_dir = destination_dir / "scenario_100pct"
    assert results[0].area_report_path == scenario_dir / "tool_outputs" / "nbs_area_batch_report.csv"
    assert results[0].area_report_path.is_file()
    df = pd.read_csv(results[0].area_report_path)
    assert df.iloc[0]["deficit_ha"] == pytest.approx(40.0)

    apply_reports = list((scenario_dir / "tool_outputs").glob("nbs_apply_report_*.csv"))
    assert len(apply_reports) == 1


def test_deficit_does_not_abort_the_step(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reference_project_dir: Path,
    swat_executable: Path,
    nbs_definition: NbSDefinition,
    allocations: dict,
):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen(a[0], returncode=0))

    # 100% pide más área (100 ha) de la que AGRL tiene (60 ha) -- debe aplicarse igual, no abortar.
    results = run_nbs_area_batch(
        reference_project_dir, tmp_path / "batch_out", nbs_definition, allocations, [100.0],
        swat_executable, "swatUser.exe",
    )

    assert results[0].status == "ok"
    assert results[0].applied_count == 1


def test_continues_batch_after_swat_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reference_project_dir: Path,
    swat_executable: Path,
    nbs_definition: NbSDefinition,
    allocations: dict,
):
    def fake_popen(args, **kwargs):
        returncode = 1 if "scenario_50pct" in str(kwargs.get("cwd")) else 0
        return _FakePopen(args, returncode=returncode)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    results = run_nbs_area_batch(
        reference_project_dir, tmp_path / "batch_out", nbs_definition, allocations, [50.0, 100.0],
        swat_executable, "swatUser.exe",
    )

    assert results[0].status == "error"
    assert "1" in results[0].error
    assert results[1].status == "ok"


def test_organizes_only_selected_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reference_project_dir: Path,
    swat_executable: Path,
    nbs_definition: NbSDefinition,
    allocations: dict,
):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen(a[0], returncode=0))
    (reference_project_dir / "TxtInOut" / "output.rch").write_text("")
    (reference_project_dir / "TxtInOut" / "output.sub").write_text("")

    calls: list[str] = []
    monkeypatch.setattr(nbs_area_batch_run, "parse_run_settings", lambda cio_path: calls.append("cio") or object())
    monkeypatch.setattr(nbs_area_batch_run, "parse_rch_file", lambda path: calls.append("parse_rch") or object())
    monkeypatch.setattr(
        nbs_area_batch_run, "build_rch_timeseries", lambda raw, settings: calls.append("build_rch") or object()
    )
    monkeypatch.setattr(nbs_area_batch_run, "export_rch_timeseries_csvs", lambda ts, dest: calls.append("export_rch"))
    monkeypatch.setattr(nbs_area_batch_run, "parse_sub_file", lambda path: calls.append("parse_sub") or object())
    monkeypatch.setattr(
        nbs_area_batch_run, "build_sub_timeseries", lambda raw, settings: calls.append("build_sub") or object()
    )
    monkeypatch.setattr(nbs_area_batch_run, "export_sub_timeseries_csvs", lambda ts, dest: calls.append("export_sub"))

    run_nbs_area_batch(
        reference_project_dir, tmp_path / "batch_out", nbs_definition, allocations, [50.0],
        swat_executable, "swatUser.exe",
        output_options=OutputOrganizeOptions(rch=True, sub=False, hru=False),
    )

    assert "parse_rch" in calls
    assert "export_rch" in calls
    assert "parse_sub" not in calls
    assert "export_sub" not in calls
