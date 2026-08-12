"""Smoke test end-to-end de la sección "Apply an NbS by area (all subbasins)"
de la pestaña NbS (scenarios/nbs_mass_apply.py + su UI en ui/tab_nbs.py) --
mismo patrón de root de Tk real (oculto, sin mainloop) que
test_nbs_area_apply_tab_smoke.py, con dos subcuencas para ejercitar que el
batch cubre más de una a la vez.

No mockea apply_nbs ni plan_mass_area_allocation: el objetivo es confirmar
que el CSV cargado llega completo hasta la escritura real de .hru/.mgt de
ambas subcuencas. Sí mockea ConfirmDialog (auto-confirma) y run_in_background
(corre sincrónico) -- mismos mocks ya aceptados en el resto de esta suite.
"""
from __future__ import annotations

from pathlib import Path

import customtkinter as ctk
import pandas as pd
import pytest

from config.settings import ConfigManager
from scenarios.nbs import NbSDefinition, add_or_replace
from scenarios.nbs_mass_apply import SubbasinAreaAllocation
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
    "Subbasin:{sub}   Hru:{hru}   Luse:AGRL   Soil: 1013090         Slope: 0-9999\n"
    "        1.0000    | HRU_FR : Fraction of subbasin area contained in HRU\n"
    "        0.1500    | OV_N : Manning's \"n\" value for overland flow\n"
    "        1.0000    | CANMX : Maximum canopy storage (mm)\n"
    "     5000.0000    | RSDIN : Initial residue cover (kg/ha)\n"
)

_MGT_TEMPLATE = (
    " .mgt file HRU:{hru} Subbasin:{sub} HRU:{hru} Luse:AGRL\n"
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

_SOL_TEMPLATE = " .Sol file HRU:{hru} Subbasin:{sub} HRU:{hru}\n Soil Name: Test\n Soil Hydrologic Group: C\n"

_SUB = "Subbasin:{sub}\n        1.0000    | SUB_KM : Subbasin area (km2)\n"  # 1 km2 = 100 ha


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
    for sub_id in (1, 2):
        (txtinout / f"{sub_id:05d}0000.sub").write_text(_SUB.format(sub=sub_id), encoding="utf-8")
        (txtinout / f"{sub_id:05d}0000.pnd").write_text("", encoding="utf-8")
        (txtinout / f"{sub_id:05d}0001.hru").write_text(_HRU_TEMPLATE.format(sub=sub_id, hru=1), encoding="utf-8")
        (txtinout / f"{sub_id:05d}0001.mgt").write_text(_MGT_TEMPLATE.format(sub=sub_id, hru=1), encoding="utf-8")
        (txtinout / f"{sub_id:05d}0001.sol").write_text(_SOL_TEMPLATE.format(sub=sub_id, hru=1), encoding="utf-8")
    return tmp_path


def _install_synchronous_mocks(monkeypatch) -> None:
    import ui.tab_nbs as tab_nbs_module

    monkeypatch.setattr(tab_nbs_module, "ConfirmDialog", lambda master, cfg, *, message, on_confirm: on_confirm())
    monkeypatch.setattr(
        tab_nbs_module, "run_in_background",
        lambda widget, work, *, on_progress, on_done, on_error, **_kw: on_done(work(lambda _m: None)),
    )


def _nbs_definition() -> NbSDefinition:
    return NbSDefinition(
        name="Restore forest", target_lulc="FRST", new_coverage=None,
        hru_params={"CANMX": 3.0, "OV_N": 0.12}, mgt_initial={"IGRO": 0}, cn2_by_hsg={"C": 88.33}, operations=[],
    )


def test_mass_load_csv_enables_preview_and_apply_buttons(hidden_root, config, project, monkeypatch) -> None:
    add_or_replace(project, _nbs_definition())
    _install_synchronous_mocks(monkeypatch)

    tab = NbSTab(hidden_root, config)
    tab.set_project(project)
    assert tab._mass_preview_button.cget("state") == "disabled"
    assert tab._mass_apply_button.cget("state") == "disabled"

    csv_path = project / "matrix.csv"
    pd.DataFrame(
        [{"subbasin": 1, "area_ha": 100, "AGRL": 100}, {"subbasin": 2, "area_ha": 50, "AGRL": 100}]
    ).to_csv(csv_path, index=False)
    monkeypatch.setattr("ui.tab_nbs.filedialog.askopenfilename", lambda **_kw: str(csv_path))

    tab._on_mass_load_csv_clicked()

    assert tab._mass_allocations == {
        1: SubbasinAreaAllocation(area_ha=100.0, sources=[("AGRL", 100.0)]),
        2: SubbasinAreaAllocation(area_ha=50.0, sources=[("AGRL", 100.0)]),
    }
    assert tab._mass_preview_button.cget("state") == "normal"
    assert tab._mass_apply_button.cget("state") == "normal"


def test_mass_plan_computes_independent_plan_per_subbasin(hidden_root, config, project, monkeypatch) -> None:
    add_or_replace(project, _nbs_definition())
    _install_synchronous_mocks(monkeypatch)

    tab = NbSTab(hidden_root, config)
    tab.set_project(project)
    tab._mass_nbs_selector.current(0)
    tab._mass_allocations = {
        1: SubbasinAreaAllocation(area_ha=100.0, sources=[("AGRL", 100.0)]),
        2: SubbasinAreaAllocation(area_ha=50.0, sources=[("AGRL", 100.0)]),
    }

    captured = []
    tab._run_mass_plan(lambda definition, result: captured.append((definition, result)))

    assert captured
    _definition, result = captured[0]
    plans_by_subbasin = {p.subbasin: p for p in result.plans}
    assert plans_by_subbasin[1].targets == [(1, 1)]
    assert plans_by_subbasin[1].by_source[0].requested_ha == 100.0  # 100% del area_ha (100 ha) de la subcuenca 1
    assert plans_by_subbasin[2].targets == [(2, 1)]
    assert plans_by_subbasin[2].by_source[0].requested_ha == 50.0  # 100% del area_ha (50 ha) de la subcuenca 2
    assert result.skipped == {}


def test_mass_apply_writes_real_hru_mgt_files_across_subbasins(hidden_root, config, project, monkeypatch) -> None:
    add_or_replace(project, _nbs_definition())
    _install_synchronous_mocks(monkeypatch)

    tab = NbSTab(hidden_root, config)
    tab.set_project(project)
    tab._mass_nbs_selector.current(0)
    tab._mass_allocations = {
        1: SubbasinAreaAllocation(area_ha=100.0, sources=[("AGRL", 100.0)]),
        2: SubbasinAreaAllocation(area_ha=100.0, sources=[("AGRL", 100.0)]),
    }

    tab._on_mass_apply_clicked()

    for sub_id in (1, 2):
        hru_file = parse_hru_file(project / "TxtInOut" / f"{sub_id:05d}0001.hru")
        assert hru_file.metadata.land_use == "FRST"
        assert hru_file.get_value("CANMX") == 3.0


def test_mass_apply_skips_subbasin_not_in_project_without_aborting(hidden_root, config, project, monkeypatch) -> None:
    add_or_replace(project, _nbs_definition())
    _install_synchronous_mocks(monkeypatch)

    tab = NbSTab(hidden_root, config)
    tab.set_project(project)
    tab._mass_nbs_selector.current(0)
    tab._mass_allocations = {
        1: SubbasinAreaAllocation(area_ha=100.0, sources=[("AGRL", 100.0)]),
        99: SubbasinAreaAllocation(area_ha=100.0, sources=[("AGRL", 100.0)]),
    }

    captured = []
    tab._run_mass_plan(lambda definition, result: captured.append((definition, result)))

    assert captured
    _definition, result = captured[0]
    assert 99 in result.skipped
    assert [p.subbasin for p in result.plans] == [1]


def test_mass_apply_is_blocked_when_any_subbasin_is_skipped(hidden_root, config, project, monkeypatch) -> None:
    """Pedido explícito del usuario, 2026-08-12: a diferencia de la planificación
    (test_mass_apply_skips_subbasin_not_in_project_without_aborting), el clic de
    Apply en sí NO debe escribir nada si hay algún SKIPPED -- el usuario prefiere
    forzar la corrección del CSV en vez de aplicar parcialmente sobre las
    subcuencas válidas."""
    add_or_replace(project, _nbs_definition())
    _install_synchronous_mocks(monkeypatch)

    started = []
    monkeypatch.setattr("ui.tab_nbs.NbSTab._start_mass_apply", lambda self, definition, targets: started.append(targets))

    tab = NbSTab(hidden_root, config)
    tab.set_project(project)
    tab._mass_nbs_selector.current(0)
    tab._mass_allocations = {
        1: SubbasinAreaAllocation(area_ha=100.0, sources=[("AGRL", 100.0)]),
        99: SubbasinAreaAllocation(area_ha=100.0, sources=[("AGRL", 100.0)]),
    }

    tab._on_mass_apply_clicked()

    assert started == []
    assert tab._mass_apply_button.cget("state") == "disabled"
    for sub_id in (1, 2):
        hru_file = parse_hru_file(project / "TxtInOut" / f"{sub_id:05d}0001.hru")
        assert hru_file.metadata.land_use == "AGRL"  # sin cambios: Apply se bloqueó antes de escribir
