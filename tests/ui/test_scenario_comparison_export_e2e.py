"""Flujo end-to-end real de la exportación comparativa: construye un batch
sintético de 2 escenarios (mismo shape que engine.batch_run deja en disco:
tool_outputs/rch_timeseries/*.csv + tool_outputs/hru_timeseries.db por
escenario), maneja la ventana igual que lo haría un usuario (Browse ->
elegir fuente/variables/modo -> Export) y verifica los CSV combinados
resultantes -- sin correr swat2012.exe.

Deliberadamente en su propio archivo/proceso de pytest, separado de
test_scenario_comparison_window_smoke.py -- ver el docstring de
test_scenario_comparison_window_initial_batch_dir_does_not_crash en ese
archivo para el porqué."""
import sqlite3
import time
from pathlib import Path

import customtkinter as ctk
import pandas as pd
import pytest

from config.settings import ConfigManager
from swat_io.hru_output_parser import _TABLE, hru_output_db_path
from swat_io.rch_parser import RCH_VARIABLE_COLUMNS, export_rch_timeseries_csvs, rch_timeseries_dir
from ui.scenario_comparison_window import ScenarioComparisonWindow


def _build_synthetic_batch(batch_dir: Path) -> None:
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


def _pump(root, predicate, *, timeout_s: float = 10.0) -> None:
    """Corre el event loop a mano hasta que predicate() sea True o se
    agote el tiempo -- necesario porque run_in_background usa widget.after()
    para sondear su cola, y en un test sin mainloop nadie más lo hace."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.02)


def test_scenario_comparison_window_exports_rch_and_hru_group_end_to_end(tmp_path):
    batch_dir = tmp_path / "batch"
    _build_synthetic_batch(batch_dir)

    config = ConfigManager()
    config.load_all()
    root = ctk.CTk()
    root.withdraw()
    try:
        window = ScenarioComparisonWindow(root, config, initial_batch_dir=batch_dir)

        window._source_selector.set(config.text("scenario_comparison_window.source_rch"))
        window._refresh_source_panels()
        window._rch_checklist.set_selected({"FLOW_OUT"})
        window._on_export_clicked()
        _pump(root, lambda: "Wrote" in window._status_label.cget("text"))

        rch_csv = batch_dir / "comparison_exports" / "rch_FLOW_OUT.csv"
        assert rch_csv.is_file()
        result = pd.read_csv(rch_csv)
        assert result["scenario_10pct"].tolist() == pytest.approx([5.0])
        assert result["scenario_20pct"].tolist() == pytest.approx([4.0])

        window._source_selector.set(config.text("scenario_comparison_window.source_hru"))
        window._refresh_source_panels()
        window._hru_mode_selector.set(config.text("scenario_comparison_window.hru_mode_group"))
        window._refresh_hru_mode_panels()
        window._land_use_checklist.set_selected({"FRST"})
        window._hru_checklist.set_selected({"WYLD"})
        window._on_export_clicked()
        _pump(root, lambda: "Wrote" in window._status_label.cget("text"))

        hru_csv = batch_dir / "comparison_exports" / "hru_group_WYLD.csv"
        assert hru_csv.is_file()
        result = pd.read_csv(hru_csv)
        assert result["scenario_10pct"].tolist() == pytest.approx([100.0])
        assert result["scenario_20pct"].tolist() == pytest.approx([90.0])

        window.destroy()
    finally:
        root.destroy()
