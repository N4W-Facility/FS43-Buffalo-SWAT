"""Smoke tests con un root de Tk real (oculto, sin mainloop) para la
pestaña NbS y su wizard de creación -- mismo patrón que
test_scenario_comparison_window_smoke.py: no son tests de lógica de
negocio (eso lo cubren tests/scenarios/test_nbs*.py), son para atrapar
errores que solo aparecen al construir/mutar widgets de verdad.
"""
from __future__ import annotations

from pathlib import Path

import customtkinter as ctk
import pytest

from config.settings import ConfigManager
from scenarios.nbs import load_library, save_library
from ui.nbs_wizard_window import NbSWizardWindow
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
    "                17\n"
)

_SOL = " .Sol file HRU:1 Subbasin:1 HRU:1\n Soil Name: Test\n Soil Hydrologic Group: C\n"

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
    (txtinout / "000010001.hru").write_text(_HRU, encoding="utf-8")
    (txtinout / "000010001.mgt").write_text(_MGT, encoding="utf-8")
    (txtinout / "000010001.sol").write_text(_SOL, encoding="utf-8")
    (txtinout / "000010000.sub").write_text(_SUB, encoding="utf-8")
    (txtinout / "000010000.pnd").write_text("", encoding="utf-8")
    return tmp_path


def test_nbs_tab_builds_and_sets_project(hidden_root, config, project) -> None:
    tab = NbSTab(hidden_root, config)
    tab.set_project(project)
    assert tab._subbasins == [1]


def test_wizard_builds_and_walks_existing_coverage_flow(hidden_root, config, project) -> None:
    created = []
    window = NbSWizardWindow(hidden_root, config, project, on_created=lambda: created.append(True))
    window.update()

    # Paso 1: nombre
    window._name_entry.insert(0, "Test NbS")
    assert window._on_next_clicked() is None
    window.update()

    # Paso 2: cobertura existente (FRST)
    window._coverage_mode_var.set("existing")
    window._render_coverage_body()
    window.update()
    index = window._existing_cpnm_codes.index("FRST")
    window._existing_cpnm_selector.current(index)
    window._on_next_clicked()
    window.update()

    # Paso 3 (sin fisiología, cobertura existente): copiar de config. existente -- se salta
    assert window._current_step_key() == "copy_from_existing"
    window._on_next_clicked()
    window.update()

    # Paso 4: parámetros .hru
    assert window._current_step_key() == "hru_params"
    window._hru_param_entries["CANMX"].insert(0, "3.0")
    window._hru_param_entries["OV_N"].insert(0, "0.12")
    window._on_next_clicked()
    window.update()

    # Paso 5: condición inicial + CN2 (IGRO=0 evita campos condicionales)
    assert window._current_step_key() == "mgt_initial"
    window._igro_selector.current(0)
    window._render_initial_fields()
    window._cn2_entries["C"].insert(0, "88.33")
    window._on_next_clicked()
    window.update()

    # Paso 6: calendario -- se deja vacío, es opcional
    assert window._current_step_key() == "operations"
    window._on_next_clicked()
    window.update()

    # Paso 7: revisión -> crear
    assert window._current_step_key() == "review"
    window._on_next_clicked()

    assert created == [True]
    library = load_library(project)
    assert len(library) == 1
    assert library[0].name == "Test NbS"
    assert library[0].target_lulc == "FRST"
    assert library[0].hru_params["CANMX"] == 3.0
    assert library[0].cn2_by_hsg == {"C": 88.33}


def test_wizard_new_coverage_adds_physiology_step(hidden_root, config, project) -> None:
    window = NbSWizardWindow(hidden_root, config, project)
    window.update()

    window._name_entry.insert(0, "New coverage NbS")
    window._on_next_clicked()
    window.update()

    window._coverage_mode_var.set("new")
    window._render_coverage_body()
    window.update()
    window._new_cpnm_entry.insert(0, "RFOR")
    window._on_next_clicked()
    window.update()

    assert window._current_step_key() == "physiology"
    window.destroy()


def test_wizard_new_coverage_syncs_plant_dat_on_finish(hidden_root, config, project, monkeypatch) -> None:
    """Al terminar el wizard con una cobertura nueva, plant.dat ya debe
    tener el registro configurado -- sin esperar a "Apply" (ver
    scenarios.nbs_apply.sync_new_coverage_to_plant_dat). El "Yes" del
    ConfirmDialog se simula parcheando la clase para que confirme de
    inmediato -- mismo criterio que el resto del código de producción para
    esta confirmación, sin lógica de negocio propia que testear acá (eso
    lo cubre tests/scenarios/test_nbs_apply.py)."""
    import ui.nbs_wizard_window as wizard_module

    monkeypatch.setattr(wizard_module, "ConfirmDialog", lambda master, cfg, *, message, on_confirm: on_confirm())

    window = NbSWizardWindow(hidden_root, config, project)
    window.update()

    window._name_entry.insert(0, "Restored forest NbS")
    window._on_next_clicked()
    window.update()

    window._coverage_mode_var.set("new")
    window._render_coverage_body()
    window.update()
    window._new_cpnm_entry.insert(0, "RFOR")
    window._on_next_clicked()
    window.update()

    assert window._current_step_key() == "physiology"
    frst_index = window._phys_copy_codes.index("FRST")
    window._phys_copy_selector.current(frst_index)
    window._on_physiology_copy_selected()
    window._on_next_clicked()
    window.update()

    assert window._current_step_key() == "copy_from_existing"
    window._on_next_clicked()
    window.update()

    assert window._current_step_key() == "hru_params"
    window._hru_param_entries["CANMX"].insert(0, "3.0")
    window._hru_param_entries["OV_N"].insert(0, "0.12")
    window._on_next_clicked()
    window.update()

    assert window._current_step_key() == "mgt_initial"
    window._igro_selector.current(0)
    window._render_initial_fields()
    window._cn2_entries["C"].insert(0, "88.33")
    window._on_next_clicked()
    window.update()

    assert window._current_step_key() == "operations"
    window._on_next_clicked()
    window.update()

    assert window._current_step_key() == "review"
    window._on_next_clicked()

    library = load_library(project)
    assert len(library) == 1
    icnum = library[0].new_coverage.icnum
    assert icnum == 7  # max(1, 6) + 1 en el plant.dat sintético del fixture

    from swat_io.plant.parser import parse_plant_dat_file

    record = parse_plant_dat_file(project / "TxtInOut" / "plant.dat").get_record_by_cpnm("RFOR")
    assert record is not None
    assert record.icnum == icnum


def test_wizard_rejects_duplicate_name(hidden_root, config, project) -> None:
    from scenarios.nbs import NbSDefinition, add_or_replace

    add_or_replace(
        project,
        NbSDefinition(
            name="Existing NbS", target_lulc="FRST", new_coverage=None,
            hru_params={"CANMX": 1.0, "OV_N": 0.1}, mgt_initial={"IGRO": 0}, cn2_by_hsg={"C": 80.0}, operations=[],
        ),
    )

    window = NbSWizardWindow(hidden_root, config, project)
    window.update()
    window._name_entry.insert(0, "Existing NbS")
    window._on_next_clicked()

    assert window._current_step_key() == "name"  # no avanzó
    assert "Existing NbS" in window._status_label.cget("text")
    window.destroy()


def test_wizard_edit_prefills_state_and_updates_in_place(hidden_root, config, project) -> None:
    from scenarios.nbs import NbSDefinition, add_or_replace

    original = NbSDefinition(
        name="Editable NbS", target_lulc="FRST", new_coverage=None,
        hru_params={"CANMX": 3.0, "OV_N": 0.12, "RSDIN": 0.0},
        mgt_initial={"IGRO": 0}, cn2_by_hsg={"C": 88.33}, operations=[],
        description="Original description",
    )
    add_or_replace(project, original)

    window = NbSWizardWindow(hidden_root, config, project, existing=original)
    window.update()

    # Estado pre-poblado desde la NbS existente, sin tocar nada todavía.
    assert window._name_entry.get() == "Editable NbS"
    assert window._state["target_cpnm"] == "FRST"
    assert window._state["hru_params"]["CANMX"] == 3.0
    assert window._state["cn2_by_hsg"] == {"C": 88.33}

    # Cambiar la descripción y recorrer el resto de los pasos sin tocar nada más.
    window._description_text.delete("1.0", "end")
    window._description_text.insert("1.0", "Updated description")

    for _ in range(6):
        if window._current_step_key() == "review":
            break
        window._on_next_clicked()
        window.update()

    window._on_next_clicked()  # crea/guarda desde el paso review

    library = load_library(project)
    assert len(library) == 1  # se actualizó en el lugar, no se duplicó
    assert library[0].description == "Updated description"
    assert library[0].hru_params["CANMX"] == 3.0


def test_nbs_tab_edit_and_delete_buttons_toggle_with_selection(hidden_root, config, project) -> None:
    from scenarios.nbs import NbSDefinition, add_or_replace

    add_or_replace(
        project,
        NbSDefinition(
            name="Selectable NbS", target_lulc="FRST", new_coverage=None,
            hru_params={"CANMX": 1.0, "OV_N": 0.1}, mgt_initial={"IGRO": 0}, cn2_by_hsg={"C": 80.0}, operations=[],
        ),
    )

    tab = NbSTab(hidden_root, config)
    tab.set_project(project)
    assert tab._edit_button.cget("state") == "disabled"
    assert tab._delete_button.cget("state") == "disabled"

    tab._library_tree.selection_set("Selectable NbS")
    tab._on_library_selection_changed()
    assert tab._edit_button.cget("state") == "normal"
    assert tab._delete_button.cget("state") == "normal"


def test_apply_rereads_library_json_to_pick_up_manual_edits(hidden_root, config, project, monkeypatch) -> None:
    """Pedido explícito del usuario, 2026-08-11: si se edita
    nbs_library.json a mano mientras la app está abierta, Apply debe usar
    el archivo tal como quedó en disco, no self._library (poblado solo al
    abrir el proyecto o crear/editar/borrar una NbS desde la UI, ver
    _refresh_library)."""
    from scenarios.nbs import NbSDefinition, add_or_replace
    from scenarios.nbs_apply import NbSApplyReport

    import ui.tab_nbs as tab_nbs_module

    add_or_replace(
        project,
        NbSDefinition(
            name="Editable NbS", target_lulc="FRST", new_coverage=None,
            hru_params={"CANMX": 1.0, "OV_N": 0.1}, mgt_initial={"IGRO": 0}, cn2_by_hsg={"C": 80.0}, operations=[],
        ),
    )

    tab = NbSTab(hidden_root, config)
    tab.set_project(project)
    tab._nbs_selector.current(0)
    tab._targets = [(1, 1)]

    # Edición manual del JSON en disco, sin pasar por la UI -- self._library
    # sigue con CANMX=1.0 en memoria.
    manual = load_library(project)
    manual[0].hru_params["CANMX"] = 9.9
    save_library(project, manual)

    monkeypatch.setattr(tab_nbs_module, "ConfirmDialog", lambda master, cfg, *, message, on_confirm: on_confirm())
    captured: dict = {}

    def fake_apply_nbs(project_dir, definition, targets):
        captured["canmx"] = definition.hru_params["CANMX"]
        return NbSApplyReport(nbs_name=definition.name, plant_id=None, cpnm=None, results=[])

    monkeypatch.setattr(tab_nbs_module, "apply_nbs", fake_apply_nbs)
    monkeypatch.setattr(
        tab_nbs_module, "run_in_background",
        lambda widget, work, *, on_progress, on_done, on_error, **_kw: on_done(work(lambda _m: None)),
    )

    tab._on_apply_clicked()

    assert captured["canmx"] == 9.9
