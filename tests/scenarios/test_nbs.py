from __future__ import annotations

from pathlib import Path

from scenarios.nbs import (
    NbSDefinition,
    NbSNewCoverage,
    NbSOperation,
    add_or_replace,
    delete_definition,
    load_library,
    save_library,
)


def _sample_definition(name: str = "Forest restoration") -> NbSDefinition:
    return NbSDefinition(
        name=name,
        target_lulc="FRST",
        new_coverage=None,
        hru_params={"CANMX": 3.0, "OV_N": 0.12, "RSDIN": 0.0},
        mgt_initial={"IGRO": 1, "LAI_INIT": 3.2, "BIO_INIT": 750.0, "PHU_PLT": 1146.0},
        cn2_by_hsg={"A": 43.56, "B": 72.6, "C": 88.33, "D": 95.59},
        operations=[NbSOperation(mgt_op=1, husc=0.15, fields={"HEAT_UNITS": 1146.0}), NbSOperation(mgt_op=17)],
        description="Convert HRUs to mature forest.",
    )


def test_load_library_empty_when_no_file(tmp_path: Path) -> None:
    assert load_library(tmp_path) == []


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    definition = _sample_definition()
    save_library(tmp_path, [definition])

    loaded = load_library(tmp_path)
    assert len(loaded) == 1
    restored = loaded[0]
    assert restored.name == definition.name
    assert restored.target_lulc == "FRST"
    assert restored.cn2_by_hsg == definition.cn2_by_hsg
    assert [op.mgt_op for op in restored.operations] == [1, 17]
    assert restored.operations[0].fields["HEAT_UNITS"] == 1146.0


def test_new_coverage_round_trips() -> None:
    from scenarios.nbs import NbSDefinition as _D

    definition = _D(
        name="Restored native forest",
        target_lulc="RFOR",
        new_coverage=NbSNewCoverage(cpnm="RFOR", idc=7, physiology={"BIO_E": 15.0, "MAT_YRS": 50}),
        hru_params={"CANMX": 3.0, "OV_N": 0.12, "RSDIN": None},
        mgt_initial={"IGRO": 1},
        cn2_by_hsg={"C": 88.33},
        operations=[],
    )
    data = definition.to_dict()
    restored = _D.from_dict(data)
    assert restored.new_coverage is not None
    assert restored.new_coverage.cpnm == "RFOR"
    assert restored.new_coverage.physiology["MAT_YRS"] == 50


def test_add_or_replace_is_upsert_by_name(tmp_path: Path) -> None:
    definition = _sample_definition()
    add_or_replace(tmp_path, definition)

    updated = _sample_definition()
    updated.description = "Updated description"
    add_or_replace(tmp_path, updated)

    library = load_library(tmp_path)
    assert len(library) == 1
    assert library[0].description == "Updated description"


def test_delete_definition_removes_by_name(tmp_path: Path) -> None:
    add_or_replace(tmp_path, _sample_definition("A"))
    add_or_replace(tmp_path, _sample_definition("B"))

    remaining = delete_definition(tmp_path, "A")
    assert [d.name for d in remaining] == ["B"]
    assert [d.name for d in load_library(tmp_path)] == ["B"]
