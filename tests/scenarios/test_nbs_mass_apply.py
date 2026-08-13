from pathlib import Path

import pandas as pd
import pytest

from scenarios.nbs_mass_apply import (
    SubbasinAreaAllocation,
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
            {"subbasin": 1, "area_ha": 100, "FRST": "40", "PAST": "60"},
            {"subbasin": 2, "area_ha": 50, "FRST": "", "PAST": "100"},
        ],
    )

    allocations, errors = parse_mass_allocation_csv(csv_path)

    assert errors == []
    assert allocations[1] == SubbasinAreaAllocation(area_ha=100.0, sources=[("FRST", 40.0), ("PAST", 60.0)])
    assert allocations[2] == SubbasinAreaAllocation(area_ha=50.0, sources=[("PAST", 100.0)])


def test_blank_area_is_skipped_without_error(tmp_path: Path):
    csv_path = _write_csv(tmp_path, [{"subbasin": 1, "area_ha": "", "FRST": "100"}])

    allocations, errors = parse_mass_allocation_csv(csv_path)

    assert allocations == {}
    assert errors == []


def test_zero_or_negative_area_is_reported_and_row_skipped(tmp_path: Path):
    csv_path = _write_csv(tmp_path, [{"subbasin": 1, "area_ha": 0, "FRST": "100"}])

    allocations, errors = parse_mass_allocation_csv(csv_path)

    assert allocations == {}
    assert any("greater than 0" in e for e in errors)


def test_row_sum_not_equal_100_is_reported_and_skipped(tmp_path: Path):
    csv_path = _write_csv(
        tmp_path,
        [
            {"subbasin": 1, "area_ha": 100, "FRST": "70", "PAST": "50"},
            {"subbasin": 2, "area_ha": 50, "FRST": "30", "PAST": "20"},
        ],
    )

    allocations, errors = parse_mass_allocation_csv(csv_path)

    assert 1 not in allocations
    assert 2 not in allocations
    assert any("add up to" in e and "1" in e for e in errors)
    assert any("add up to" in e and "2" in e for e in errors)


def test_row_sum_under_100_is_reported_and_skipped(tmp_path: Path):
    csv_path = _write_csv(tmp_path, [{"subbasin": 1, "area_ha": 100, "FRST": "10"}])

    allocations, errors = parse_mass_allocation_csv(csv_path)

    assert 1 not in allocations
    assert any("add up to" in e for e in errors)


def test_area_with_no_coverage_cells_is_reported_and_skipped(tmp_path: Path):
    csv_path = _write_csv(tmp_path, [{"subbasin": 1, "area_ha": 100, "FRST": "", "PAST": ""}])

    allocations, errors = parse_mass_allocation_csv(csv_path)

    assert allocations == {}
    assert any("no source coverage" in e for e in errors)


def test_non_numeric_cell_is_reported_and_row_skipped(tmp_path: Path):
    csv_path = _write_csv(tmp_path, [{"subbasin": 1, "area_ha": 100, "FRST": "abc"}])

    allocations, errors = parse_mass_allocation_csv(csv_path)

    assert allocations == {}
    assert any("abc" in e for e in errors)


def test_duplicate_subbasin_row_is_reported_and_ignored(tmp_path: Path):
    csv_path = _write_csv(
        tmp_path,
        [{"subbasin": 1, "area_ha": 100, "FRST": "100"}, {"subbasin": 1, "area_ha": 50, "FRST": "100"}],
    )

    allocations, errors = parse_mass_allocation_csv(csv_path)

    assert allocations == {1: SubbasinAreaAllocation(area_ha=100.0, sources=[("FRST", 100.0)])}
    assert any("more than once" in e for e in errors)


def test_missing_subbasin_column_raises(tmp_path: Path):
    csv_path = _write_csv(tmp_path, [{"area_ha": 100, "FRST": "50"}])

    with pytest.raises(ValueError, match="subbasin"):
        parse_mass_allocation_csv(csv_path)


def test_missing_area_column_raises(tmp_path: Path):
    csv_path = _write_csv(tmp_path, [{"subbasin": 1, "FRST": "50"}])

    with pytest.raises(ValueError, match="area_ha"):
        parse_mass_allocation_csv(csv_path)


def test_no_coverage_columns_raises(tmp_path: Path):
    csv_path = _write_csv(tmp_path, [{"subbasin": 1, "area_ha": 100}])

    with pytest.raises(ValueError, match="coverage"):
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
    allocations = {
        1: SubbasinAreaAllocation(area_ha=50.0, sources=[("FRST", 100.0)]),  # FRST tiene exactamente 50 ha
        2: SubbasinAreaAllocation(area_ha=100.0, sources=[("PAST", 20.0)]),
    }

    result = plan_mass_area_allocation(txtinout_dir.parent, allocations)

    assert result.skipped == {}
    plans_by_subbasin = {p.subbasin: p for p in result.plans}
    assert plans_by_subbasin[1].total_area_ha == 50.0
    assert plans_by_subbasin[1].targets == [(1, 1)]
    assert plans_by_subbasin[2].total_area_ha == 100.0
    assert plans_by_subbasin[2].by_source[0].requested_ha == 20.0  # 20% de 100 ha (area_ha), no del área total
    assert set(result.targets) == {(1, 1), (2, 1)}


def test_subbasin_not_found_is_skipped(txtinout_dir: Path):
    allocations = {99: SubbasinAreaAllocation(area_ha=50.0, sources=[("FRST", 100.0)])}

    result = plan_mass_area_allocation(txtinout_dir.parent, allocations)

    assert result.plans == []
    assert 99 in result.skipped


def test_area_over_subbasin_real_area_is_skipped(txtinout_dir: Path):
    # La subcuenca 2 tiene solo 500 ha reales, toda PAST (ver fixture).
    allocations = {2: SubbasinAreaAllocation(area_ha=600.0, sources=[("PAST", 100.0)])}

    result = plan_mass_area_allocation(txtinout_dir.parent, allocations)

    assert result.plans == []
    assert 2 in result.skipped
    assert "exceeds the area available" in result.skipped[2]
    assert "500.00 ha" in result.skipped[2]
    assert "PAST: 500.00 ha available" in result.skipped[2]


def test_area_within_subbasin_but_over_assigned_source_availability_is_skipped(txtinout_dir: Path):
    # Subcuenca 1: FRST solo tiene 50 ha (5% de 1000 ha), aunque la
    # subcuenca completa tenga 1000 ha reales -- pedir 200 ha solo de FRST
    # no alcanza, aunque 200 ha esté muy por debajo del área total real.
    allocations = {1: SubbasinAreaAllocation(area_ha=200.0, sources=[("FRST", 100.0)])}

    result = plan_mass_area_allocation(txtinout_dir.parent, allocations)

    assert result.plans == []
    assert 1 in result.skipped
    assert "50.00 ha" in result.skipped[1]
    assert "FRST: 50.00 ha available" in result.skipped[1]


def test_priorities_are_passed_through_to_every_subbasin_plan(txtinout_dir: Path):
    allocations = {1: SubbasinAreaAllocation(area_ha=50.0, sources=[("FRST", 100.0)])}  # FRST tiene exactamente 50 ha

    result = plan_mass_area_allocation(
        txtinout_dir.parent, allocations, slope_priority=["0-9999"], soil_priority=["SOIL1"]
    )

    assert result.plans[0].by_source[0].selected_hru_ids == [1]


# -- write_mass_allocation_template_csv ------------------------------------------


def test_template_excludes_the_target_coverage_column(txtinout_dir: Path):
    destination = txtinout_dir.parent / "template.csv"

    write_mass_allocation_template_csv(txtinout_dir, destination, target_lulc="FRST")
    df = pd.read_csv(destination)

    # FRST es la cobertura objetivo de la NbS: no puede ser su propia fuente.
    assert set(df.columns) == {"subbasin", "area_ha", "PAST"}
    assert list(df["subbasin"]) == [1, 2]


def test_template_leaves_area_column_blank(txtinout_dir: Path):
    destination = txtinout_dir.parent / "template.csv"

    write_mass_allocation_template_csv(txtinout_dir, destination, target_lulc="FRST")
    df = pd.read_csv(destination, dtype=str)

    assert df["area_ha"].isna().all()


def test_template_marks_applicable_cells_with_zero_and_the_rest_blank(txtinout_dir: Path):
    destination = txtinout_dir.parent / "template.csv"

    # Objetivo PAST: FRST es la única cobertura fuente posible, y solo la
    # subcuenca 1 tiene HRU con FRST (la subcuenca 2 es 100% PAST).
    write_mass_allocation_template_csv(txtinout_dir, destination, target_lulc="PAST")
    df = pd.read_csv(destination, dtype=str)

    row1 = df[df["subbasin"] == "1"].iloc[0]
    row2 = df[df["subbasin"] == "2"].iloc[0]
    assert row1["FRST"] == "0"
    assert pd.isna(row2["FRST"])
