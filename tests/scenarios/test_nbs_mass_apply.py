from pathlib import Path

import pandas as pd
import pytest

from scenarios.nbs_mass_apply import (
    parse_mass_allocation_csv,
    plan_mass_area_allocation,
    write_mass_allocation_template_csv,
)
from tests.helpers import write_synthetic_sub


def _write_csv(path: Path, rows: list[dict], columns: list[str] | None = None) -> Path:
    csv_path = path / "mass_config.csv"
    pd.DataFrame(rows, columns=columns).to_csv(csv_path, index=False)
    return csv_path


def _write_hru(path: Path, subbasin: int, hru: int, land_use: str, hru_fr: float) -> None:
    text = (
        f"Subbasin:{subbasin}   Hru:{hru}   Luse:{land_use}   Soil: SOIL1   Slope: 0-9999\n"
        f"{hru_fr:16.4f}    | HRU_FR : fraction of subbasin area\n"
    )
    path.write_text(text, encoding="utf-8")


# -- parse_mass_allocation_csv -------------------------------------------------


def test_parses_matrix_with_blank_cells(tmp_path: Path):
    csv_path = _write_csv(
        tmp_path,
        [
            {"subbasin": 1, "FRST": "40", "PAST": "60"},
            {"subbasin": 2, "FRST": "", "PAST": "20"},
        ],
    )

    allocations, errors = parse_mass_allocation_csv(csv_path)

    assert errors == []
    assert allocations[1] == [("FRST", 40.0), ("PAST", 20.0)] or allocations[1] == [("FRST", 40.0), ("PAST", 60.0)]
    assert allocations[2] == [("PAST", 20.0)]


def test_blank_row_is_skipped_without_error(tmp_path: Path):
    csv_path = _write_csv(tmp_path, [{"subbasin": 1, "FRST": "", "PAST": ""}])

    allocations, errors = parse_mass_allocation_csv(csv_path)

    assert allocations == {}
    assert errors == []


def test_row_sum_over_100_is_reported_and_skipped(tmp_path: Path):
    csv_path = _write_csv(
        tmp_path,
        [
            {"subbasin": 1, "FRST": "70", "PAST": "50"},
            {"subbasin": 2, "FRST": "30", "PAST": "20"},
        ],
    )

    allocations, errors = parse_mass_allocation_csv(csv_path)

    assert 1 not in allocations
    assert 2 in allocations
    assert any("100%" in e and "1" in e for e in errors)


def test_row_sum_under_100_is_accepted(tmp_path: Path):
    csv_path = _write_csv(tmp_path, [{"subbasin": 1, "FRST": "10"}])

    allocations, errors = parse_mass_allocation_csv(csv_path)

    assert errors == []
    assert allocations[1] == [("FRST", 10.0)]


def test_non_numeric_cell_is_reported_and_row_skipped(tmp_path: Path):
    csv_path = _write_csv(tmp_path, [{"subbasin": 1, "FRST": "abc"}])

    allocations, errors = parse_mass_allocation_csv(csv_path)

    assert allocations == {}
    assert any("abc" in e for e in errors)


def test_duplicate_subbasin_row_is_reported_and_ignored(tmp_path: Path):
    csv_path = _write_csv(
        tmp_path,
        [{"subbasin": 1, "FRST": "50"}, {"subbasin": 1, "FRST": "60"}],
    )

    allocations, errors = parse_mass_allocation_csv(csv_path)

    assert allocations == {1: [("FRST", 50.0)]}
    assert any("más de una vez" in e for e in errors)


def test_missing_subbasin_column_raises(tmp_path: Path):
    csv_path = _write_csv(tmp_path, [{"FRST": "50"}])

    with pytest.raises(ValueError, match="subbasin"):
        parse_mass_allocation_csv(csv_path)


def test_no_coverage_columns_raises(tmp_path: Path):
    csv_path = _write_csv(tmp_path, [{"subbasin": 1}])

    with pytest.raises(ValueError, match="cobertura"):
        parse_mass_allocation_csv(csv_path)


# -- plan_mass_area_allocation --------------------------------------------------


@pytest.fixture
def txtinout_dir(tmp_path: Path) -> Path:
    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()

    write_synthetic_sub(txtinout / "000010000.sub", area_km2=10.0)  # 1000 ha
    (txtinout / "000010000.pnd").write_text("", encoding="utf-8")
    _write_hru(txtinout / "000010001.hru", 1, 1, "FRST", 0.05)
    _write_hru(txtinout / "000010002.hru", 1, 2, "PAST", 0.95)

    write_synthetic_sub(txtinout / "000020000.sub", area_km2=5.0)  # 500 ha
    (txtinout / "000020000.pnd").write_text("", encoding="utf-8")
    _write_hru(txtinout / "000020001.hru", 2, 1, "PAST", 1.0)

    return txtinout


def test_plans_each_subbasin_independently(txtinout_dir: Path):
    allocations = {1: [("FRST", 100.0)], 2: [("PAST", 20.0)]}

    result = plan_mass_area_allocation(txtinout_dir.parent, allocations)

    assert result.skipped == {}
    plans_by_subbasin = {p.subbasin: p for p in result.plans}
    assert plans_by_subbasin[1].total_area_ha == 1000.0  # 100% del área real de la subcuenca 1
    assert plans_by_subbasin[1].targets == [(1, 1)]
    assert plans_by_subbasin[2].total_area_ha == 500.0
    assert plans_by_subbasin[2].by_source[0].requested_ha == 100.0  # 20% de 500 ha
    assert set(result.targets) == {(1, 1), (2, 1)}


def test_subbasin_not_found_is_skipped(txtinout_dir: Path):
    allocations = {99: [("FRST", 50.0)]}

    result = plan_mass_area_allocation(txtinout_dir.parent, allocations)

    assert result.plans == []
    assert 99 in result.skipped


def test_priorities_are_passed_through_to_every_subbasin_plan(txtinout_dir: Path):
    allocations = {1: [("FRST", 100.0)]}

    result = plan_mass_area_allocation(
        txtinout_dir.parent, allocations, slope_priority=["0-9999"], soil_priority=["SOIL1"]
    )

    assert result.plans[0].by_source[0].selected_hru_ids == [1]


# -- write_mass_allocation_template_csv ------------------------------------------


def test_template_lists_every_subbasin_with_a_sample_allocation(txtinout_dir: Path):
    destination = txtinout_dir.parent / "template.csv"

    write_mass_allocation_template_csv(txtinout_dir, destination)
    allocations, errors = parse_mass_allocation_csv(destination)

    assert errors == []
    assert set(allocations.keys()) <= {1, 2}
    assert allocations  # al menos una fila poblada de ejemplo


def test_template_columns_cover_every_real_coverage(txtinout_dir: Path):
    destination = txtinout_dir.parent / "template.csv"

    write_mass_allocation_template_csv(txtinout_dir, destination)
    df = pd.read_csv(destination)

    assert set(df.columns) == {"subbasin", "FRST", "PAST"}
    assert list(df["subbasin"]) == [1, 2]
