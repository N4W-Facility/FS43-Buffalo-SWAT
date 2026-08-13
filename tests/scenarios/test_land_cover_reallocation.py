from swat_io.hru.parser import parse_hru_text

from scenarios.land_cover_reallocation import (
    STATUS_APPLIED,
    STATUS_SKIPPED_NO_TARGET_HRU,
    STATUS_SKIPPED_TARGET_ALREADY_MET,
    plan_batch_reallocation,
    plan_subbasin_reallocation,
)


def _hru(hru_id: int, land_use: str, hru_fr: float, *, slope: str = "0-9999", soil: str = "SOIL1"):
    text = (
        f"Subbasin:1   Hru:{hru_id}   Luse:{land_use}   Soil: {soil}   Slope: {slope}\n"
        f"{hru_fr:16.4f}    | HRU_FR : fraction of subbasin area\n"
    )
    return parse_hru_text(text)


def _subbasin(*hrus) -> dict[int, object]:
    return {hru.metadata.hru: hru for hru in hrus}


def test_grows_target_and_reduces_single_donor_proportionally():
    hru_files = _subbasin(
        _hru(1, "FRST", 0.10),
        _hru(2, "PAST", 0.90),
    )

    result = plan_subbasin_reallocation(
        1, hru_files, target_lulc="FRST", target_pct=30, donor_priority=["PAST"]
    )

    assert result.status == STATUS_APPLIED
    assert result.current_target_pct == 10.0
    assert result.new_hru_fr[1] == 0.30
    assert round(result.new_hru_fr[2], 10) == 0.70
    assert result.notes == []


def test_skips_subbasin_without_target_coverage():
    hru_files = _subbasin(
        _hru(1, "PAST", 0.50),
        _hru(2, "AGRL", 0.50),
    )

    result = plan_subbasin_reallocation(
        1, hru_files, target_lulc="FRST", target_pct=10, donor_priority=["PAST", "AGRL"]
    )

    assert result.status == STATUS_SKIPPED_NO_TARGET_HRU
    assert result.new_hru_fr == {}


def test_skips_subbasin_when_target_already_met():
    hru_files = _subbasin(
        _hru(1, "FRST", 0.15),
        _hru(2, "PAST", 0.85),
    )

    result = plan_subbasin_reallocation(
        1, hru_files, target_lulc="FRST", target_pct=10, donor_priority=["PAST"]
    )

    assert result.status == STATUS_SKIPPED_TARGET_ALREADY_MET
    assert result.current_target_pct == 15.0
    assert result.new_hru_fr == {}


def test_donor_priority_cascade_exhausts_first_group_before_second():
    hru_files = _subbasin(
        _hru(1, "FRST", 0.10),
        _hru(2, "PAST", 0.05),
        _hru(3, "AGRL", 0.85),
    )

    result = plan_subbasin_reallocation(
        1, hru_files, target_lulc="FRST", target_pct=30, donor_priority=["PAST", "AGRL"]
    )

    assert result.status == STATUS_APPLIED
    # PAST (0.05) se agota por completo antes de tocar AGRL.
    assert result.new_hru_fr[2] == 0.0
    # Necesita 0.20 en total; ya sacó 0.05 de PAST, faltan 0.15 de AGRL.
    assert round(result.new_hru_fr[3], 10) == 0.70
    assert round(result.new_hru_fr[1], 10) == 0.30


def test_donors_without_priority_split_proportionally_within_tied_group():
    hru_files = _subbasin(
        _hru(1, "FRST", 0.00),
        _hru(2, "PAST", 0.30),
        _hru(3, "PAST", 0.70),
    )

    result = plan_subbasin_reallocation(
        1, hru_files, target_lulc="FRST", target_pct=10, donor_priority=["PAST"]
    )

    assert result.status == STATUS_APPLIED
    # Necesita 0.10 de PAST, repartido proporcional a su peso (0.30/1.00 y 0.70/1.00).
    assert round(result.new_hru_fr[2], 10) == 0.27
    assert round(result.new_hru_fr[3], 10) == 0.63
    assert round(result.new_hru_fr[1], 10) == 0.10


def test_unlisted_donor_coverage_is_lowest_priority():
    hru_files = _subbasin(
        _hru(1, "FRST", 0.10),
        _hru(2, "PAST", 0.10),
        _hru(3, "AGRL", 0.80),
    )

    # Solo se prioriza PAST explícitamente; AGRL (no listado) es donante
    # de último recurso y solo se toca si PAST no alcanza.
    result = plan_subbasin_reallocation(
        1, hru_files, target_lulc="FRST", target_pct=15, donor_priority=["PAST"]
    )

    assert result.status == STATUS_APPLIED
    assert round(result.new_hru_fr[2], 10) == 0.05
    assert 3 not in result.new_hru_fr


def test_slope_priority_selects_donor_group_before_coverage_wide_proportional():
    hru_files = _subbasin(
        _hru(1, "FRST", 0.10),
        _hru(2, "PAST", 0.20, slope="0-2"),
        _hru(3, "PAST", 0.70, slope="2-8"),
    )

    result = plan_subbasin_reallocation(
        1,
        hru_files,
        target_lulc="FRST",
        target_pct=25,
        donor_priority=["PAST"],
        slope_priority=["0-2", "2-8"],
    )

    assert result.status == STATUS_APPLIED
    # Necesita 0.15; el grupo de pendiente 0-2 (HRU 2, 0.20) alcanza solo.
    assert round(result.new_hru_fr[2], 10) == 0.05
    assert 3 not in result.new_hru_fr


def test_growth_priority_concentrates_all_new_area_in_first_group():
    hru_files = _subbasin(
        _hru(1, "FRST", 0.05, slope="0-2"),
        _hru(2, "FRST", 0.05, slope="2-8"),
        _hru(3, "PAST", 0.90),
    )

    result = plan_subbasin_reallocation(
        1,
        hru_files,
        target_lulc="FRST",
        target_pct=20,
        donor_priority=["PAST"],
        slope_priority=["0-2", "2-8"],
    )

    assert result.status == STATUS_APPLIED
    # Todo el crecimiento (0.10) va a la HRU 1 (pendiente 0-2), la HRU 2 no cambia.
    assert round(result.new_hru_fr[1], 10) == 0.15
    assert 2 not in result.new_hru_fr
    assert round(result.new_hru_fr[3], 10) == 0.80


def test_growth_without_priority_splits_proportionally_across_target_hrus():
    hru_files = _subbasin(
        _hru(1, "FRST", 0.10),
        _hru(2, "FRST", 0.30),
        _hru(3, "PAST", 0.60),
    )

    result = plan_subbasin_reallocation(
        1, hru_files, target_lulc="FRST", target_pct=60, donor_priority=["PAST"]
    )

    assert result.status == STATUS_APPLIED
    # Necesita 0.20 repartido proporcional entre FRST (0.10 y 0.30, total 0.40).
    assert round(result.new_hru_fr[1], 10) == 0.15
    assert round(result.new_hru_fr[2], 10) == 0.45
    assert round(result.new_hru_fr[3], 10) == 0.40


def test_insufficient_donor_area_applies_best_effort_and_reports_note():
    hru_files = _subbasin(
        _hru(1, "FRST", 0.10),
        _hru(2, "PAST", 0.05),
    )

    result = plan_subbasin_reallocation(
        1, hru_files, target_lulc="FRST", target_pct=50, donor_priority=["PAST"]
    )

    assert result.status == STATUS_APPLIED
    assert result.new_hru_fr[2] == 0.0
    # Solo pudo crecer lo que PAST tenía disponible (0.05).
    assert round(result.new_hru_fr[1], 10) == 0.15
    assert len(result.notes) == 1
    assert "short by" in result.notes[0]
    # Pidió 50% - 10% actual = 40 puntos porcentuales; PAST solo tenía 5.
    assert round(result.deficit_pct, 4) == 35.0


def test_deficit_pct_is_zero_when_fully_applied():
    hru_files = _subbasin(
        _hru(1, "FRST", 0.10),
        _hru(2, "PAST", 0.90),
    )

    result = plan_subbasin_reallocation(
        1, hru_files, target_lulc="FRST", target_pct=30, donor_priority=["PAST"]
    )

    assert result.deficit_pct == 0.0


def test_plan_batch_reallocation_runs_each_subbasin_independently_and_sorted():
    subbasin_1 = _subbasin(_hru(1, "FRST", 0.10), _hru(2, "PAST", 0.90))
    subbasin_2 = _subbasin(_hru(1, "PAST", 1.00))

    results = plan_batch_reallocation(
        {2: subbasin_2, 1: subbasin_1},
        target_lulc="FRST",
        target_pct=20,
        donor_priority=["PAST"],
    )

    assert [r.subbasin for r in results] == [1, 2]
    assert results[0].status == STATUS_APPLIED
    assert results[1].status == STATUS_SKIPPED_NO_TARGET_HRU
