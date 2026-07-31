from pathlib import Path

import pytest

from engine.configure import apply_draft_to_pnd, create_working_scenario
from scenarios.draft import init_draft, read_draft, update_draft_value
from swat_io.pnd_parser import parse_pnd_file
from tests.helpers import make_synthetic_txtinout

_LAYOUT = {"fields": [{"id": "wet_fr", "range": [0.0, 1.0]}]}


def test_create_working_scenario_copies_whole_reference_folder(tmp_path: Path) -> None:
    reference_dir = tmp_path / "Buffalo_calibrated_annual"
    make_synthetic_txtinout(reference_dir, {1: {"WET_FR": 0.2}})
    (reference_dir / "TablesIn").mkdir()
    (reference_dir / "TablesOut").mkdir()
    project_dir = tmp_path / "workspace" / "Buffalo"
    project_dir.mkdir(parents=True)

    scenario_dir = create_working_scenario(project_dir, reference_dir, "Buffalo_WET_MS_annual")

    assert scenario_dir == project_dir / "Buffalo_WET_MS_annual"
    assert (scenario_dir / "TxtInOut" / "000010000.pnd").exists()
    assert (scenario_dir / "TablesIn").is_dir()
    assert (scenario_dir / "TablesOut").is_dir()
    # reference untouched
    reference_pnd = parse_pnd_file(reference_dir / "TxtInOut" / "000010000.pnd", subbasin_id=1)
    assert reference_pnd.wet_fr == 0.2


def test_create_working_scenario_reports_progress(tmp_path: Path) -> None:
    reference_dir = tmp_path / "Buffalo_calibrated_annual"
    make_synthetic_txtinout(reference_dir, {1: {"WET_FR": 0.2}, 2: {"WET_FR": 0.0}})
    project_dir = tmp_path / "workspace" / "Buffalo"
    project_dir.mkdir(parents=True)
    calls: list[tuple[int, int]] = []

    create_working_scenario(
        project_dir, reference_dir, "Buffalo_WET_MS_annual",
        on_progress=lambda copied, total: calls.append((copied, total)),
    )

    assert calls
    total = calls[0][1]
    assert all(total_files == total for _, total_files in calls)
    assert calls[-1][0] == total
    assert [copied for copied, _ in calls] == sorted(copied for copied, _ in calls)


def test_create_working_scenario_refuses_to_overwrite_existing(tmp_path: Path) -> None:
    reference_dir = tmp_path / "Buffalo_calibrated_annual"
    make_synthetic_txtinout(reference_dir, {1: {"WET_FR": 0.2}})
    project_dir = tmp_path / "workspace" / "Buffalo"
    project_dir.mkdir(parents=True)
    create_working_scenario(project_dir, reference_dir, "Buffalo_WET_MS_annual")

    with pytest.raises(FileExistsError):
        create_working_scenario(project_dir, reference_dir, "Buffalo_WET_MS_annual")


def test_apply_draft_to_pnd_writes_edited_values_only_to_working_copy(tmp_path: Path) -> None:
    reference_dir = tmp_path / "Buffalo_calibrated_annual"
    make_synthetic_txtinout(reference_dir, {1: {"WET_FR": 0.2}, 2: {"WET_FR": 0.0}})
    project_dir = tmp_path / "workspace" / "Buffalo"
    project_dir.mkdir(parents=True)
    scenario_dir = create_working_scenario(project_dir, reference_dir, "Buffalo_WET_MS_annual")
    txtinout_dir = scenario_dir / "TxtInOut"
    draft_path = init_draft(project_dir, "Buffalo_WET_MS_annual", txtinout_dir)
    update_draft_value(draft_path, 1, "wet_fr", 0.9, _LAYOUT)
    draft = read_draft(draft_path)

    apply_draft_to_pnd(txtinout_dir, draft)

    updated = parse_pnd_file(txtinout_dir / "000010000.pnd", subbasin_id=1)
    assert updated.wet_fr == 0.9
    unchanged = parse_pnd_file(txtinout_dir / "000020000.pnd", subbasin_id=2)
    assert unchanged.wet_fr == 0.0
    # reference still untouched
    reference_pnd = parse_pnd_file(reference_dir / "TxtInOut" / "000010000.pnd", subbasin_id=1)
    assert reference_pnd.wet_fr == 0.2
