"""Smoke tests con un root de Tk real (oculto, sin mainloop) para la
ventana de exportación comparativa de Batch Scenarios y para HRU Results/
Batch tab en general.

No son tests de lógica (eso ya lo cubre tests/scenarios/test_comparison_export.py):
son para atrapar errores que solo aparecen al construir/mutar widgets de
verdad -- ej. un TclError porque un CTkScrollableFrame no se puede
reconstruir dentro de __init__ antes de que el event loop haga su primer
ciclo (bug real encontrado y corregido en scenario_comparison_window.py:
_replace_checklist_options no puede usar checklist.master, porque
CTkScrollableFrame redirige pack()/master a un canvas interno propio, no
al contenedor real donde se empaquetó).

El flujo de exportación real (con hilo de fondo, ver ui/tasks.py) vive
aparte en test_scenario_comparison_export_e2e.py -- ver el docstring de
test_scenario_comparison_window_initial_batch_dir_does_not_crash más abajo
para el porqué de separarlo."""
import sqlite3
from pathlib import Path

import customtkinter as ctk
import pandas as pd
import pytest

from config.settings import ConfigManager
from swat_io.hru_output_parser import _TABLE, hru_output_db_path
from swat_io.rch_parser import RCH_VARIABLE_COLUMNS, export_rch_timeseries_csvs, rch_timeseries_dir
from ui.scenario_comparison_window import ScenarioComparisonWindow
from ui.tab_batch import BatchTab
from ui.tab_hru_results import HruResultsTab
from ui.variable_selection_window import VariableSelectionWindow


def _build_synthetic_batch(batch_dir: Path) -> None:
    """Batch de 2 escenarios con output.rch y output.hru ya organizados
    (mismo shape que engine.batch_run.run_land_cover_batch deja de verdad),
    para no depender de correr swat2012.exe en un test. Duplicado a
    propósito en test_scenario_comparison_export_e2e.py: tests/ no es un
    paquete (sin __init__.py), así que un import cruzado entre archivos de
    test dependería del orden de inserción en sys.path de pytest -- más
    frágil que repetir este helper chico."""
    for name, flow, wyld in (("scenario_10pct", 5.0, 100.0), ("scenario_20pct", 4.0, 90.0)):
        scenario_dir = batch_dir / name
        (scenario_dir / "TxtInOut").mkdir(parents=True)

        rows = [{"date": "2017-01-01", "reach": 1, "FLOW_OUT": flow}]
        columns = ["date", "reach"] + RCH_VARIABLE_COLUMNS
        df = pd.DataFrame(rows)
        for col in columns:
            if col not in df.columns:
                df[col] = 0.0
        df["date"] = pd.to_datetime(df["date"])
        export_rch_timeseries_csvs(df[columns], rch_timeseries_dir(scenario_dir))

        (scenario_dir / "TxtInOut" / "000010001.hru").write_text(
            "Subbasin:1   Hru:1   Luse:FRST   Soil: 1013090         Slope: 0-9999\n"
            "        0.5000    | HRU_FR : Fraction of subbasin area contained in HRU\n",
            encoding="utf-8",
        )
        db_path = hru_output_db_path(scenario_dir)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute(f'CREATE TABLE {_TABLE} (date TEXT, sub INTEGER, hru INTEGER, "AREA" REAL, "WYLD" REAL)')
        conn.execute(f"INSERT INTO {_TABLE} VALUES (?,?,?,?,?)", ("2017-01-01", 1, 1, 1.0, wyld))
        conn.commit()
        conn.close()


@pytest.fixture(scope="module")
def config() -> ConfigManager:
    cfg = ConfigManager()
    cfg.load_all()
    return cfg


@pytest.fixture(scope="module")
def hidden_root():
    """Un único root de Tk para todo el módulo -- customtkinter mantiene
    trackers a nivel de clase (AppearanceModeTracker/ScalingTracker) que
    programan callbacks vía widget.after() atados a la instancia de root;
    crear y destruir un CTk() por test dejaba esos callbacks apuntando a
    roots ya destruidos (writes a stderr con "invalid command name ...
    after script"). Cada test solo destruye las ventanas (Toplevel) que
    crea, nunca el root."""
    root = ctk.CTk()
    root.withdraw()
    yield root
    root.destroy()


def test_batch_tab_builds_and_sets_project(hidden_root, config):
    tab = BatchTab(hidden_root, config)
    tab.set_project(Path("C:/fake_project"))


def test_hru_results_tab_builds_without_project(hidden_root, config):
    HruResultsTab(hidden_root, config)


def test_variable_selection_window_select_all_and_confirm(hidden_root, config):
    captured = []
    window = VariableSelectionWindow(
        hidden_root,
        config,
        title_key="hru_results_tab.select_variables_window_title",
        options=[("A", "Label A"), ("B", "Label B")],
        on_confirm=lambda codes: captured.append(codes),
    )
    window.update()
    window._checklist.select_all()
    assert window._checklist.selected() == ["A", "B"]
    window.destroy()


def test_scenario_comparison_window_builds_with_no_batch_dir(hidden_root, config):
    window = ScenarioComparisonWindow(hidden_root, config)
    window.update()
    window._on_export_clicked()
    assert "batch folder" in window._status_label.cget("text").lower()
    window.destroy()


def test_scenario_comparison_window_toggle_panels_does_not_raise(hidden_root, config):
    """Reproduce el flujo de alternar fuente/modo/alcance sin ninguna
    carpeta de batch elegida todavía -- solo construcción de widgets."""
    window = ScenarioComparisonWindow(hidden_root, config)
    window.update()

    window._source_selector.set(config.text("scenario_comparison_window.source_sub"))
    window._refresh_source_panels()
    window._source_selector.set(config.text("scenario_comparison_window.source_hru"))
    window._refresh_source_panels()
    window._hru_mode_selector.set(config.text("scenario_comparison_window.hru_mode_group"))
    window._refresh_hru_mode_panels()
    window._scope_selector.set(config.text("scenario_comparison_window.group_scope_subbasins"))
    window._refresh_scope_panel()
    window._scope_selector.set(config.text("scenario_comparison_window.group_scope_basin"))
    window._refresh_scope_panel()

    window.destroy()


def test_scenario_comparison_window_initial_batch_dir_does_not_crash(hidden_root, config, tmp_path):
    """Regresión del bug real: abrir la ventana con initial_batch_dir ya
    seteado (pasa cuando el usuario ya eligió una carpeta destino en Batch
    Scenarios y aprieta "Compare scenarios...") reconstruye los checklists
    de cobertura/pendiente/suelo/subcuencas dentro de __init__, antes de
    que haya corrido ni un ciclo del event loop. El resto del flujo
    end-to-end (export real con hilo de fondo) vive aparte en
    test_scenario_comparison_export_e2e.py -- deliberadamente en su propio
    módulo/proceso pytest, no en este archivo: encadenar ese export después
    de varios tests con ventanas de Tk en la misma sesión de pytest (a
    diferencia de un script suelto o de correr ese test solo) hacía que el
    sondeo de run_in_background nunca viera el resultado -- no reproducido
    fuera de pytest ni al aislar ese test solo, así que se lo separó en vez
    de perseguir la causa exacta en los schedulers internos de
    customtkinter."""
    batch_dir = tmp_path / "batch"
    _build_synthetic_batch(batch_dir)

    window = ScenarioComparisonWindow(hidden_root, config, initial_batch_dir=batch_dir)
    assert "2 scenario" in window._status_label.cget("text")
    window.destroy()
