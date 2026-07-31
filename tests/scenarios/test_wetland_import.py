from pathlib import Path

import pandas as pd
import pytest

from config.settings import ConfigManager
from scenarios.wetland_import import parse_wetland_import_csv


@pytest.fixture
def layout() -> dict:
    return ConfigManager().load_layout("wetland_params")


def _write_csv(path: Path, rows: list[dict]) -> Path:
    csv_path = path / "import.csv"
    pd.DataFrame(rows).set_index("subbasin_id").to_csv(csv_path)
    return csv_path


def test_parses_partial_subset_of_subbasins_and_fields(tmp_path: Path, layout: dict) -> None:
    csv_path = _write_csv(tmp_path, [{"subbasin_id": 1, "wet_fr": 0.4}])

    result = parse_wetland_import_csv(csv_path, [1, 2], layout)

    assert result == {1: {"wet_fr": 0.4}}


def test_matches_summary_column_names_with_unit_suffixes(tmp_path: Path, layout: dict) -> None:
    csv_path = _write_csv(
        tmp_path, [{"subbasin_id": 1, "area_km2": 12.0, "wet_nsa_ha": 3.5, "wet_mxvol_104m3": 7.0}]
    )

    result = parse_wetland_import_csv(csv_path, [1], layout)

    assert result == {1: {"wet_nsa": 3.5, "wet_mxvol": 7.0}}


def test_rejects_unknown_column(tmp_path: Path, layout: dict) -> None:
    csv_path = _write_csv(tmp_path, [{"subbasin_id": 1, "not_a_field": 1.0}])

    with pytest.raises(ValueError, match="not_a_field"):
        parse_wetland_import_csv(csv_path, [1], layout)


def test_rejects_unknown_subbasin(tmp_path: Path, layout: dict) -> None:
    csv_path = _write_csv(tmp_path, [{"subbasin_id": 99, "wet_fr": 0.4}])

    with pytest.raises(ValueError, match="99"):
        parse_wetland_import_csv(csv_path, [1], layout)


def test_rejects_out_of_range_value(tmp_path: Path, layout: dict) -> None:
    csv_path = _write_csv(tmp_path, [{"subbasin_id": 1, "wet_fr": 1.5}])  # rango [0.0, 1.0]

    with pytest.raises(ValueError, match="1.5"):
        parse_wetland_import_csv(csv_path, [1], layout)


def test_rejects_non_numeric_value(tmp_path: Path, layout: dict) -> None:
    csv_path = _write_csv(tmp_path, [{"subbasin_id": 1, "wet_fr": "abc"}])

    with pytest.raises(ValueError, match="abc"):
        parse_wetland_import_csv(csv_path, [1], layout)


def test_reports_all_errors_at_once(tmp_path: Path, layout: dict) -> None:
    csv_path = _write_csv(
        tmp_path, [{"subbasin_id": 1, "wet_fr": "abc"}, {"subbasin_id": 99, "wet_fr": 0.4}]
    )

    with pytest.raises(ValueError) as excinfo:
        parse_wetland_import_csv(csv_path, [1], layout)

    message = str(excinfo.value)
    assert "abc" in message
    assert "99" in message
