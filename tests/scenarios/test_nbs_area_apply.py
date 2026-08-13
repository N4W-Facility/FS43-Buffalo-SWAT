from swat_io.hru.parser import parse_hru_text

from scenarios.nbs_area_apply import (
    STATUS_APPLIED,
    STATUS_NO_SOURCE_HRU,
    parse_priority_text,
    plan_area_allocation,
    subbasin_land_uses,
    validate_source_allocations,
)


def _hru(hru_id: int, land_use: str, hru_fr: float, *, slope: str = "0-9999", soil: str = "SOIL1"):
    text = (
        f"Subbasin:1   Hru:{hru_id}   Luse:{land_use}   Soil: {soil}   Slope: {slope}\n"
        f"{hru_fr:16.4f}    | HRU_FR : fraction of subbasin area\n"
    )
    return parse_hru_text(text)


def _subbasin(*hrus) -> dict[int, object]:
    return {hru.metadata.hru: hru for hru in hrus}


def test_selects_whole_hrus_until_target_area_covered():
    hru_files = _subbasin(
        _hru(1, "FRST", 0.05),
        _hru(2, "FRST", 0.05),
        _hru(3, "PAST", 0.90),
    )

    plan = plan_area_allocation(
        1, hru_files, subbasin_area_ha=1000.0,
        total_area_ha=100.0, source_allocations=[("FRST", 100.0)],
    )

    assert len(plan.by_source) == 1
    result = plan.by_source[0]
    assert result.status == STATUS_APPLIED
    assert result.requested_ha == 100.0
    # 0.05 + 0.05 = 0.10 de 1000 ha = 100 ha, ambas HRU completas se toman
    # porque ninguna sola alcanza los 100 ha pedidos.
    assert set(result.selected_hru_ids) == {1, 2}
    assert result.selected_ha == 100.0
    assert plan.targets == [(1, 1), (1, 2)]


def test_splits_total_area_across_multiple_source_coverages():
    hru_files = _subbasin(
        _hru(1, "FRST", 0.40),
        _hru(2, "PAST", 0.60),
    )

    plan = plan_area_allocation(
        1, hru_files, subbasin_area_ha=1000.0,
        total_area_ha=100.0, source_allocations=[("FRST", 40.0), ("PAST", 60.0)],
    )

    by_lulc = {r.source_lulc: r for r in plan.by_source}
    assert by_lulc["FRST"].requested_ha == 40.0
    assert by_lulc["FRST"].selected_hru_ids == [1]
    assert by_lulc["PAST"].requested_ha == 60.0
    assert by_lulc["PAST"].selected_hru_ids == [2]
    assert set(plan.targets) == {(1, 1), (1, 2)}


def test_reports_deficit_when_not_enough_source_area_available():
    hru_files = _subbasin(_hru(1, "FRST", 0.02))  # 20 ha de 1000

    plan = plan_area_allocation(
        1, hru_files, subbasin_area_ha=1000.0,
        total_area_ha=100.0, source_allocations=[("FRST", 100.0)],
    )

    result = plan.by_source[0]
    assert result.selected_ha == 20.0
    assert result.deficit_ha == 80.0
    assert result.notes  # avisa el déficit
    assert plan.total_deficit_ha == 80.0


def test_skips_source_coverage_with_no_candidate_hru():
    hru_files = _subbasin(_hru(1, "PAST", 1.0))

    plan = plan_area_allocation(
        1, hru_files, subbasin_area_ha=1000.0,
        total_area_ha=50.0, source_allocations=[("FRST", 100.0)],
    )

    result = plan.by_source[0]
    assert result.status == STATUS_NO_SOURCE_HRU
    assert result.selected_hru_ids == []
    assert plan.targets == []


def test_slope_priority_group_is_exhausted_before_the_next():
    hru_files = _subbasin(
        _hru(1, "FRST", 0.05, slope="0-9999"),
        _hru(2, "FRST", 0.05, slope="0-9999"),
        _hru(3, "FRST", 0.50, slope="9999-9999"),
    )

    plan = plan_area_allocation(
        1, hru_files, subbasin_area_ha=1000.0,
        total_area_ha=60.0, source_allocations=[("FRST", 100.0)],
        slope_priority=["0-9999", "9999-9999"],
    )

    result = plan.by_source[0]
    # El grupo de menor pendiente (0-9999) suma 100 ha (HRU 1+2), ya cubre
    # los 60 ha pedidos sin tocar la HRU del otro grupo de pendiente.
    assert set(result.selected_hru_ids) == {1, 2}


def test_a_hru_selected_for_one_source_coverage_is_never_reused():
    # Cada HRU pertenece a una sola cobertura, así que esto es más una
    # garantía de invariante que un caso realista, pero confirma que
    # already_selected no se comparte incorrectamente entre coberturas.
    hru_files = _subbasin(_hru(1, "FRST", 1.0))

    plan = plan_area_allocation(
        1, hru_files, subbasin_area_ha=1000.0,
        total_area_ha=100.0, source_allocations=[("FRST", 50.0), ("FRST", 50.0)],
    )

    # La segunda entrada de "FRST" no encuentra candidatas libres.
    assert plan.by_source[0].selected_hru_ids == [1]
    assert plan.by_source[1].status == STATUS_NO_SOURCE_HRU


def test_validate_source_allocations_requires_100_percent_total():
    errors = validate_source_allocations([("FRST", 40.0), ("PAST", 40.0)])
    assert any("add up to 100" in e for e in errors)


def test_validate_source_allocations_rejects_duplicates_and_non_positive():
    errors = validate_source_allocations([("FRST", 0.0), ("FRST", 100.0)])
    assert any("Repeated" in e for e in errors)
    assert any("greater than 0" in e for e in errors)


def test_validate_source_allocations_accepts_well_formed_list():
    assert validate_source_allocations([("FRST", 40.0), ("PAST", 60.0)]) == []


def test_parse_priority_text():
    assert parse_priority_text(None) is None
    assert parse_priority_text("  ") is None
    assert parse_priority_text("PAST>RNGB> AGRR ") == ["PAST", "RNGB", "AGRR"]


def test_subbasin_land_uses_lists_distinct_sorted_coverages():
    hru_files = _subbasin(_hru(1, "PAST", 0.5), _hru(2, "FRST", 0.5))
    assert subbasin_land_uses(hru_files) == ["FRST", "PAST"]
