from pathlib import Path

import pandas as pd
import pytest

from scenarios.nbs_area_batch import (
    OutputOrganizeOptions,
    parse_pct_series_text,
    scale_allocations,
    write_area_batch_step_report_csv,
)
from scenarios.nbs_area_apply import AreaAllocationPlan, SourceAllocationResult
from scenarios.nbs_mass_apply import MassAreaAllocationResult, SubbasinAreaAllocation


# -- parse_pct_series_text --------------------------------------------------


def test_parses_comma_separated_series():
    assert parse_pct_series_text("10,20,30") == [10.0, 20.0, 30.0]


def test_parses_series_up_to_100_with_whitespace():
    assert parse_pct_series_text(" 10 , 55.5 , 100 ") == [10.0, 55.5, 100.0]


def test_blank_series_raises():
    with pytest.raises(ValueError, match="empty"):
        parse_pct_series_text("")
    with pytest.raises(ValueError, match="empty"):
        parse_pct_series_text("   ")


def test_non_numeric_token_raises():
    with pytest.raises(ValueError, match="abc"):
        parse_pct_series_text("10,abc,30")


def test_out_of_range_token_raises():
    with pytest.raises(ValueError, match="out of range"):
        parse_pct_series_text("10,150")
    with pytest.raises(ValueError, match="out of range"):
        parse_pct_series_text("0,50")


# -- scale_allocations -------------------------------------------------------


def test_scale_allocations_scales_area_ha_only():
    allocations = {
        1: SubbasinAreaAllocation(area_ha=100.0, sources=[("FRST", 40.0), ("PAST", 60.0)]),
        2: SubbasinAreaAllocation(area_ha=50.0, sources=[("PAST", 100.0)]),
    }

    scaled = scale_allocations(allocations, 20.0)

    assert scaled[1].area_ha == pytest.approx(20.0)
    assert scaled[1].sources == [("FRST", 40.0), ("PAST", 60.0)]  # % relativos sin cambios
    assert scaled[2].area_ha == pytest.approx(10.0)
    # No muta el original.
    assert allocations[1].area_ha == 100.0


def test_scale_allocations_at_100_pct_is_identity():
    allocations = {1: SubbasinAreaAllocation(area_ha=42.5, sources=[("FRST", 100.0)])}

    scaled = scale_allocations(allocations, 100.0)

    assert scaled[1].area_ha == pytest.approx(42.5)


# -- write_area_batch_step_report_csv ----------------------------------------


def _plan(subbasin: int, *, source_lulc: str, requested: float, selected: float, hru_ids: list[int]) -> AreaAllocationPlan:
    plan = AreaAllocationPlan(subbasin=subbasin, total_area_ha=requested, subbasin_area_ha=1000.0)
    plan.by_source.append(
        SourceAllocationResult(
            source_lulc=source_lulc, requested_ha=requested, selected_ha=selected, selected_hru_ids=hru_ids,
        )
    )
    return plan


def test_report_has_a_row_per_subbasin_source_with_deficit(tmp_path: Path):
    result = MassAreaAllocationResult()
    result.plans.append(_plan(1, source_lulc="FRST", requested=50.0, selected=30.0, hru_ids=[1, 2]))
    result.skipped[2] = "La subcuenca no tiene ninguna HRU."

    report_path = write_area_batch_step_report_csv(tmp_path, 20.0, result)

    assert report_path.is_file()
    df = pd.read_csv(report_path)
    assert set(df["subbasin"]) == {1, 2}

    row1 = df[df["subbasin"] == 1].iloc[0]
    assert row1["source_lulc"] == "FRST"
    assert row1["requested_ha"] == pytest.approx(50.0)
    assert row1["applied_ha"] == pytest.approx(30.0)
    assert row1["deficit_ha"] == pytest.approx(20.0)
    assert row1["hru_count"] == 2
    assert row1["target_pct"] == pytest.approx(20.0)

    row2 = df[df["subbasin"] == 2].iloc[0]
    assert row2["status"] == "skipped"
    assert "ninguna HRU" in row2["notes"]


def test_output_organize_options_default_all_true():
    options = OutputOrganizeOptions()
    assert options.rch is True
    assert options.sub is True
    assert options.hru is True
