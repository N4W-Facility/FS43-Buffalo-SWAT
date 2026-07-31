from pathlib import Path

import pandas as pd

from scenarios.wetland_draft import build_wetland_draft, save_wetland_draft, wetland_draft_path
from swat_io.pnd_parser import _FIELD_TO_CODE
from tests.helpers import make_synthetic_txtinout


def test_build_wetland_draft_has_one_row_per_subbasin(tmp_path: Path) -> None:
    txtinout_dir = make_synthetic_txtinout(
        tmp_path, {1: {"WET_FR": 0.1}, 2: {"WET_FR": 0.5}}
    )

    draft = build_wetland_draft(txtinout_dir)

    assert list(draft.index) == [1, 2]
    assert set(draft.columns) == set(_FIELD_TO_CODE.keys())
    assert draft.loc[1, "wet_fr"] == 0.1
    assert draft.loc[2, "wet_fr"] == 0.5


def test_save_wetland_draft_round_trips(tmp_path: Path) -> None:
    txtinout_dir = make_synthetic_txtinout(tmp_path, {1: {"WET_FR": 0.3}})
    draft = build_wetland_draft(txtinout_dir)

    result_path = save_wetland_draft(tmp_path, draft)

    assert result_path == wetland_draft_path(tmp_path)
    reloaded = pd.read_csv(result_path, index_col="subbasin_id")
    assert reloaded.loc[1, "wet_fr"] == 0.3
