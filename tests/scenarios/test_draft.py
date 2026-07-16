from pathlib import Path

import pandas as pd
import pytest

from scenarios.draft import draft_csv_path, import_draft_csv, init_draft, read_draft, update_draft_value
from scenarios.models import Project
from tests.helpers import make_synthetic_txtinout

_LAYOUT = {
    "fields": [
        {"id": "wet_fr", "range": [0.0, 1.0]},
        {"id": "wet_nsa", "range": [0.0, None]},
        {"id": "wet_nvol", "range": [0.0, None]},
        {"id": "wet_mxsa", "range": [0.0, None]},
        {"id": "wet_mxvol", "range": [0.0, None]},
        {"id": "wet_vol", "range": [0.0, None]},
        {"id": "wet_k", "range": [0.0, None]},
    ]
}


def _make_project(tmp_path: Path) -> Project:
    base_dir = tmp_path / "base" / "Buffalo_calibrated_annual"
    txtinout_dir = make_synthetic_txtinout(
        base_dir,
        {
            1: {"WET_FR": 0.2, "WET_NSA": 10.0},
            2: {"WET_FR": 0.0, "WET_NSA": 0.0},
        },
    )
    project_dir = tmp_path / "workspace" / "Buffalo"
    project_dir.mkdir(parents=True)
    return Project(
        watershed="Buffalo",
        base_model_dir=base_dir,
        base_txtinout_dir=txtinout_dir,
        project_dir=project_dir,
    )


def test_init_draft_seeds_from_base_model(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    path = init_draft(project, "Buffalo_WET_MS_annual")

    assert path == draft_csv_path(project, "Buffalo_WET_MS_annual")
    draft = read_draft(path)
    assert list(draft.index) == [1, 2]
    assert draft.loc[1, "wet_fr"] == 0.2
    assert draft.loc[2, "wet_fr"] == 0.0


def test_update_draft_value_writes_valid_value(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    path = init_draft(project, "Buffalo_WET_MS_annual")

    draft = update_draft_value(path, 1, "wet_fr", 0.75, _LAYOUT)

    assert draft.loc[1, "wet_fr"] == 0.75
    assert read_draft(path).loc[1, "wet_fr"] == 0.75


def test_update_draft_value_rejects_out_of_range_and_writes_nothing(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    path = init_draft(project, "Buffalo_WET_MS_annual")

    with pytest.raises(ValueError):
        update_draft_value(path, 1, "wet_fr", 1.5, _LAYOUT)

    assert read_draft(path).loc[1, "wet_fr"] == 0.2


def test_update_draft_value_rejects_unknown_subbasin(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    path = init_draft(project, "Buffalo_WET_MS_annual")

    with pytest.raises(KeyError):
        update_draft_value(path, 999, "wet_fr", 0.5, _LAYOUT)


def test_import_draft_csv_applies_all_valid_rows(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    path = init_draft(project, "Buffalo_WET_MS_annual")

    import_path = tmp_path / "import.csv"
    pd.DataFrame(
        [
            {"subbasin_id": 1, "wet_fr": 0.5, "wet_nsa": 15.0, "wet_nvol": 0.0,
             "wet_mxsa": 0.0, "wet_mxvol": 0.0, "wet_vol": 0.0, "wet_k": 0.0},
            {"subbasin_id": 2, "wet_fr": 0.3, "wet_nsa": 5.0, "wet_nvol": 0.0,
             "wet_mxsa": 0.0, "wet_mxvol": 0.0, "wet_vol": 0.0, "wet_k": 0.0},
        ]
    ).to_csv(import_path, index=False)

    draft = import_draft_csv(path, import_path, _LAYOUT)

    assert draft.loc[1, "wet_fr"] == 0.5
    assert draft.loc[2, "wet_fr"] == 0.3
    assert read_draft(path).loc[1, "wet_nsa"] == 15.0


def test_import_draft_csv_rejects_missing_column_and_applies_nothing(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    path = init_draft(project, "Buffalo_WET_MS_annual")

    import_path = tmp_path / "import.csv"
    pd.DataFrame([{"subbasin_id": 1, "wet_fr": 0.5}]).to_csv(import_path, index=False)

    with pytest.raises(ValueError):
        import_draft_csv(path, import_path, _LAYOUT)

    assert read_draft(path).loc[1, "wet_fr"] == 0.2


def test_import_draft_csv_rejects_out_of_range_value_and_applies_nothing(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    path = init_draft(project, "Buffalo_WET_MS_annual")

    import_path = tmp_path / "import.csv"
    pd.DataFrame(
        [
            {"subbasin_id": 1, "wet_fr": 5.0, "wet_nsa": 15.0, "wet_nvol": 0.0,
             "wet_mxsa": 0.0, "wet_mxvol": 0.0, "wet_vol": 0.0, "wet_k": 0.0},
        ]
    ).to_csv(import_path, index=False)

    with pytest.raises(ValueError):
        import_draft_csv(path, import_path, _LAYOUT)

    assert read_draft(path).loc[1, "wet_fr"] == 0.2
