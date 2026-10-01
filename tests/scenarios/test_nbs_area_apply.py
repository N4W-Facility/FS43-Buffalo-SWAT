from swat_io.hru.parser import parse_hru_text

from scenarios.nbs_area_apply import (
    STATUS_APPLIED,
    STATUS_NO_SOURCE_HRU,
    effective_source_priority,
    load_intervention_priority,
    parse_priority_text,
    plan_area_allocation,
    plan_area_allocation_by_priority,
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


# -- effective_source_priority ---------------------------------------------------


def test_effective_source_priority_filters_and_excludes_target():
    order = ["WETL", "FRST", "PAST", "URLD"]
    real = {"FRST", "PAST", "URLD", "WETL"}

    result = effective_source_priority(order, real, target_lulc="WETL")

    assert result == ["FRST", "PAST", "URLD"]  # WETL excluido: es el target


def test_effective_source_priority_appends_unlisted_real_classes_at_the_end():
    order = ["WETL", "FRST"]
    real = {"FRST", "CORN", "SOYB"}  # CORN/SOYB no están en el archivo maestro

    result = effective_source_priority(order, real, target_lulc="WETL")

    assert result == ["FRST", "CORN", "SOYB"]  # no listadas, ordenadas alfabéticamente al final


def test_load_intervention_priority_restoration_starts_from_most_degraded():
    # Restaurar significa convertir suelo degradado, no talar bosque sano
    # -- el archivo de restoration.csv debe empezar por las coberturas
    # degradadas y dejar humedal/bosque para el final.
    order = load_intervention_priority("restoration")
    assert order.index("URLD") < order.index("PAST") < order.index("FRST") < order.index("WETL")


def test_load_intervention_priority_degradation_starts_from_best_quality():
    # Una degradación real pierde primero las coberturas de mejor calidad
    # -- degradation.csv debe empezar por humedal/bosque y dejar lo ya
    # degradado para el final.
    order = load_intervention_priority("degradation")
    assert order.index("WETL") < order.index("FRST") < order.index("PAST") < order.index("URLD")


def test_load_intervention_priority_restoration_and_degradation_are_independent_files():
    # Pedido explícito del usuario, 2026-09-30: no un solo archivo
    # invertido en memoria -- dos archivos editables por separado, que
    # podrían en principio no ser el espejo exacto uno del otro.
    restoration = load_intervention_priority("restoration")
    degradation = load_intervention_priority("degradation")
    assert restoration == list(reversed(degradation))  # hoy sí son espejo, pero por archivo, no por código


# -- plan_area_allocation_by_priority ---------------------------------------------


def test_priority_cascade_drains_first_class_before_moving_to_next():
    hru_files = _subbasin(
        _hru(1, "FRST", 0.03),  # 30 ha de 1000
        _hru(2, "PAST", 0.02),  # 20 ha de 1000
    )

    plan = plan_area_allocation_by_priority(
        1, hru_files, subbasin_area_ha=1000.0,
        total_area_ha=50.0, coverage_priority=["FRST", "PAST"],
    )

    by_lulc = {r.source_lulc: r for r in plan.by_source}
    # FRST solo tiene 30 ha -- se agota entera, y los 20 ha restantes se
    # completan desde PAST (la siguiente en la prioridad), sin que el
    # usuario haya especificado ningún %.
    assert by_lulc["FRST"].selected_ha == 30.0
    assert by_lulc["PAST"].selected_ha == 20.0
    assert plan.total_deficit_ha == 0.0


def test_priority_cascade_skips_classes_absent_from_the_subbasin_silently():
    hru_files = _subbasin(_hru(1, "PAST", 0.05))  # 50 ha de 1000

    plan = plan_area_allocation_by_priority(
        1, hru_files, subbasin_area_ha=1000.0,
        total_area_ha=50.0, coverage_priority=["WETL", "FRST", "PAST"],
    )

    # WETL/FRST no tienen HRU acá -- se saltan sin aparecer como
    # STATUS_NO_SOURCE_HRU (a diferencia del modo por %, acá es esperado).
    assert [r.source_lulc for r in plan.by_source] == ["PAST"]
    assert plan.by_source[0].selected_ha == 50.0


def test_priority_cascade_reports_deficit_when_whole_list_is_exhausted():
    hru_files = _subbasin(_hru(1, "FRST", 0.01))  # 10 ha de 1000

    plan = plan_area_allocation_by_priority(
        1, hru_files, subbasin_area_ha=1000.0,
        total_area_ha=100.0, coverage_priority=["FRST"],
    )

    result = plan.by_source[0]
    assert result.selected_ha == 10.0
    assert plan.total_deficit_ha == 90.0
    assert result.notes  # avisa que la lista se agotó sin cubrir el área


def test_priority_cascade_reports_no_source_hru_when_nothing_in_list_exists():
    hru_files = _subbasin(_hru(1, "PAST", 1.0))

    plan = plan_area_allocation_by_priority(
        1, hru_files, subbasin_area_ha=1000.0,
        total_area_ha=50.0, coverage_priority=["WETL", "FRST"],
    )

    assert len(plan.by_source) == 1
    assert plan.by_source[0].status == STATUS_NO_SOURCE_HRU
    assert plan.targets == []


def test_priority_cascade_still_applies_slope_soil_tiebreak_within_a_class():
    hru_files = _subbasin(
        _hru(1, "FRST", 0.05, slope="0-9999"),
        _hru(2, "FRST", 0.05, slope="0-9999"),
        _hru(3, "FRST", 0.50, slope="9999-9999"),
    )

    plan = plan_area_allocation_by_priority(
        1, hru_files, subbasin_area_ha=1000.0,
        total_area_ha=60.0, coverage_priority=["FRST"],
        slope_priority=["0-9999", "9999-9999"],
    )

    assert set(plan.by_source[0].selected_hru_ids) == {1, 2}
