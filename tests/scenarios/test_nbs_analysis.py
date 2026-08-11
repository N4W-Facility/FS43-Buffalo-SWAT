"""Tests de scenarios.nbs_analysis sobre un TxtInOut sintético con dos HRU
de la misma cobertura (AGRL) pero distinto HYDGRP, para verificar que se
agrupan en una sola combinación con CN2 separado por HSG."""
from __future__ import annotations

from pathlib import Path

import pytest

from scenarios.nbs_analysis import scan_existing_parameter_combinations

_HRU = (
    "Subbasin:1   Hru:{hru}   Luse:AGRL   Soil: 1013090         Slope: 0-9999\n"
    "        0.5000    | HRU_FR : Fraction of subbasin area contained in HRU\n"
    "        0.1500    | OV_N : Manning's \"n\" value for overland flow\n"
    "        1.0000    | CANMX : Maximum canopy storage (mm)\n"
    "     5000.0000    | RSDIN : Initial residue cover (kg/ha)\n"
)

_MGT = (
    " .mgt file HRU:{hru} Subbasin:1 HRU:{hru} Luse:AGRL\n"
    "               0    | NMGT:Management code\n"
    "Initial Plant Growth Parameters\n"
    "               0    | IGRO: Land cover status: 0-none growing; 1-growing\n"
    "               0    | PLANT_ID: Land cover ID number (IGRO = 1)\n"
    "            0.00    | LAI_INIT: Initial leaf are index (IGRO = 1)\n"
    "            0.00    | BIO_INIT: Initial biomass (kg/ha) (IGRO = 1)\n"
    "            0.00    | PHU_PLT: Number of heat units to bring plant to maturity (IGRO = 1)\n"
    "General Management Parameters\n"
    "            0.20    | BIOMIX: Biological mixing efficiency\n"
    "           {cn2}    | CN2: Initial SCS CN II value\n"
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

_SOL = " .Sol file HRU:{hru} Subbasin:1 HRU:{hru}\n Soil Name: Test\n Soil Hydrologic Group: {hsg}\n"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    for hru_id, hsg, cn2 in ((1, "A", "70.00"), (2, "D", "88.00")):
        (txtinout / f"0000100{hru_id:02d}.hru").write_text(_HRU.format(hru=hru_id), encoding="utf-8")
        (txtinout / f"0000100{hru_id:02d}.mgt").write_text(_MGT.format(hru=hru_id, cn2=cn2), encoding="utf-8")
        (txtinout / f"0000100{hru_id:02d}.sol").write_text(_SOL.format(hru=hru_id, hsg=hsg), encoding="utf-8")
    return txtinout


def test_scan_groups_identical_hru_mgt_but_splits_cn2_by_hsg(project: Path) -> None:
    combinations = scan_existing_parameter_combinations(project, "AGRL")

    assert len(combinations) == 1
    combo = combinations[0]
    assert combo.hru_count == 2
    assert combo.hru_params["CANMX"] == 1.0
    assert combo.cn2_by_hsg == {"A": 70.0, "D": 88.0}
    assert [op.mgt_op for op in combo.operations] == [1, 5, 17]


def test_scan_unknown_coverage_returns_empty(project: Path) -> None:
    assert scan_existing_parameter_combinations(project, "NOPE") == []
