"""Smoke tests con un root de Tk real (oculto, sin mainloop) para la
ventana de síntesis de Apply (ui/nbs_apply_summary_window.py) -- mismo
patrón que test_nbs_tab_smoke.py: no son tests de lógica de negocio (esa
vive en scenarios/nbs_apply.py, ver tests/scenarios/test_nbs_apply.py), son
para atrapar errores que solo aparecen al construir/mutar widgets de
verdad, y para verificar la tabla + el filtro "errors only"."""
from __future__ import annotations

from pathlib import Path

import customtkinter as ctk
import pytest

from config.settings import ConfigManager
from scenarios.nbs_apply import NbSApplyHRUResult, NbSApplyReport
from ui.nbs_apply_summary_window import NbSApplySummaryWindow


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


def _sample_report() -> NbSApplyReport:
    return NbSApplyReport(
        nbs_name="Restore forest",
        plant_id=6,
        cpnm="FRST",
        results=[
            NbSApplyHRUResult(1, 1, "applied", hru_fr=0.5),
            NbSApplyHRUResult(1, 2, "applied", hru_fr=0.25),
            NbSApplyHRUResult(99, 999, "error", "HRU file not found.", hru_fr=None),
        ],
    )


def test_summary_window_lists_all_results_by_default(hidden_root, config, tmp_path: Path) -> None:
    window = NbSApplySummaryWindow(hidden_root, config, report=_sample_report(), csv_path=tmp_path / "report.csv")
    window.update()

    rows = window._tree.get_children()
    assert len(rows) == 3
    window.destroy()


def test_summary_window_errors_only_filter(hidden_root, config, tmp_path: Path) -> None:
    window = NbSApplySummaryWindow(hidden_root, config, report=_sample_report(), csv_path=tmp_path / "report.csv")
    window.update()

    window._errors_only_check.select()
    window._on_errors_only_toggled()

    rows = window._tree.get_children()
    assert len(rows) == 1
    values = window._tree.item(rows[0], "values")
    assert values[0] == "99"
    assert values[1] == "999"
    window.destroy()


def test_summary_window_counts_label_reflects_report(hidden_root, config, tmp_path: Path) -> None:
    window = NbSApplySummaryWindow(hidden_root, config, report=_sample_report(), csv_path=tmp_path / "report.csv")
    window.update()

    assert window._counts_label.cget("text") == "2/3 HRU applied (1 error(s))."
    window.destroy()
