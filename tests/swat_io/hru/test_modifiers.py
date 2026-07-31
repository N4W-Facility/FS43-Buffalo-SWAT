from pathlib import Path

import pytest

from swat_io.hru.exceptions import HRUModificationError
from swat_io.hru.modifiers import (
    HRUModificationRule,
    HRUSelection,
    apply_modifications,
    preview_modifications,
    write_modified_hru_files,
)
from swat_io.hru.parser import parse_hru_file, parse_hru_text

from tests.swat_io.hru.conftest import fixture_path


def _load(*names: str):
    return [parse_hru_file(fixture_path(name)) for name in names]


def test_apply_modifications_changes_only_selected_value() -> None:
    [hru] = _load("000010001.hru")
    rule = HRUModificationRule(parameter="CANMX", new_value=12.5, selection=HRUSelection())

    apply_modifications([hru], [rule])

    assert hru.get_value("CANMX") == pytest.approx(12.5)


def test_apply_modifications_does_not_change_parameter_name() -> None:
    [hru] = _load("000010001.hru")
    rule = HRUModificationRule(parameter="canmx", new_value=12.5, selection=HRUSelection())

    apply_modifications([hru], [rule])

    param = hru.get_parameter("CANMX")
    assert param.parameter_name == "CANMX"  # nombre original, sin alterar


def test_apply_modifications_does_not_change_description() -> None:
    [hru] = _load("000010001.hru")
    param_before = hru.get_parameter("CANMX")
    description_before = param_before.description
    rule = HRUModificationRule(parameter="CANMX", new_value=99.0, selection=HRUSelection())

    apply_modifications([hru], [rule])

    assert hru.get_parameter("CANMX").description == description_before


def test_apply_modifications_does_not_change_neighboring_parameters() -> None:
    [hru] = _load("000010001.hru")
    esco_before = hru.get_parameter("ESCO").raw_value
    rule = HRUModificationRule(parameter="CANMX", new_value=99.0, selection=HRUSelection())

    apply_modifications([hru], [rule])

    assert hru.get_parameter("ESCO").raw_value == esco_before
    assert hru.get_parameter("ESCO").modified is False


def test_apply_modifications_preserves_precision_of_untouched_values() -> None:
    [hru] = _load("000010001.hru")
    rsdin_before = hru.get_parameter("RSDIN").raw_value
    rule = HRUModificationRule(parameter="CANMX", new_value=99.0, selection=HRUSelection())

    apply_modifications([hru], [rule])

    assert hru.get_parameter("RSDIN").raw_value == rsdin_before


def test_apply_modifications_expands_field_when_value_does_not_fit() -> None:
    hru = parse_hru_text("   0.7500    | HRU_FR : Fraction of subbasin area\n")
    original_width = len(hru.get_parameter("HRU_FR").raw_value)
    rule = HRUModificationRule(parameter="HRU_FR", new_value=123456.789, selection=HRUSelection())

    apply_modifications([hru], [rule])

    new_raw_value = hru.get_parameter("HRU_FR").raw_value
    assert len(new_raw_value) > original_width
    assert new_raw_value.strip() == "123456.7890"


def test_apply_modifications_reports_missing_parameter() -> None:
    [hru] = _load("000010001.hru")
    rule = HRUModificationRule(parameter="DOES_NOT_EXIST", new_value=1.0, selection=HRUSelection())

    changes = apply_modifications([hru], [rule])

    assert len(changes) == 1
    assert changes[0].status == "PARAMETER_NOT_FOUND"
    assert changes[0].old_value is None


def test_preview_modifications_does_not_mutate_original_object() -> None:
    [hru] = _load("000010001.hru")
    original_raw_value = hru.get_parameter("CANMX").raw_value
    rule = HRUModificationRule(parameter="CANMX", new_value=42.0, selection=HRUSelection())

    changes = preview_modifications([hru], [rule])

    assert hru.get_parameter("CANMX").raw_value == original_raw_value
    assert hru.get_parameter("CANMX").modified is False
    assert changes[0].new_value == 42.0
    assert changes[0].old_value == pytest.approx(1.0)


def test_preview_modifications_does_not_write_to_disk(tmp_path: Path) -> None:
    [hru] = _load("000010001.hru")
    rule = HRUModificationRule(parameter="CANMX", new_value=42.0, selection=HRUSelection())

    preview_modifications([hru], [rule])

    # source_path sigue siendo el fixture original; si se hubiese escrito
    # algo, este archivo tendría el nuevo valor.
    reloaded = parse_hru_file(hru.source_path)
    assert reloaded.get_value("CANMX") == pytest.approx(1.0)


def test_rule_filters_by_subbasin() -> None:
    hru_files = _load("000010001.hru", "000030003_duplicate.hru")  # subbasin 1, 3
    rule = HRUModificationRule(
        parameter="SLSUBBSN", new_value=1.0, selection=HRUSelection(subbasins=frozenset({1}))
    )

    changes = apply_modifications(hru_files, [rule])

    assert len(changes) == 1
    assert changes[0].subbasin == 1


def test_rule_filters_by_hru() -> None:
    hru_files = _load("000010001.hru", "000030003_duplicate.hru")  # hru 1, hru 3
    rule = HRUModificationRule(
        parameter="SLSUBBSN", new_value=1.0, selection=HRUSelection(hrus=frozenset({3}))
    )

    changes = apply_modifications(hru_files, [rule])

    assert len(changes) == 1
    assert changes[0].hru == 3


def test_rule_filters_by_land_use() -> None:
    hru_files = _load("000010001.hru", "000030003_duplicate.hru")  # AGRL, PAST
    rule = HRUModificationRule(
        parameter="SLSUBBSN", new_value=1.0, selection=HRUSelection(land_uses=frozenset({"PAST"}))
    )

    changes = apply_modifications(hru_files, [rule])

    assert len(changes) == 1
    assert changes[0].land_use == "PAST"


def test_multiple_rules_produce_full_change_log() -> None:
    [hru] = _load("000010001.hru")
    rules = [
        HRUModificationRule(parameter="CANMX", new_value=5.0, selection=HRUSelection()),
        HRUModificationRule(parameter="ESCO", new_value=0.8, selection=HRUSelection()),
        HRUModificationRule(parameter="DOES_NOT_EXIST", new_value=1.0, selection=HRUSelection()),
    ]

    changes = apply_modifications([hru], rules)

    assert len(changes) == 3
    statuses = {c.parameter: c.status for c in changes}
    assert statuses["CANMX"] == "MODIFIED"
    assert statuses["ESCO"] == "MODIFIED"
    assert statuses["DOES_NOT_EXIST"] == "PARAMETER_NOT_FOUND"


def test_write_modified_hru_files_mirrors_relative_structure(tmp_path: Path) -> None:
    source_root = tmp_path / "TxtInOut"
    (source_root).mkdir()
    (source_root / "000010001.hru").write_text(
        "        0.7500    | HRU_FR : Fraction of subbasin area\n"
        "        1.0000    | CANMX : Maximum canopy storage (mm)\n",
        encoding="utf-8",
    )
    hru = parse_hru_file(source_root / "000010001.hru")
    rule = HRUModificationRule(parameter="CANMX", new_value=8.0, selection=HRUSelection())
    apply_modifications([hru], [rule])

    destination_root = tmp_path / "Scenario1"
    changes = write_modified_hru_files([hru], destination_root, source_root=source_root)

    written_file = destination_root / "000010001.hru"
    assert written_file.exists()
    rewritten = parse_hru_file(written_file)
    assert rewritten.get_value("CANMX") == pytest.approx(8.0)
    assert len(changes) == 1
    assert changes[0].status == "WRITTEN"
    assert changes[0].old_value == pytest.approx(1.0)
    assert changes[0].new_value == pytest.approx(8.0)


def test_write_modified_hru_files_rejects_equal_roots(tmp_path: Path) -> None:
    with pytest.raises(HRUModificationError):
        write_modified_hru_files([], tmp_path, source_root=tmp_path)


def test_write_modified_hru_files_rejects_file_outside_source_root(tmp_path: Path) -> None:
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "000010001.hru"
    outside_file.write_text("        0.7500    | HRU_FR : desc\n", encoding="utf-8")
    hru = parse_hru_file(outside_file)

    source_root = tmp_path / "TxtInOut"
    source_root.mkdir()
    destination_root = tmp_path / "Scenario1"

    with pytest.raises(HRUModificationError):
        write_modified_hru_files([hru], destination_root, source_root=source_root)

    assert not destination_root.exists()


def test_write_modified_hru_files_rejects_protected_destination(tmp_path: Path) -> None:
    source_root = tmp_path / "TxtInOut"
    source_root.mkdir()
    (source_root / "000010001.hru").write_text("        0.7500    | HRU_FR : desc\n", encoding="utf-8")
    hru = parse_hru_file(source_root / "000010001.hru")

    protected_root = tmp_path / "BaseModels"
    destination_root = protected_root / "Buffalo_calibrated_annual" / "TxtInOut"

    with pytest.raises(HRUModificationError):
        write_modified_hru_files(
            [hru], destination_root, source_root=source_root, protected_roots=[protected_root]
        )
