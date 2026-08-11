"""Smoke test end-to-end de la sección "Apply by area" de la pestaña NbS
(scenarios/nbs_area_apply.py + su UI en ui/tab_nbs.py) -- mismo patrón de
root de Tk real (oculto, sin mainloop) que test_nbs_tab_smoke.py, pero con
dos HRU de la misma cobertura fuente en la subcuenca para poder ejercitar
la selección por área además de la escritura real de scenarios.nbs_apply.

No mockea apply_nbs (a diferencia de test_apply_rereads_library_json_to_pick_up_manual_edits,
que sí lo mockea): acá el objetivo es confirmar que el plan de selección
por área llega completo hasta la escritura real de .hru/.mgt. Sí mockea
ConfirmDialog (auto-confirma) y run_in_background (corre sincrónico) --
mismos mocks ya aceptados en el resto de esta suite para no depender de
threading real en un test.
"""
from __future__ import annotations

from pathlib import Path

import customtkinter as ctk
import pytest

from config.settings import ConfigManager
from scenarios.nbs import NbSDefinition, add_or_replace
from swat_io.hru.parser import parse_hru_file
from ui.tab_nbs import NbSTab

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

_HRU_TEMPLATE = (
    "Subbasin:1   Hru:{hru}   Luse:AGRL   Soil: 1013090         Slope: 0-9999\n"
    "        0.5000    | HRU_FR : Fraction of subbasin area contained in HRU\n"
    "        0.1500    | OV_N : Manning's \"n\" value for overland flow\n"
    "        1.0000    | CANMX : Maximum canopy storage (mm)\n"
    "     5000.0000    | RSDIN : Initial residue cover (kg/ha)\n"
)

_MGT_TEMPLATE = (
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
    "           83.00    | CN2: Initial SCS CN II value\n"
    "            1.00    | USLE_P: USLE support practice factor\n"
    "            0.00    | BIO_MIN: Minimum biomass for grazing (kg/ha)\n"
    "           0.000    | FILTERW: width of edge of field filter strip (m)\n"
    "Management Operations:\n"
    "               1    | NROT: number of years of rotation\n"
    "Operation Schedule:\n"
    "  5 15           1   19          1084.00000   0.00     0.00000 0.00   0.00  0.00\n"
    "                17\n"
)

_SOL_TEMPLATE = " .Sol file HRU:{hru} Subbasin:1 HRU:{hru}\n Soil Name: Test\n Soil Hydrologic Group: C\n"

# 1 km2 = 100 ha de subcuenca; cada HRU (HRU_FR 0.5) aporta 50 ha.
_SUB = "Subbasin:1\n        1.0000    | SUB_KM : Subbasin area (km2)\n"


@pytest.fixture(scope="module")
def config() -> ConfigManager:
    cfg = ConfigManager()
    cfg.load_all()
    return cfg


@pytest.fixture(scope="module")
def hidden_root():
    root = ctk.CTk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    (txtinout / "plant.dat").write_text(_PLANT_DAT, encoding="utf-8", newline="")
    for hru_id in (1, 2):
        (txtinout / f"0000100{hru_id:02d}.hru").write_text(_HRU_TEMPLATE.format(hru=hru_id), encoding="utf-8")
        (txtinout / f"0000100{hru_id:02d}.mgt").write_text(_MGT_TEMPLATE.format(hru=hru_id), encoding="utf-8")
        (txtinout / f"0000100{hru_id:02d}.sol").write_text(_SOL_TEMPLATE.format(hru=hru_id), encoding="utf-8")
    (txtinout / "000010000.sub").write_text(_SUB, encoding="utf-8")
    (txtinout / "000010000.pnd").write_text("", encoding="utf-8")
    return tmp_path


def _install_synchronous_mocks(monkeypatch) -> None:
    import ui.tab_nbs as tab_nbs_module

    monkeypatch.setattr(tab_nbs_module, "ConfirmDialog", lambda master, cfg, *, message, on_confirm: on_confirm())
    monkeypatch.setattr(
        tab_nbs_module, "run_in_background",
        lambda widget, work, *, on_progress, on_done, on_error, **_kw: on_done(work(lambda _m: None)),
    )


def test_area_apply_card_lists_subbasin_coverages_on_project_open(hidden_root, config, project) -> None:
    tab = NbSTab(hidden_root, config)
    tab.set_project(project)

    assert tab._area_subbasin_selector.get() == "1"
    assert list(tab._area_coverage_selector.cget("values")) == ["AGRL"]


def test_area_apply_preview_selects_both_hru_to_cover_requested_area(hidden_root, config, project) -> None:
    add_or_replace(
        project,
        NbSDefinition(
            name="Restore forest", target_lulc="FRST", new_coverage=None,
            hru_params={"CANMX": 3.0, "OV_N": 0.12}, mgt_initial={"IGRO": 0}, cn2_by_hsg={"C": 88.33}, operations=[],
        ),
    )

    tab = NbSTab(hidden_root, config)
    tab.set_project(project)
    tab._area_nbs_selector.current(0)

    tab._area_coverage_selector.current(0)  # "AGRL"
    tab._area_percent_entry.insert(0, "100")
    tab._on_add_source_row_clicked()
    assert tab._area_source_rows == [("AGRL", 100.0)]

    # 80 ha pedidos, cada HRU solo aporta 50 ha -> hacen falta las dos.
    tab._area_total_entry.insert(0, "80")
    built = tab._build_area_plan()
    assert built is not None
    _definition, plan = built
    assert plan.targets == [(1, 1), (1, 2)]
    assert plan.by_source[0].selected_ha == 100.0


def test_area_apply_writes_real_hru_mgt_files_for_selected_hrus(hidden_root, config, project, monkeypatch) -> None:
    add_or_replace(
        project,
        NbSDefinition(
            name="Restore forest", target_lulc="FRST", new_coverage=None,
            hru_params={"CANMX": 3.0, "OV_N": 0.12}, mgt_initial={"IGRO": 0}, cn2_by_hsg={"C": 88.33}, operations=[],
        ),
    )

    tab = NbSTab(hidden_root, config)
    tab.set_project(project)
    tab._area_nbs_selector.current(0)
    tab._area_coverage_selector.current(0)
    tab._area_percent_entry.insert(0, "100")
    tab._on_add_source_row_clicked()
    tab._area_total_entry.insert(0, "80")

    _install_synchronous_mocks(monkeypatch)
    tab._on_area_apply_clicked()

    for hru_id in (1, 2):
        hru_file = parse_hru_file(project / "TxtInOut" / f"0000100{hru_id:02d}.hru")
        assert hru_file.metadata.land_use == "FRST"
        assert hru_file.get_value("CANMX") == 3.0


def test_area_apply_reports_deficit_without_aborting_when_not_enough_source_area(
    hidden_root, config, project, monkeypatch
) -> None:
    add_or_replace(
        project,
        NbSDefinition(
            name="Restore forest", target_lulc="FRST", new_coverage=None,
            hru_params={"CANMX": 3.0, "OV_N": 0.12}, mgt_initial={"IGRO": 0}, cn2_by_hsg={"C": 88.33}, operations=[],
        ),
    )

    tab = NbSTab(hidden_root, config)
    tab.set_project(project)
    tab._area_nbs_selector.current(0)
    tab._area_coverage_selector.current(0)
    tab._area_percent_entry.insert(0, "100")
    tab._on_add_source_row_clicked()
    # Solo 100 ha disponibles en total (50+50); pedir 150 ha deja un déficit
    # de 50 ha pero igual debe aplicar las dos HRU disponibles.
    tab._area_total_entry.insert(0, "150")

    built = tab._build_area_plan()
    assert built is not None
    _definition, plan = built
    assert plan.targets == [(1, 1), (1, 2)]
    assert plan.total_deficit_ha == 50.0

    _install_synchronous_mocks(monkeypatch)
    tab._on_area_apply_clicked()

    for hru_id in (1, 2):
        hru_file = parse_hru_file(project / "TxtInOut" / f"0000100{hru_id:02d}.hru")
        assert hru_file.metadata.land_use == "FRST"
