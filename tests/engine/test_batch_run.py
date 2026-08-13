import subprocess
from pathlib import Path

import pytest

from engine import batch_run
from engine.batch_run import BATCH_REPORT_FILENAME, run_land_cover_batch
from scenarios.land_cover_config import LandCoverBatchConfig
from scenarios.nbs_area_batch import OutputOrganizeOptions
from swat_io.hru.parser import parse_hru_file


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


def _write_hru(path: Path, subbasin: int, hru: int, land_use: str, hru_fr: float) -> None:
    text = (
        f"Subbasin:{subbasin}   Hru:{hru}   Luse:{land_use}   Soil: SOIL1   Slope: 0-9999\n"
        f"{hru_fr:16.4f}    | HRU_FR : fraction of subbasin area\n"
    )
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def reference_project_dir(tmp_path: Path) -> Path:
    reference = tmp_path / "reference_project"
    txtinout = reference / "TxtInOut"
    txtinout.mkdir(parents=True)
    _write_hru(txtinout / "000010001.hru", 1, 1, "FRST", 0.10)
    _write_hru(txtinout / "000010002.hru", 1, 2, "PAST", 0.90)
    return reference


@pytest.fixture
def swat_executable(tmp_path: Path) -> Path:
    exe = tmp_path / "rev670_64rel.exe"
    exe.write_text("fake binary")
    return exe


@pytest.fixture
def batch_config() -> LandCoverBatchConfig:
    return LandCoverBatchConfig(
        target_lulc="FRST",
        target_pct_series=[20, 90],
        donor_priority=["PAST"],
        slope_priority=None,
        soil_priority=None,
    )


@pytest.fixture(autouse=True)
def _stub_post_processing(monkeypatch: pytest.MonkeyPatch):
    """Los organizadores reales (resumen de coberturas/humedales) dependen
    de .sub/.pnd que no hacen falta para probar la orquestación del batch
    -- eso ya lo cubren sus propios tests. Acá solo se registra que se
    llamaron, sobre qué escenario."""
    calls: dict[str, list] = {"coberturas": [], "humedales": []}
    monkeypatch.setattr(batch_run, "generar_resumen_coberturas", lambda d: calls["coberturas"].append(d))
    monkeypatch.setattr(batch_run, "generar_resumen_humedales", lambda d: calls["humedales"].append(d))
    return calls


def test_runs_series_independently_from_base(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reference_project_dir: Path,
    swat_executable: Path,
    batch_config: LandCoverBatchConfig,
):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen(a[0], returncode=0))
    destination_dir = tmp_path / "batch_out"

    results = run_land_cover_batch(
        reference_project_dir, destination_dir, batch_config, swat_executable, "swatUser.exe"
    )

    assert [r.status for r in results] == ["ok", "ok"]
    assert [r.target_pct for r in results] == [20, 90]

    # Cada paso parte de la referencia (10% FRST), no del escenario anterior.
    scenario_20 = destination_dir / "scenario_20pct" / "TxtInOut"
    scenario_90 = destination_dir / "scenario_90pct" / "TxtInOut"

    frst_20 = parse_hru_file(scenario_20 / "000010001.hru").get_value("HRU_FR")
    frst_90 = parse_hru_file(scenario_90 / "000010001.hru").get_value("HRU_FR")
    assert round(frst_20, 10) == 0.20
    assert round(frst_90, 10) == 0.90


def test_never_modifies_reference_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reference_project_dir: Path,
    swat_executable: Path,
    batch_config: LandCoverBatchConfig,
):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen(a[0], returncode=0))

    run_land_cover_batch(reference_project_dir, tmp_path / "batch_out", batch_config, swat_executable, "swatUser.exe")

    original = parse_hru_file(reference_project_dir / "TxtInOut" / "000010001.hru").get_value("HRU_FR")
    assert original == 0.10


def test_writes_batch_report_per_scenario(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reference_project_dir: Path,
    swat_executable: Path,
    batch_config: LandCoverBatchConfig,
):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen(a[0], returncode=0))
    destination_dir = tmp_path / "batch_out"

    run_land_cover_batch(reference_project_dir, destination_dir, batch_config, swat_executable, "swatUser.exe")

    report_path = destination_dir / "scenario_20pct" / "tool_outputs" / BATCH_REPORT_FILENAME
    assert report_path.is_file()
    content = report_path.read_text(encoding="utf-8")
    assert "TOTAL" in content
    assert "hru_count_changed" in content


def test_writes_batch_summary_across_scenarios(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reference_project_dir: Path,
    swat_executable: Path,
    batch_config: LandCoverBatchConfig,
):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen(a[0], returncode=0))
    destination_dir = tmp_path / "batch_out"

    run_land_cover_batch(reference_project_dir, destination_dir, batch_config, swat_executable, "swatUser.exe")

    summary_path = destination_dir / "land_cover_batch_summary.csv"
    assert summary_path.is_file()
    content = summary_path.read_text(encoding="utf-8")
    assert "scenario_20pct" in content
    assert "scenario_90pct" in content


def test_calls_post_processing_for_each_successful_scenario(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reference_project_dir: Path,
    swat_executable: Path,
    batch_config: LandCoverBatchConfig,
    _stub_post_processing: dict,
):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen(a[0], returncode=0))

    run_land_cover_batch(reference_project_dir, tmp_path / "batch_out", batch_config, swat_executable, "swatUser.exe")

    assert len(_stub_post_processing["coberturas"]) == 2
    assert len(_stub_post_processing["humedales"]) == 2


def test_continues_batch_after_scenario_dir_already_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reference_project_dir: Path,
    swat_executable: Path,
    batch_config: LandCoverBatchConfig,
):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen(a[0], returncode=0))
    destination_dir = tmp_path / "batch_out"
    (destination_dir / "scenario_20pct").mkdir(parents=True)

    results = run_land_cover_batch(
        reference_project_dir, destination_dir, batch_config, swat_executable, "swatUser.exe"
    )

    assert results[0].status == "error"
    assert results[1].status == "ok"


def test_continues_batch_after_swat_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reference_project_dir: Path,
    swat_executable: Path,
    batch_config: LandCoverBatchConfig,
):
    def fake_popen(args, **kwargs):
        # Falla solo la primera corrida (scenario_20pct).
        returncode = 1 if "scenario_20pct" in str(kwargs.get("cwd")) else 0
        return _FakePopen(args, returncode=returncode)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    results = run_land_cover_batch(
        reference_project_dir, tmp_path / "batch_out", batch_config, swat_executable, "swatUser.exe"
    )

    assert results[0].status == "error"
    assert "1" in results[0].error
    assert results[1].status == "ok"


def test_organizes_rch_and_hru_outputs_only_when_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reference_project_dir: Path,
    swat_executable: Path,
    batch_config: LandCoverBatchConfig,
):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen(a[0], returncode=0))

    calls: list[str] = []
    monkeypatch.setattr(batch_run, "parse_run_settings", lambda cio_path: calls.append("cio") or object())
    monkeypatch.setattr(batch_run, "parse_rch_file", lambda path: calls.append("parse_rch") or object())
    monkeypatch.setattr(batch_run, "build_rch_timeseries", lambda raw, settings: calls.append("build_rch") or object())
    monkeypatch.setattr(batch_run, "export_rch_timeseries_csvs", lambda ts, dest: calls.append("export_rch"))
    monkeypatch.setattr(
        batch_run,
        "build_hru_output_database",
        lambda path, settings, dest, report_progress=None: calls.append("build_hru_db"),
    )

    # Sin output.rch/output.hru en la referencia: no debe llamar a nada de esto.
    run_land_cover_batch(
        reference_project_dir, tmp_path / "batch_out_1", batch_config, swat_executable, "swatUser.exe"
    )
    assert calls == []

    # Con output.rch presente (aunque vacío): sí debe organizarse.
    (reference_project_dir / "TxtInOut" / "output.rch").write_text("")
    run_land_cover_batch(
        reference_project_dir, tmp_path / "batch_out_2", batch_config, swat_executable, "swatUser.exe"
    )
    assert "parse_rch" in calls
    assert "build_rch" in calls
    assert "export_rch" in calls
    assert "build_hru_db" not in calls


def test_organizes_sub_output_only_when_present_and_selected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reference_project_dir: Path,
    swat_executable: Path,
    batch_config: LandCoverBatchConfig,
):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen(a[0], returncode=0))
    (reference_project_dir / "TxtInOut" / "output.sub").write_text("")

    calls: list[str] = []
    monkeypatch.setattr(batch_run, "parse_run_settings", lambda cio_path: calls.append("cio") or object())
    monkeypatch.setattr(batch_run, "parse_sub_file", lambda path: calls.append("parse_sub") or object())
    monkeypatch.setattr(batch_run, "build_sub_timeseries", lambda raw, settings: calls.append("build_sub") or object())
    monkeypatch.setattr(batch_run, "export_sub_timeseries_csvs", lambda ts, dest: calls.append("export_sub"))

    run_land_cover_batch(
        reference_project_dir, tmp_path / "batch_out_1", batch_config, swat_executable, "swatUser.exe",
        output_options=OutputOrganizeOptions(rch=False, sub=True, hru=False),
    )
    assert "parse_sub" in calls
    assert "export_sub" in calls

    calls.clear()
    run_land_cover_batch(
        reference_project_dir, tmp_path / "batch_out_2", batch_config, swat_executable, "swatUser.exe",
        output_options=OutputOrganizeOptions(rch=False, sub=False, hru=False),
    )
    assert calls == []


def test_output_options_default_organizes_everything_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reference_project_dir: Path,
    swat_executable: Path,
    batch_config: LandCoverBatchConfig,
):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen(a[0], returncode=0))
    (reference_project_dir / "TxtInOut" / "output.rch").write_text("")
    (reference_project_dir / "TxtInOut" / "output.sub").write_text("")

    calls: list[str] = []
    monkeypatch.setattr(batch_run, "parse_run_settings", lambda cio_path: calls.append("cio") or object())
    monkeypatch.setattr(batch_run, "parse_rch_file", lambda path: calls.append("parse_rch") or object())
    monkeypatch.setattr(batch_run, "build_rch_timeseries", lambda raw, settings: object())
    monkeypatch.setattr(batch_run, "export_rch_timeseries_csvs", lambda ts, dest: None)
    monkeypatch.setattr(batch_run, "parse_sub_file", lambda path: calls.append("parse_sub") or object())
    monkeypatch.setattr(batch_run, "build_sub_timeseries", lambda raw, settings: object())
    monkeypatch.setattr(batch_run, "export_sub_timeseries_csvs", lambda ts, dest: None)

    # Sin output_options (None -> default): mismo comportamiento "organizar
    # todo lo que exista" que tenía la función antes de este parámetro.
    run_land_cover_batch(reference_project_dir, tmp_path / "batch_out", batch_config, swat_executable, "swatUser.exe")

    assert "parse_rch" in calls
    assert "parse_sub" in calls
