from pathlib import Path

import pandas as pd
import pytest

from scenarios.land_cover_config import (
    discover_land_cover_options,
    parse_land_cover_batch_csv,
    write_land_cover_batch_template_csv,
)


def _write_csv(path: Path, rows: list[dict], columns: list[str] | None = None) -> Path:
    csv_path = path / "batch_config.csv"
    pd.DataFrame(rows, columns=columns).to_csv(csv_path, index=False)
    return csv_path


def test_parses_valid_config_with_all_priorities(tmp_path: Path):
    csv_path = _write_csv(
        tmp_path,
        [
            {
                "target_lulc": "FRST",
                "target_pct_series": "10,20,30",
                "donor_priority": "PAST>RNGB>AGRR",
                "slope_priority": "0-2>2-8>8-15",
                "soil_priority": "SOIL1>SOIL2",
            }
        ],
    )

    config = parse_land_cover_batch_csv(csv_path)

    assert config.target_lulc == "FRST"
    assert config.target_pct_series == [10.0, 20.0, 30.0]
    assert config.donor_priority == ["PAST", "RNGB", "AGRR"]
    assert config.slope_priority == ["0-2", "2-8", "8-15"]
    assert config.soil_priority == ["SOIL1", "SOIL2"]


def test_blank_optional_priorities_become_none(tmp_path: Path):
    csv_path = _write_csv(
        tmp_path,
        [
            {
                "target_lulc": "FRST",
                "target_pct_series": "10",
                "donor_priority": "PAST",
                "slope_priority": "",
                "soil_priority": "",
            }
        ],
    )

    config = parse_land_cover_batch_csv(csv_path)

    assert config.slope_priority is None
    assert config.soil_priority is None


def test_missing_optional_columns_entirely_become_none(tmp_path: Path):
    csv_path = _write_csv(
        tmp_path,
        [{"target_lulc": "FRST", "target_pct_series": "10", "donor_priority": "PAST"}],
    )

    config = parse_land_cover_batch_csv(csv_path)

    assert config.slope_priority is None
    assert config.soil_priority is None


def test_rejects_missing_required_columns(tmp_path: Path):
    csv_path = _write_csv(tmp_path, [{"target_lulc": "FRST", "donor_priority": "PAST"}])

    with pytest.raises(ValueError, match="target_pct_series"):
        parse_land_cover_batch_csv(csv_path)


def test_rejects_more_than_one_row(tmp_path: Path):
    csv_path = _write_csv(
        tmp_path,
        [
            {"target_lulc": "FRST", "target_pct_series": "10", "donor_priority": "PAST"},
            {"target_lulc": "WETL", "target_pct_series": "10", "donor_priority": "PAST"},
        ],
    )

    with pytest.raises(ValueError, match="una fila"):
        parse_land_cover_batch_csv(csv_path)


def test_rejects_zero_rows(tmp_path: Path):
    csv_path = _write_csv(
        tmp_path, [], columns=["target_lulc", "target_pct_series", "donor_priority"]
    )

    with pytest.raises(ValueError, match="una fila"):
        parse_land_cover_batch_csv(csv_path)


def test_rejects_empty_target_lulc(tmp_path: Path):
    csv_path = _write_csv(
        tmp_path, [{"target_lulc": "", "target_pct_series": "10", "donor_priority": "PAST"}]
    )

    with pytest.raises(ValueError, match="target_lulc"):
        parse_land_cover_batch_csv(csv_path)


def test_rejects_non_numeric_pct(tmp_path: Path):
    csv_path = _write_csv(
        tmp_path, [{"target_lulc": "FRST", "target_pct_series": "10,abc", "donor_priority": "PAST"}]
    )

    with pytest.raises(ValueError, match="abc"):
        parse_land_cover_batch_csv(csv_path)


def test_rejects_out_of_range_pct(tmp_path: Path):
    csv_path = _write_csv(
        tmp_path, [{"target_lulc": "FRST", "target_pct_series": "150", "donor_priority": "PAST"}]
    )

    with pytest.raises(ValueError, match="150"):
        parse_land_cover_batch_csv(csv_path)


def test_rejects_empty_donor_priority(tmp_path: Path):
    csv_path = _write_csv(
        tmp_path, [{"target_lulc": "FRST", "target_pct_series": "10", "donor_priority": ""}]
    )

    with pytest.raises(ValueError, match="donor_priority"):
        parse_land_cover_batch_csv(csv_path)


def test_rejects_duplicate_values_in_priority_list(tmp_path: Path):
    csv_path = _write_csv(
        tmp_path,
        [{"target_lulc": "FRST", "target_pct_series": "10", "donor_priority": "PAST>PAST"}],
    )

    with pytest.raises(ValueError, match="repetidos"):
        parse_land_cover_batch_csv(csv_path)


def test_reports_all_errors_at_once(tmp_path: Path):
    csv_path = _write_csv(
        tmp_path,
        [{"target_lulc": "", "target_pct_series": "abc", "donor_priority": ""}],
    )

    with pytest.raises(ValueError) as excinfo:
        parse_land_cover_batch_csv(csv_path)

    message = str(excinfo.value)
    assert "target_lulc" in message
    assert "abc" in message
    assert "donor_priority" in message


def _write_hru(path: Path, subbasin: int, hru: int, land_use: str, slope: str, soil: str) -> None:
    text = (
        f"Subbasin:{subbasin}   Hru:{hru}   Luse:{land_use}   Soil: {soil}   Slope: {slope}\n"
        f"        0.5000    | HRU_FR : fraction of subbasin area\n"
    )
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def txtinout_dir(tmp_path: Path) -> Path:
    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    _write_hru(txtinout / "000010001.hru", 1, 1, "FRST", "0-2", "SOIL1")
    _write_hru(txtinout / "000010002.hru", 1, 2, "PAST", "2-8", "SOIL2")
    _write_hru(txtinout / "000010003.hru", 1, 3, "AGRL", "0-2", "SOIL1")
    return txtinout


def test_discover_land_cover_options_returns_sorted_distinct_values(txtinout_dir: Path):
    land_uses, slopes, soils = discover_land_cover_options(txtinout_dir)

    assert land_uses == ["AGRL", "FRST", "PAST"]
    assert slopes == ["0-2", "2-8"]
    assert soils == ["SOIL1", "SOIL2"]


def test_template_uses_real_values_and_is_itself_a_valid_config(tmp_path: Path, txtinout_dir: Path):
    destination = tmp_path / "template.csv"

    result_path = write_land_cover_batch_template_csv(txtinout_dir, destination)

    assert result_path == destination
    config = parse_land_cover_batch_csv(destination)

    assert config.target_lulc in ("AGRL", "FRST", "PAST")
    assert config.target_pct_series == [10.0, 20.0, 30.0]
    assert config.target_lulc not in config.donor_priority
    assert config.slope_priority == ["0-2", "2-8"]
    assert config.soil_priority == ["SOIL1", "SOIL2"]


def test_template_falls_back_to_generic_values_when_project_has_no_hrus(tmp_path: Path):
    empty_txtinout = tmp_path / "TxtInOut"
    empty_txtinout.mkdir()
    destination = tmp_path / "template.csv"

    write_land_cover_batch_template_csv(empty_txtinout, destination)
    config = parse_land_cover_batch_csv(destination)

    assert config.target_lulc == "FRST"
    assert config.donor_priority == ["PAST"]
    assert config.slope_priority is None
    assert config.soil_priority is None
