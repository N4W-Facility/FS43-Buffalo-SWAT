from pathlib import Path

import pandas as pd
import pytest

from scenarios.hru_draft import (
    build_hru_table,
    effective_hru_fr_sum,
    export_hru_table_csv,
    list_subbasin_hru_files,
    load_subbasin_hru_files,
    subbasin_hru_fr_sum,
    write_hru_values,
)
from scenarios.hru_import import parse_hru_import_csv


def _write_hru(path: Path, subbasin: int, hru: int, values: dict[str, float]) -> None:
    lines = [f"Subbasin:{subbasin}   Hru:{hru}   Luse:AGRL   Soil: 1013090         Slope: 0-9999\n"]
    for code, value in values.items():
        lines.append(f"{value:16.4f}    | {code} : synthetic test value\n")
    path.write_text("".join(lines), encoding="utf-8")


def test_list_and_load_subbasin_hru_files_scoped_to_subbasin(tmp_path: Path) -> None:
    txtinout_dir = tmp_path / "TxtInOut"
    txtinout_dir.mkdir()
    _write_hru(txtinout_dir / "000010001.hru", 1, 1, {"HRU_FR": 0.6, "CANMX": 1.0})
    _write_hru(txtinout_dir / "000010002.hru", 1, 2, {"HRU_FR": 0.4, "CANMX": 2.0})
    _write_hru(txtinout_dir / "000020001.hru", 2, 1, {"HRU_FR": 1.0, "CANMX": 3.0})

    files = list_subbasin_hru_files(txtinout_dir, 1)
    assert [p.name for p in files] == ["000010001.hru", "000010002.hru"]

    hru_files = load_subbasin_hru_files(txtinout_dir, 1)
    assert set(hru_files) == {1, 2}


def test_build_hru_table_has_one_row_per_hru(tmp_path: Path) -> None:
    txtinout_dir = tmp_path / "TxtInOut"
    txtinout_dir.mkdir()
    _write_hru(txtinout_dir / "000010001.hru", 1, 1, {"HRU_FR": 0.6, "CANMX": 1.0})
    _write_hru(txtinout_dir / "000010002.hru", 1, 2, {"HRU_FR": 0.4, "CANMX": 2.0})

    table = build_hru_table(load_subbasin_hru_files(txtinout_dir, 1))

    assert list(table.index) == [1, 2]
    assert set(table.columns) == {"HRU_FR", "CANMX"}
    assert table.loc[1, "CANMX"] == 1.0
    assert table.loc[2, "CANMX"] == 2.0


def test_write_hru_values_persists_in_place(tmp_path: Path) -> None:
    txtinout_dir = tmp_path / "TxtInOut"
    txtinout_dir.mkdir()
    _write_hru(txtinout_dir / "000010001.hru", 1, 1, {"HRU_FR": 0.6, "CANMX": 1.0})

    hru_files = load_subbasin_hru_files(txtinout_dir, 1)
    write_hru_values(hru_files[1], {"CANMX": 5.5})

    reloaded = load_subbasin_hru_files(txtinout_dir, 1)
    assert reloaded[1].get_value("CANMX") == 5.5
    assert reloaded[1].get_value("HRU_FR") == 0.6


def test_export_hru_table_csv_has_subbasin_and_hru_columns(tmp_path: Path) -> None:
    txtinout_dir = tmp_path / "TxtInOut"
    txtinout_dir.mkdir()
    _write_hru(txtinout_dir / "000010001.hru", 1, 1, {"HRU_FR": 0.6, "CANMX": 1.0})
    _write_hru(txtinout_dir / "000010002.hru", 1, 2, {"HRU_FR": 0.4, "CANMX": 2.0})

    table = build_hru_table(load_subbasin_hru_files(txtinout_dir, 1))
    csv_path = export_hru_table_csv(1, table, tmp_path / "export.csv")

    exported = pd.read_csv(csv_path)
    assert list(exported.columns[:2]) == ["subbasin", "hru"]
    assert set(exported["subbasin"]) == {1}
    assert set(exported["hru"]) == {1, 2}
    assert exported.loc[exported["hru"] == 2, "CANMX"].iloc[0] == 2.0


def test_export_hru_table_csv_round_trips_through_import(tmp_path: Path) -> None:
    """El export es explícitamente una plantilla para el import masivo:
    exportar y reimportar sin tocar nada debe reproducir los mismos
    valores en staging."""
    txtinout_dir = tmp_path / "TxtInOut"
    txtinout_dir.mkdir()
    _write_hru(txtinout_dir / "000010001.hru", 1, 1, {"HRU_FR": 0.6, "CANMX": 1.0})
    _write_hru(txtinout_dir / "000010002.hru", 1, 2, {"HRU_FR": 0.4, "CANMX": 2.0})

    table = build_hru_table(load_subbasin_hru_files(txtinout_dir, 1))
    csv_path = export_hru_table_csv(1, table, tmp_path / "export.csv")

    staged = parse_hru_import_csv(csv_path, txtinout_dir, [1])

    assert staged == {
        (1, 1): {"HRU_FR": 0.6, "CANMX": 1.0},
        (1, 2): {"HRU_FR": 0.4, "CANMX": 2.0},
    }


def test_effective_hru_fr_sum_uses_disk_values_without_staging(tmp_path: Path) -> None:
    txtinout_dir = tmp_path / "TxtInOut"
    txtinout_dir.mkdir()
    _write_hru(txtinout_dir / "000010001.hru", 1, 1, {"HRU_FR": 0.6, "CANMX": 1.0})
    _write_hru(txtinout_dir / "000010002.hru", 1, 2, {"HRU_FR": 0.4, "CANMX": 2.0})

    table = build_hru_table(load_subbasin_hru_files(txtinout_dir, 1))

    assert effective_hru_fr_sum(table) == pytest.approx(1.0)


def test_effective_hru_fr_sum_prefers_staged_value_over_disk(tmp_path: Path) -> None:
    txtinout_dir = tmp_path / "TxtInOut"
    txtinout_dir.mkdir()
    _write_hru(txtinout_dir / "000010001.hru", 1, 1, {"HRU_FR": 0.6, "CANMX": 1.0})
    _write_hru(txtinout_dir / "000010002.hru", 1, 2, {"HRU_FR": 0.4, "CANMX": 2.0})

    table = build_hru_table(load_subbasin_hru_files(txtinout_dir, 1))
    staged = {1: {"HRU_FR": 0.9}}

    assert effective_hru_fr_sum(table, staged) == pytest.approx(1.3)


def test_effective_hru_fr_sum_none_without_hru_fr_column(tmp_path: Path) -> None:
    txtinout_dir = tmp_path / "TxtInOut"
    txtinout_dir.mkdir()
    _write_hru(txtinout_dir / "000010001.hru", 1, 1, {"CANMX": 1.0})

    table = build_hru_table(load_subbasin_hru_files(txtinout_dir, 1))

    assert effective_hru_fr_sum(table) is None


def test_subbasin_hru_fr_sum_reads_from_disk(tmp_path: Path) -> None:
    txtinout_dir = tmp_path / "TxtInOut"
    txtinout_dir.mkdir()
    _write_hru(txtinout_dir / "000010001.hru", 1, 1, {"HRU_FR": 0.6, "CANMX": 1.0})
    _write_hru(txtinout_dir / "000010002.hru", 1, 2, {"HRU_FR": 0.5, "CANMX": 2.0})

    hru_files = load_subbasin_hru_files(txtinout_dir, 1)

    assert subbasin_hru_fr_sum(hru_files) == pytest.approx(1.1)


def test_subbasin_hru_fr_sum_none_without_hru_fr(tmp_path: Path) -> None:
    txtinout_dir = tmp_path / "TxtInOut"
    txtinout_dir.mkdir()
    _write_hru(txtinout_dir / "000010001.hru", 1, 1, {"CANMX": 1.0})

    hru_files = load_subbasin_hru_files(txtinout_dir, 1)

    assert subbasin_hru_fr_sum(hru_files) is None
