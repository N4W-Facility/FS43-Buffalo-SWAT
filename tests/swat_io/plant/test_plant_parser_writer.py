"""Tests de swat_io.plant: round-trip, edición de un campo, y creación de
un registro nuevo.

Contenido de fixture: los primeros dos registros reales de plant.dat
(AGRL, AGRR) tal como los trae la base vegetal estándar de rev670 --
verificado idéntico en tres modelos distintos del proyecto durante el
desarrollo (ver CLAUDE.md), incluyendo el hallazgo de que la línea 5 solo
tiene 5 campos (no los 7 de la documentación oficial más reciente)."""
from __future__ import annotations

from pathlib import Path

import pytest

from swat_io.plant.exceptions import PlantDatModificationError, PlantDatParseError
from swat_io.plant.models import ALL_PHYSIOLOGY_FIELDS, build_plant_record
from swat_io.plant.parser import parse_plant_dat_text
from swat_io.plant.writer import write_plant_dat_file

_PLANT_DAT = (
    "   1  AGRL   4\r\n"
    "  33.50   0.45    3.00   0.15   0.05   0.50   0.95   0.64    1.00   2.00\r\n"
    "  30.00   11.00   0.0199   0.0032   0.0440   0.0164   0.0128   0.0060   0.0022   0.0018\r\n"
    "  0.250   0.2000   0.0050   4.00   0.750    8.50    660.00    36.00   0.0500   0.000\r\n"
    "  0.000     0    0.00   0.650   0.100\r\n"
    "   2  AGRR   4\r\n"
    "  39.00   0.50    3.00   0.15   0.05   0.50   0.95   0.70    2.50   2.00\r\n"
    "  25.00    8.00   0.0140   0.0016   0.0470   0.0177   0.0138   0.0048   0.0018   0.0014\r\n"
    "  0.300   0.2000   0.0070   4.00   0.750    7.20    660.00    45.00   0.0500   0.000\r\n"
    "  0.000     0    0.00   0.650   0.100\r\n"
)


def _parse():
    return parse_plant_dat_text(_PLANT_DAT, source_path=None, encoding="utf-8")


def test_round_trip_is_byte_identical() -> None:
    pdat = _parse()
    assert pdat.render() == _PLANT_DAT


def test_records_parsed_correctly() -> None:
    pdat = _parse()
    assert len(pdat.records) == 2
    agrl = pdat.get_record_by_cpnm("AGRL")
    assert agrl.icnum == 1
    assert agrl.idc == 4
    assert agrl.fields["BIO_E"] == 33.5
    assert agrl.fields["BMX_TREES"] == 0.0
    assert "RSR1C" not in agrl.fields  # rev670 real: no existe en la línea 5


def test_max_and_next_icnum() -> None:
    pdat = _parse()
    assert pdat.max_icnum() == 2
    assert pdat.next_icnum() == 3


def test_set_field_only_touches_that_token() -> None:
    pdat = _parse()
    record = pdat.get_record_by_cpnm("AGRL")
    record.set("CHTMX", 12.5)
    assert record.fields["CHTMX"] == 12.5
    assert "12.5000" in record.line2 or "12.50" in record.line2
    # el resto de la línea 2 no cambió de forma incoherente
    assert "33.50" in record.line2


def test_set_unknown_field_raises() -> None:
    pdat = _parse()
    record = pdat.get_record_by_cpnm("AGRL")
    with pytest.raises(PlantDatModificationError):
        record.set("NOT_A_FIELD", 1.0)


def test_parse_rejects_non_multiple_of_five() -> None:
    with pytest.raises(PlantDatParseError):
        parse_plant_dat_text("   1  AGRL   4\r\nonly one more line\r\n")


def test_build_plant_record_requires_all_physiology_fields() -> None:
    with pytest.raises(PlantDatModificationError):
        build_plant_record(icnum=99, cpnm="TEST", idc=7, values={})


def test_build_and_append_new_record() -> None:
    pdat = _parse()
    values = {name: (10 if name == "MAT_YRS" else 1.5) for name in ALL_PHYSIOLOGY_FIELDS if name not in ("CPNM", "IDC")}
    record = build_plant_record(icnum=pdat.next_icnum(), cpnm="test", idc=7, values=values, newline="\r\n")
    pdat.append_record(record)

    assert len(pdat.records) == 3
    assert record.cpnm == "TEST"  # normalizado a mayúsculas
    assert record.fields["MAT_YRS"] == 10

    # el archivo completo re-parseado da los mismos valores
    reparsed = parse_plant_dat_text(pdat.render())
    new_record = reparsed.get_record_by_cpnm("TEST")
    assert new_record is not None
    assert new_record.fields["BIO_E"] == 1.5


def test_append_duplicate_icnum_or_cpnm_raises() -> None:
    pdat = _parse()
    values = {name: 1.0 for name in ALL_PHYSIOLOGY_FIELDS if name not in ("CPNM", "IDC", "MAT_YRS")}
    values["MAT_YRS"] = 5
    duplicate = build_plant_record(icnum=1, cpnm="TEST", idc=7, values=values)
    with pytest.raises(PlantDatModificationError):
        pdat.append_record(duplicate)


def test_write_plant_dat_file_rejects_same_path(tmp_path: Path) -> None:
    from swat_io.plant.exceptions import PlantDatWriteError
    from swat_io.plant.parser import parse_plant_dat_file

    source = tmp_path / "plant.dat"
    source.write_text(_PLANT_DAT, encoding="utf-8", newline="")
    pdat = parse_plant_dat_file(source)
    with pytest.raises(PlantDatWriteError):
        write_plant_dat_file(pdat, source)
