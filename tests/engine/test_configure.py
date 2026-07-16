from pathlib import Path

import pytest

from engine.configure import configure_scenario
from scenarios.draft import init_draft, update_draft_value
from scenarios.models import Project
from swat_io.pnd_parser import parse_pnd_file
from tests.helpers import make_synthetic_txtinout

_LAYOUT = {"fields": [{"id": "wet_fr", "range": [0.0, 1.0]}]}


def _make_project(tmp_path: Path) -> Project:
    base_dir = tmp_path / "base" / "Buffalo_calibrated_annual"
    txtinout_dir = make_synthetic_txtinout(base_dir, {1: {"WET_FR": 0.2}, 2: {"WET_FR": 0.0}})
    project_dir = tmp_path / "workspace" / "Buffalo"
    project_dir.mkdir(parents=True)
    return Project(
        watershed="Buffalo",
        base_model_dir=base_dir,
        base_txtinout_dir=txtinout_dir,
        project_dir=project_dir,
    )


def test_configure_scenario_materializes_working_copy(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    draft_path = init_draft(project, "Buffalo_WET_MS_annual")
    update_draft_value(draft_path, 1, "wet_fr", 0.9, _LAYOUT)
    swat_executable = tmp_path / "rev670_64rel.exe"
    swat_executable.write_text("fake binary")

    result = configure_scenario(project, "Buffalo_WET_MS_annual", swat_executable, "swatUser.exe")

    assert result.txtinout_dir == project.project_dir / "Buffalo_WET_MS_annual" / "TxtInOut"
    assert (result.txtinout_dir / "swatUser.exe").exists()
    updated = parse_pnd_file(result.txtinout_dir / "000010000.pnd", subbasin_id=1)
    assert updated.wet_fr == 0.9
    unchanged = parse_pnd_file(result.txtinout_dir / "000020000.pnd", subbasin_id=2)
    assert unchanged.wet_fr == 0.0
    assert result.params_csv == result.scenario_dir / "tool_outputs" / "scenario_params.csv"
    assert result.params_csv.exists()
    assert not draft_path.exists()
    # base model untouched
    base_pnd = parse_pnd_file(project.base_txtinout_dir / "000010000.pnd", subbasin_id=1)
    assert base_pnd.wet_fr == 0.2


def test_configure_scenario_raises_without_a_draft(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    swat_executable = tmp_path / "rev670_64rel.exe"
    swat_executable.write_text("fake binary")

    with pytest.raises(FileNotFoundError):
        configure_scenario(project, "Buffalo_WET_MS_annual", swat_executable, "swatUser.exe")


def test_configure_scenario_refuses_to_overwrite_existing_scenario(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    init_draft(project, "Buffalo_WET_MS_annual")
    swat_executable = tmp_path / "rev670_64rel.exe"
    swat_executable.write_text("fake binary")
    configure_scenario(project, "Buffalo_WET_MS_annual", swat_executable, "swatUser.exe")

    init_draft(project, "Buffalo_WET_MS_annual")  # recreate a draft with the same name
    with pytest.raises(FileExistsError):
        configure_scenario(project, "Buffalo_WET_MS_annual", swat_executable, "swatUser.exe")
