from pathlib import Path

import pandas as pd
import pytest

from scenarios.hru_import import parse_hru_import_csv


def _write_hru(path: Path, subbasin: int, hru: int, values: dict[str, float]) -> None:
    lines = [f"Subbasin:{subbasin}   Hru:{hru}   Luse:AGRL   Soil: 1013090         Slope: 0-9999\n"]
    for code, value in values.items():
        lines.append(f"{value:16.4f}    | {code} : synthetic test value\n")
    path.write_text("".join(lines), encoding="utf-8")


@pytest.fixture
def txtinout_dir(tmp_path: Path) -> Path:
    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    _write_hru(txtinout / "000010001.hru", 1, 1, {"HRU_FR": 0.6, "CANMX": 1.0})
    _write_hru(txtinout / "000010002.hru", 1, 2, {"HRU_FR": 0.4, "CANMX": 2.0})
    return txtinout


def _write_csv(path: Path, rows: list[dict]) -> Path:
    csv_path = path / "import.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    return csv_path


def test_parses_partial_subset_of_hrus_and_columns(tmp_path: Path, txtinout_dir: Path) -> None:
    csv_path = _write_csv(tmp_path, [{"subbasin": 1, "hru": 1, "CANMX": 5.5}])

    result = parse_hru_import_csv(csv_path, txtinout_dir, [1])

    assert result == {(1, 1): {"CANMX": 5.5}}


def test_ignores_missing_cells(tmp_path: Path, txtinout_dir: Path) -> None:
    csv_path = _write_csv(
        tmp_path, [{"subbasin": 1, "hru": 1, "CANMX": 5.5, "HRU_FR": None}]
    )

    result = parse_hru_import_csv(csv_path, txtinout_dir, [1])

    assert result == {(1, 1): {"CANMX": 5.5}}


def test_rejects_missing_required_columns(tmp_path: Path, txtinout_dir: Path) -> None:
    csv_path = _write_csv(tmp_path, [{"subbasin": 1, "CANMX": 5.5}])

    with pytest.raises(ValueError, match="hru"):
        parse_hru_import_csv(csv_path, txtinout_dir, [1])


def test_rejects_unknown_subbasin(tmp_path: Path, txtinout_dir: Path) -> None:
    csv_path = _write_csv(tmp_path, [{"subbasin": 99, "hru": 1, "CANMX": 5.5}])

    with pytest.raises(ValueError, match="99"):
        parse_hru_import_csv(csv_path, txtinout_dir, [1])


def test_rejects_unknown_hru(tmp_path: Path, txtinout_dir: Path) -> None:
    csv_path = _write_csv(tmp_path, [{"subbasin": 1, "hru": 99, "CANMX": 5.5}])

    with pytest.raises(ValueError, match="99"):
        parse_hru_import_csv(csv_path, txtinout_dir, [1])


def test_rejects_non_numeric_value(tmp_path: Path, txtinout_dir: Path) -> None:
    csv_path = _write_csv(tmp_path, [{"subbasin": 1, "hru": 1, "CANMX": "abc"}])

    with pytest.raises(ValueError, match="abc"):
        parse_hru_import_csv(csv_path, txtinout_dir, [1])


def test_reports_all_errors_at_once(tmp_path: Path, txtinout_dir: Path) -> None:
    csv_path = _write_csv(
        tmp_path,
        [
            {"subbasin": 1, "hru": 1, "CANMX": "abc"},
            {"subbasin": 99, "hru": 1, "CANMX": 5.5},
        ],
    )

    with pytest.raises(ValueError) as excinfo:
        parse_hru_import_csv(csv_path, txtinout_dir, [1])

    message = str(excinfo.value)
    assert "abc" in message
    assert "99" in message


def test_unknown_parameter_column_is_not_rejected_here(tmp_path: Path, txtinout_dir: Path) -> None:
    """A diferencia de wetland_import.py, no hay lista curada de columnas
    válidas: un nombre de parámetro que no existe en esa HRU puntual se
    acepta aquí y recién falla en Materialize (HRUFile.set_value)."""
    csv_path = _write_csv(tmp_path, [{"subbasin": 1, "hru": 1, "NOT_A_REAL_PARAM": 5.5}])

    result = parse_hru_import_csv(csv_path, txtinout_dir, [1])

    assert result == {(1, 1): {"NOT_A_REAL_PARAM": 5.5}}
