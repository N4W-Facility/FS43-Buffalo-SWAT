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


def test_apply_resolves_real_file_when_header_hru_differs_from_filename(tmp_path: Path) -> None:
    """Bug real reportado por el usuario, 2026-09-15: en un modelo SWAT
    real, el sufijo del nombre de archivo (posición LOCAL dentro de la
    subcuenca) y el "Hru:" del header (número GLOBAL en toda la cuenca)
    pueden ser completamente distintos salvo en la subcuenca 1 (donde
    coinciden por casualidad). ``targets`` siempre trae el número de
    header (ver plan_area_allocation), así que aplicar sobre la subcuenca
    2 de este fixture -- archivo 000020001.hru con header "Hru:88" --
    debe escribir sobre ESE archivo real, nunca sobre uno reconstruido
    como 000020088.hru (que no existe)."""
    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    (txtinout / "plant.dat").write_text(_PLANT_DAT, encoding="utf-8", newline="")
    (txtinout / "000020001.hru").write_text(_HRU.replace("Subbasin:1", "Subbasin:2").replace("Hru:1", "Hru:88"), encoding="utf-8")
    (txtinout / "000020001.mgt").write_text(_MGT.replace("Subbasin:1", "Subbasin:2"), encoding="utf-8")
    (txtinout / "000020001.sol").write_text(_SOL.replace("Subbasin:1", "Subbasin:2"), encoding="utf-8")
    write_synthetic_sub(txtinout / "000020000.sub", area_km2=10.0)
    (txtinout / "000020000.pnd").write_text("", encoding="utf-8")

    report = apply_nbs(tmp_path, _forest_nbs_existing(), [(2, 88)])

    assert report.applied_count == 1
    assert report.error_count == 0

    from swat_io.hru.parser import parse_hru_file

    hru = parse_hru_file(txtinout / "000020001.hru")
    assert hru.metadata.land_use == "FRST"
    assert hru.get_value("CANMX") == 3.0


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


def _urban_nbs(**mgt_initial_overrides) -> NbSDefinition:
    mgt_initial = {"IGRO": 0, "PLANT_ID": 1, "IURBAN": 1, "URBLU": 3}
    mgt_initial.update(mgt_initial_overrides)
    return NbSDefinition(
        name="Urbanize", target_lulc="URLD", new_coverage=None,
        hru_params={"CANMX": 1.0, "OV_N": 0.1, "RSDIN": 0.0},
        mgt_initial=mgt_initial, cn2_by_hsg={"C": 98.0}, operations=[],
    )


def test_validate_nbs_definition_rejects_non_plant_target_not_in_real_land_uses(project: Path) -> None:
    # "URLD" no está en plant.dat ni en real_land_uses (ninguna HRU real del
    # proyecto lo usa todavía) -- mismo error que cualquier código
    # desconocido, no se trata distinto solo porque "suena" urbano.
    pdat = parse_plant_dat_file(project / "TxtInOut" / "plant.dat")
    errors = validate_nbs_definition(_urban_nbs(), pdat, real_land_uses=set())
    assert any("URLD" in e and "plant.dat" in e for e in errors)


def test_validate_nbs_definition_accepts_complete_non_plant_target(project: Path) -> None:
    pdat = parse_plant_dat_file(project / "TxtInOut" / "plant.dat")
    errors = validate_nbs_definition(_urban_nbs(), pdat, real_land_uses={"URLD"})
    assert errors == []


def test_validate_nbs_definition_requires_plant_id_iurban_urblu_for_non_plant_target(project: Path) -> None:
    pdat = parse_plant_dat_file(project / "TxtInOut" / "plant.dat")
    incomplete = _urban_nbs(PLANT_ID=None, URBLU=None)

    errors = validate_nbs_definition(incomplete, pdat, real_land_uses={"URLD"})

    assert any("PLANT_ID" in e for e in errors)
    assert any("URBLU" in e for e in errors)
    assert not any("IURBAN" in e for e in errors)  # ese sí estaba presente


# -- apply_nbs a un target no vegetal (urbano) -----------------------------------

# HRU 2: a convertir de AGRL a URLD -- su .mgt ya trae la sección "Urban
# Management Parameters" (IURBAN/URBLU) en 0, como cualquier .mgt real de
# SWAT (ver guía del proyecto, sección 11 "Urbanización"), independiente de
# si esa HRU puntual es urbana hoy.
_MGT_WITH_URBAN_SECTION = (
    " .mgt file HRU:2 Subbasin:1 HRU:2 Luse:AGRL\n"
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
    "Urban Management Parameters\n"
    "               0    | IURBAN: urban simulation code, 0-none, 1-USGS, 2-buildup/washoff\n"
    "               0    | URBLU: urban land type\n"
    "Management Operations:\n"
    "               1    | NROT: number of years of rotation\n"
    "Operation Schedule:\n"
    "  5 15           1   19          1084.00000   0.00     0.00000 0.00   0.00  0.00\n"
    " 10 22           5                  0.00000\n"
    "                17\n"
)

# HRU 3: HRU urbana real ya existente en el proyecto -- nunca se toca, solo
# existe para que discover_non_plant_land_uses encuentre "URLD" como
# cobertura real (nunca inventada) y para representar de dónde "Copy from
# existing" sacaría PLANT_ID/IURBAN/URBLU en el wizard real.
_URBAN_REFERENCE_HRU = (
    "Subbasin:1   Hru:3   Luse:URLD   Soil: 1013090         Slope: 0-9999\n"
    "        0.1000    | HRU_FR : Fraction of subbasin area contained in HRU\n"
)


@pytest.fixture
def project_with_urban_reference(project: Path) -> Path:
    txtinout = project / "TxtInOut"
    (txtinout / "000010002.hru").write_text(_HRU.replace("Hru:1", "Hru:2"), encoding="utf-8")
    (txtinout / "000010002.mgt").write_text(_MGT_WITH_URBAN_SECTION, encoding="utf-8")
    (txtinout / "000010002.sol").write_text(_SOL.replace("HRU:1", "HRU:2"), encoding="utf-8")
    (txtinout / "000010003.hru").write_text(_URBAN_REFERENCE_HRU, encoding="utf-8")
    return project


def test_apply_urban_target_writes_iurban_and_urblu(project_with_urban_reference: Path) -> None:
    from swat_io.hru.parser import parse_hru_file
    from swat_io.mgt.parser import parse_mgt_file

    report = apply_nbs(project_with_urban_reference, _urban_nbs(), [(1, 2)])

    assert report.applied_count == 1
    assert report.error_count == 0
    assert report.plant_id == 1  # de mgt_initial["PLANT_ID"], no resuelto por CPNM
    assert report.cpnm == "URLD"

    mgt = parse_mgt_file(project_with_urban_reference / "TxtInOut" / "000010002.mgt")
    assert mgt.get_header_value("IURBAN") == 1
    assert mgt.get_header_value("URBLU") == 3
    assert mgt.get_header_value("PLANT_ID") == 1
    assert mgt.metadata.land_use == "URLD"

    hru = parse_hru_file(project_with_urban_reference / "TxtInOut" / "000010002.hru")
    assert hru.metadata.land_use == "URLD"

    # la HRU urbana de referencia (nunca target de este Apply) sigue intacta.
    reference = parse_hru_file(project_with_urban_reference / "TxtInOut" / "000010003.hru")
    assert reference.metadata.land_use == "URLD"


def test_apply_urban_target_without_real_land_use_raises(project_with_urban_reference: Path) -> None:
    # Si nadie hubiera pasado antes por Restoration Inputs/HRU real con
    # Luse:URLD, discover_non_plant_land_uses no la encontraría -- mismo
    # error que cualquier cobertura inventada.
    (project_with_urban_reference / "TxtInOut" / "000010003.hru").unlink()

    with pytest.raises(NbSApplyError):
        apply_nbs(project_with_urban_reference, _urban_nbs(), [(1, 2)])


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
