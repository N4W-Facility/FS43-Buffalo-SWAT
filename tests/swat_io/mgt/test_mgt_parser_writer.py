"""Tests de swat_io.mgt: round-trip, edición de cabecera, y reemplazo del
calendario de operaciones.

El contenido de fixture es un extracto real (000010001.mgt de
03-Models/Buffalo/Buffalo_calibrated_annual) verificado byte a byte contra
el parser durante el desarrollo -- ver CLAUDE.md.
"""
from __future__ import annotations

from pathlib import Path

from swat_io.mgt.models import MGTOperation
from swat_io.mgt.parser import parse_mgt_text
from swat_io.mgt.writer import write_mgt_file

_HAY_MGT = (
    " .mgt file Watershed HRU:1 Subbasin:1 HRU:1 Luse:HAY Soil: 290778 Slope: 2-5 8/26/2021 12:00:00 AM ArcSWAT 2012.10_7.23\n"
    "               0    | NMGT:Management code\n"
    "Initial Plant Growth Parameters\n"
    "               0    | IGRO: Land cover status: 0-none growing; 1-growing\n"
    "               0    | PLANT_ID: Land cover ID number (IGRO = 1)\n"
    "            0.00    | LAI_INIT: Initial leaf are index (IGRO = 1)\n"
    "            0.00    | BIO_INIT: Initial biomass (kg/ha) (IGRO = 1)\n"
    "            0.00    | PHU_PLT: Number of heat units to bring plant to maturity (IGRO = 1)\n"
    "General Management Parameters\n"
    "            0.20    | BIOMIX: Biological mixing efficiency\n"
    "           72.00    | CN2: Initial SCS CN II value\n"
    "            1.00    | USLE_P: USLE support practice factor\n"
    "            0.00    | BIO_MIN: Minimum biomass for grazing (kg/ha)\n"
    "           0.000    | FILTERW: width of edge of field filter strip (m)\n"
    "Urban Management Parameters\n"
    "               0    | IURBAN: urban simulation code, 0-none, 1-USGS, 2-buildup/washoff\n"
    "               0    | URBLU: urban land type\n"
    "Irrigation Management Parameters\n"
    "               0    | IRRSC: irrigation code\n"
    "               0    | IRRNO: irrigation source location\n"
    "           0.000    | FLOWMIN: min in-stream flow for irr diversions (m^3/s)\n"
    "           0.000    | DIVMAX: max irrigation diversion from reach (+mm/-10^4m^3)\n"
    "           0.000    | FLOWFR: : fraction of flow allowed to be pulled for irr\n"
    "Tile Drain Management Parameters\n"
    "           0.000    | DDRAIN: depth to subsurface tile drain (mm)\n"
    "           0.000    | TDRAIN: time to drain soil to field capacity (hr)\n"
    "           0.000    | GDRAIN: drain tile lag time (hr)\n"
    "Management Operations:\n"
    "               1    | NROT: number of years of rotation\n"
    "Operation Schedule:\n"
    "          0.150  1    5          1416.00000   0.00     0.00000 0.00   0.00  0.00\n"
    "          1.200  5                  0.00000\n"
    "                17\n"
)


def _parse():
    return parse_mgt_text(_HAY_MGT, source_path=None, encoding="utf-8")


def test_round_trip_is_byte_identical() -> None:
    mgt = _parse()
    assert mgt.render() == _HAY_MGT


def test_header_values_parsed() -> None:
    mgt = _parse()
    assert mgt.get_header_value("IGRO") == 0
    assert mgt.get_header_value("CN2") == 72.0
    assert mgt.get_header_value("BIOMIX") == 0.2


def test_operations_parsed_with_correct_fields() -> None:
    mgt = _parse()
    ops = mgt.operations()
    assert [op.mgt_op for op in ops] == [1, 5, 17]

    plant_op = ops[0]
    assert plant_op.husc == 0.15
    assert plant_op.fields["PLANT_ID"] == 5
    assert plant_op.fields["HEAT_UNITS"] == 1416.0

    skip_op = ops[2]
    assert skip_op.month is None and skip_op.day is None and skip_op.husc is None
    assert skip_op.fields == {}


def test_set_header_value_preserves_rest_of_file() -> None:
    mgt = _parse()
    mgt.set_header_value("CN2", 88.5)
    rendered = mgt.render()
    assert "88.50    | CN2" in rendered
    # todo lo demás queda intacto
    assert rendered.count("\n") == _HAY_MGT.count("\n")
    assert "IURBAN" in rendered


def test_set_header_value_missing_parameter_raises() -> None:
    mgt = _parse()
    import pytest
    from swat_io.mgt.exceptions import MGTModificationError

    with pytest.raises(MGTModificationError):
        mgt.set_header_value("NOT_A_REAL_PARAM", 1.0)


def test_replace_operations_keeps_header_intact_and_swaps_calendar() -> None:
    mgt = _parse()
    header_before = mgt.render().split("Operation Schedule:")[0]

    new_ops = [
        MGTOperation(mgt_op=1, husc=0.1, fields={"PLANT_ID": 6, "HEAT_UNITS": 1200.0}, modified=True),
        MGTOperation(mgt_op=17, modified=True),
    ]
    mgt.replace_operations(new_ops)

    rendered = mgt.render()
    assert rendered.split("Operation Schedule:")[0] == header_before
    assert [op.mgt_op for op in mgt.operations()] == [1, 17]
    assert mgt.operations()[0].fields["PLANT_ID"] == 6


def test_write_mgt_file_rejects_same_path(tmp_path: Path) -> None:
    import pytest
    from swat_io.mgt.exceptions import MGTWriteError
    from swat_io.mgt.parser import parse_mgt_file

    source = tmp_path / "000010001.mgt"
    source.write_text(_HAY_MGT, encoding="utf-8")
    mgt = parse_mgt_file(source)

    with pytest.raises(MGTWriteError):
        write_mgt_file(mgt, source)


def test_write_mgt_file_to_new_destination(tmp_path: Path) -> None:
    mgt = _parse()
    mgt.set_header_value("CN2", 90.0)
    destination = tmp_path / "copy.mgt"
    write_mgt_file(mgt, destination)
    assert destination.exists()
    assert "90.00    | CN2" in destination.read_text(encoding="utf-8")
