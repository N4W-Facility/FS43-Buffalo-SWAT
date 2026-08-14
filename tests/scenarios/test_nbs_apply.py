"""Tests del motor de aplicación de NbS (scenarios.nbs_apply) sobre un
TxtInOut sintético autocontenido en tmp_path -- nunca sobre un modelo real
(ver CLAUDE.md: nunca escribir sobre la carpeta de referencia)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from scenarios.nbs import NbSDefinition, NbSNewCoverage, NbSOperation
from scenarios.nbs_apply import (
    NbSApplyError,
    apply_nbs,
    sync_new_coverage_to_plant_dat,
    validate_nbs_definition,
    write_apply_report_csv,
)
from swat_io.plant.parser import parse_plant_dat_file
from tests.helpers import write_synthetic_sub

_PLANT_DAT = (
    "   1  AGRL   4\r\n"
    "  33.50   0.45    3.00   0.15   0.05   0.50   0.95   0.64    1.00   2.00\r\n"
    "  30.00   11.00   0.0199   0.0032   0.0440   0.0164   0.0128   0.0060   0.0022   0.0018\r\n"
    "  0.250   0.2000   0.0050   4.00   0.750    8.50    660.00    36.00   0.0500   0.000\r\n"
    "  0.000     0    0.00   0.650   0.100\r\n"
    "   6  FRST   7\r\n"
    "  15.00   0.76    5.00   0.05   0.05   0.40   0.95   0.99    6.00   3.50\r\n"
    "  20.00    0.00   0.0015   0.0003   0.0060   0.0020   0.0015   0.0007   0.0004   0.0003\r\n"
    "  0.010   0.0010   0.0020   4.00   0.750    8.00    660.00    16.00   0.0500   0.750\r\n"
    "  0.300    50  1000.00   0.650   0.100\r\n"
)

_HRU = (
    "Subbasin:1   Hru:1   Luse:AGRL   Soil: 1013090         Slope: 0-9999\n"
    "        0.7500    | HRU_FR : Fraction of subbasin area contained in HRU\n"
    "        0.1500    | OV_N : Manning's \"n\" value for overland flow\n"
    "        1.0000    | CANMX : Maximum canopy storage (mm)\n"
    "     5000.0000    | RSDIN : Initial residue cover (kg/ha)\n"
)

_MGT = (
    " .mgt file HRU:1 Subbasin:1 HRU:1 Luse:AGRL\n"
    "               0    | NMGT:Management code\n"
    "Initial Plant Growth Parameters\n"
    "               0    | IGRO: Land cover status: 0-none growing; 1-growing\n"
    "               0    | PLANT_ID: Land cover ID number (IGRO = 1)\n"
    "            0.00    | LAI_INIT: Initial leaf are index (IGRO = 1)\n"
    "            0.00    | BIO_INIT: Initial biomass (kg/ha) (IGRO = 1)\n"
    "            0.00    | PHU_PLT: Number of heat units to bring plant to maturity (IGRO = 1)\n"
    "General Management Parameters\n"
    "            0.20    | BIOMIX: Biological mixing efficiency\n"
    "           83.00    | CN2: Initial SCS CN II value\n"
    "            1.00    | USLE_P: USLE support practice factor\n"
    "            0.00    | BIO_MIN: Minimum biomass for grazing (kg/ha)\n"
    "           0.000    | FILTERW: width of edge of field filter strip (m)\n"
    "Management Operations:\n"
    "               1    | NROT: number of years of rotation\n"
    "Operation Schedule:\n"
    "  5 15           1   19          1084.00000   0.00     0.00000 0.00   0.00  0.00\n"
    " 10 22           5                  0.00000\n"
    "                17\n"
)

_SOL = " .Sol file HRU:1 Subbasin:1 HRU:1 Luse:AGRL\n Soil Name: Test\n Soil Hydrologic Group: C\n"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    (txtinout / "plant.dat").write_text(_PLANT_DAT, encoding="utf-8", newline="")
    (txtinout / "000010001.hru").write_text(_HRU, encoding="utf-8")
    (txtinout / "000010001.mgt").write_text(_MGT, encoding="utf-8")
    (txtinout / "000010001.sol").write_text(_SOL, encoding="utf-8")
    write_synthetic_sub(txtinout / "000010000.sub", area_km2=10.0)
    (txtinout / "000010000.pnd").write_text("", encoding="utf-8")  # discover_subbasins exige el par .sub/.pnd
    return tmp_path


def _forest_nbs_existing() -> NbSDefinition:
    return NbSDefinition(
        name="Reforest with existing FRST",
        target_lulc="FRST",
        new_coverage=None,
        hru_params={"CANMX": 3.0, "OV_N": 0.12, "RSDIN": 0.0},
        mgt_initial={"IGRO": 1, "LAI_INIT": 3.2, "BIO_INIT": 750.0, "PHU_PLT": 1146.0},
        cn2_by_hsg={"A": 43.56, "B": 72.6, "C": 88.33, "D": 95.59},
        operations=[
            NbSOperation(mgt_op=1, husc=0.15, fields={"CURYR_MAT": 10, "HEAT_UNITS": 1146.0}),
            NbSOperation(mgt_op=17),
        ],
    )


def test_apply_existing_coverage_writes_hru_and_mgt(project: Path) -> None:
    from swat_io.hru.parser import parse_hru_file
    from swat_io.mgt.parser import parse_mgt_file

    report = apply_nbs(project, _forest_nbs_existing(), [(1, 1)])

    assert report.applied_count == 1
    assert report.error_count == 0
    assert report.plant_id == 6
    assert report.cpnm == "FRST"

    mgt = parse_mgt_file(project / "TxtInOut" / "000010001.mgt")
    assert mgt.get_header_value("IGRO") == 1
    assert mgt.get_header_value("PLANT_ID") == 6
    assert mgt.get_header_value("CN2") == 88.33
    ops = mgt.operations()
    assert [op.mgt_op for op in ops] == [1, 17]
    assert ops[0].fields["PLANT_ID"] == 6  # inyectado automáticamente

    hru = parse_hru_file(project / "TxtInOut" / "000010001.hru")
    assert hru.get_value("CANMX") == 3.0
    assert hru.get_value("OV_N") == 0.12
    assert hru.get_value("HRU_FR") == 0.75  # nunca tocado por la NbS

    # el texto "Luse:" del título queda consistente con la cobertura nueva
    # -- de lo contrario scan_existing_parameter_combinations seguiría
    # clasificando esta HRU como AGRL (la cobertura original) para siempre.
    assert hru.metadata.land_use == "FRST"
    assert mgt.metadata.land_use == "FRST"

    # .sol nunca se toca -- ni siquiera el texto "Luse:" de su título (ver
    # guía del proyecto, sección 3.3: sin excepciones para un cambio de
    # cobertura). Sigue diciendo la cobertura vieja a propósito.
    sol_text = (project / "TxtInOut" / "000010001.sol").read_text(encoding="utf-8")
    assert sol_text == _SOL
    assert "Luse:AGRL" in sol_text


def test_apply_report_csv_includes_hru_fr_and_area_ha(project: Path) -> None:
    report = apply_nbs(project, _forest_nbs_existing(), [(1, 1)])

    csv_path = write_apply_report_csv(project, report, datetime(2026, 8, 12, 10, 30, 0))

    assert csv_path.name == "nbs_apply_report_Reforest_with_existing_FRST_20260812_103000.csv"
    assert csv_path.parent == project / "tool_outputs"

    df = pd.read_csv(csv_path)
    assert list(df.columns) == ["subbasin", "hru", "status", "hru_fr", "hru_area_ha", "message"]
    row = df.iloc[0]
    assert row["subbasin"] == 1
    assert row["hru"] == 1
    assert row["status"] == "applied"
    assert row["hru_fr"] == pytest.approx(0.75)
    # subbasin 1 = 10 km2 (write_synthetic_sub) = 1000 ha; HRU_FR=0.75 -> 750 ha
    assert row["hru_area_ha"] == pytest.approx(750.0)


def test_apply_report_csv_blank_area_when_sub_file_missing(tmp_path: Path) -> None:
    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    (txtinout / "plant.dat").write_text(_PLANT_DAT, encoding="utf-8", newline="")
    (txtinout / "000010001.hru").write_text(_HRU, encoding="utf-8")
    (txtinout / "000010001.mgt").write_text(_MGT, encoding="utf-8")
    (txtinout / "000010001.sol").write_text(_SOL, encoding="utf-8")
    # a propósito, sin .sub -- la subcuenca no es localizable

    report = apply_nbs(tmp_path, _forest_nbs_existing(), [(1, 1)])
    csv_path = write_apply_report_csv(tmp_path, report, datetime(2026, 8, 12, 10, 30, 0))

    df = pd.read_csv(csv_path)
    assert df.iloc[0]["hru_fr"] == pytest.approx(0.75)
    assert pd.isna(df.iloc[0]["hru_area_ha"])


_RFOR_PHYSIOLOGY = {
    "BIO_E": 15.0, "HVSTI": 0.76, "BLAI": 5.0, "FRGRW1": 0.05, "LAIMX1": 0.05,
    "FRGRW2": 0.4, "LAIMX2": 0.95, "DLAI": 0.99, "CHTMX": 6.0, "RDMX": 3.5,
    "T_OPT": 20.0, "T_BASE": 0.0, "CNYLD": 0.0015, "CPYLD": 0.0003,
    "PLTNFR1": 0.006, "PLTNFR2": 0.002, "PLTNFR3": 0.0015,
    "PLTPFR1": 0.0007, "PLTPFR2": 0.0004, "PLTPFR3": 0.0003,
    "WSYF": 0.01, "USLE_C": 0.001, "GSI": 0.002, "VPDFR": 4.0, "FRGMAX": 0.75,
    "WAVP": 8.0, "CO2HI": 660.0, "BIOEHI": 16.0, "RSDCO_PL": 0.05, "ALAI_MIN": 0.75,
    "BIO_LEAF": 0.3, "MAT_YRS": 50, "BMX_TREES": 1000.0, "EXT_COEF": 0.65, "BMDIEOFF": 0.1,
}


def test_apply_new_coverage_creates_plant_dat_record(project: Path) -> None:
    definition = NbSDefinition(
        name="Restored forest (new species)",
        target_lulc="RFOR",
        new_coverage=NbSNewCoverage(cpnm="RFOR", idc=7, physiology=_RFOR_PHYSIOLOGY),
        hru_params={"CANMX": 3.0, "OV_N": 0.12, "RSDIN": 0.0},
        mgt_initial={"IGRO": 1, "LAI_INIT": 3.2, "BIO_INIT": 750.0, "PHU_PLT": 1146.0},
        cn2_by_hsg={"C": 88.33},
        operations=[NbSOperation(mgt_op=1, husc=0.15, fields={}), NbSOperation(mgt_op=17)],
    )

    report = apply_nbs(project, definition, [(1, 1)])
    assert report.applied_count == 1
    assert report.plant_id == 7  # max(1, 6) + 1
    assert report.cpnm == "RFOR"

    pdat = parse_plant_dat_file(project / "TxtInOut" / "plant.dat")
    assert pdat.get_record_by_cpnm("RFOR") is not None
    assert len(pdat.records) == 3

    # aplicar la MISMA NbS otra vez no debe duplicar el registro
    report2 = apply_nbs(project, definition, [(1, 1)])
    assert report2.plant_id == 7
    pdat2 = parse_plant_dat_file(project / "TxtInOut" / "plant.dat")
    assert len(pdat2.records) == 3


def test_apply_missing_hsg_cn2_reports_error_without_writing(project: Path) -> None:
    definition = _forest_nbs_existing()
    definition.cn2_by_hsg = {"A": 43.56}  # no cubre "C" (HYDGRP real de la HRU sintética)

    from swat_io.mgt.parser import parse_mgt_file

    before = parse_mgt_file(project / "TxtInOut" / "000010001.mgt").get_header_value("PLANT_ID")
    report = apply_nbs(project, definition, [(1, 1)])

    assert report.error_count == 1
    assert report.applied_count == 0
    after = parse_mgt_file(project / "TxtInOut" / "000010001.mgt").get_header_value("PLANT_ID")
    assert before == after  # no se escribió nada


def test_apply_missing_hru_reports_error_and_continues(project: Path) -> None:
    report = apply_nbs(project, _forest_nbs_existing(), [(1, 1), (99, 999)])
    statuses = {(r.subbasin, r.hru): r.status for r in report.results}
    assert statuses[(1, 1)] == "applied"
    assert statuses[(99, 999)] == "error"


def test_apply_invokes_on_hru_result_once_per_target_in_order(project: Path) -> None:
    seen: list[tuple[int, int, str]] = []
    report = apply_nbs(
        project, _forest_nbs_existing(), [(1, 1), (99, 999)],
        on_hru_result=lambda r: seen.append((r.subbasin, r.hru, r.status)),
    )
    assert seen == [(1, 1, "applied"), (99, 999, "error")]
    assert seen == [(r.subbasin, r.hru, r.status) for r in report.results]


def test_apply_incomplete_nbs_raises_before_touching_anything(project: Path) -> None:
    incomplete = NbSDefinition(
        name="incomplete", target_lulc="FRST", new_coverage=None,
        hru_params={"CANMX": 1.0, "OV_N": 0.1}, mgt_initial={"IGRO": 0}, cn2_by_hsg={}, operations=[],
    )
    with pytest.raises(NbSApplyError):
        apply_nbs(project, incomplete, [(1, 1)])


def test_validate_nbs_definition_flags_missing_target_coverage(project: Path) -> None:
    pdat = parse_plant_dat_file(project / "TxtInOut" / "plant.dat")
    bad = NbSDefinition(
        name="bad", target_lulc="NOPE", new_coverage=None,
        hru_params={"CANMX": 1.0, "OV_N": 0.1}, mgt_initial={"IGRO": 0}, cn2_by_hsg={"A": 50.0}, operations=[],
    )
    errors = validate_nbs_definition(bad, pdat)
    assert any("NOPE" in e for e in errors)


def _rfor_definition() -> NbSDefinition:
    return NbSDefinition(
        name="Restored forest (new species)",
        target_lulc="RFOR",
        new_coverage=NbSNewCoverage(cpnm="RFOR", idc=7, physiology=dict(_RFOR_PHYSIOLOGY)),
        hru_params={"CANMX": 3.0, "OV_N": 0.12, "RSDIN": 0.0},
        mgt_initial={"IGRO": 1, "LAI_INIT": 3.2, "BIO_INIT": 750.0, "PHU_PLT": 1146.0},
        cn2_by_hsg={"C": 88.33},
        operations=[NbSOperation(mgt_op=1, husc=0.15, fields={}), NbSOperation(mgt_op=17)],
    )


def test_sync_new_coverage_creates_record_on_first_save(project: Path) -> None:
    definition = _rfor_definition()

    synced = sync_new_coverage_to_plant_dat(project, definition)

    assert synced.new_coverage.icnum == 7  # max(1, 6) + 1
    pdat = parse_plant_dat_file(project / "TxtInOut" / "plant.dat")
    record = pdat.get_record_by_cpnm("RFOR")
    assert record is not None
    assert record.icnum == 7
    assert record.get("BIO_E") == 15.0


def test_sync_new_coverage_updates_same_record_on_edit(project: Path) -> None:
    definition = _rfor_definition()
    sync_new_coverage_to_plant_dat(project, definition)

    definition.new_coverage.physiology["BIO_E"] = 22.0  # el usuario edita la NbS
    sync_new_coverage_to_plant_dat(project, definition)

    pdat = parse_plant_dat_file(project / "TxtInOut" / "plant.dat")
    assert len(pdat.records) == 3  # no se duplicó el registro
    record = pdat.get_record_by_cpnm("RFOR")
    assert record.get("BIO_E") == 22.0


def test_sync_new_coverage_adopts_record_created_by_another_process(project: Path) -> None:
    # Simula que el CPNM ya existe en plant.dat (p. ej. otra NbS lo creó)
    # pero esta NbS todavía no conoce el ICNUM -- debe adoptar el registro
    # existente en vez de duplicarlo (mismo criterio que antes tenía
    # _resolve_plant_id para el flujo de aplicar).
    first = _rfor_definition()
    sync_new_coverage_to_plant_dat(project, first)

    second = _rfor_definition()  # icnum=None: no sabe que "RFOR" ya existe
    synced = sync_new_coverage_to_plant_dat(project, second)

    assert synced.new_coverage.icnum == 7
    pdat = parse_plant_dat_file(project / "TxtInOut" / "plant.dat")
    assert len(pdat.records) == 3


def test_sync_new_coverage_raises_on_cpnm_rename_conflict(project: Path) -> None:
    definition = _rfor_definition()
    sync_new_coverage_to_plant_dat(project, definition)  # icnum=7, CPNM=RFOR

    definition.new_coverage.cpnm = "FRST"  # ya usado por el registro icnum=6
    with pytest.raises(NbSApplyError):
        sync_new_coverage_to_plant_dat(project, definition)

    pdat = parse_plant_dat_file(project / "TxtInOut" / "plant.dat")
    assert len(pdat.records) == 3  # no se escribió nada
