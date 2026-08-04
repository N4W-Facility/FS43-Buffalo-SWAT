import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from scenarios.comparison_export import (
    ComparisonExportError,
    HRUGroupFilter,
    discover_hru_group_options,
    discover_hru_selection_options,
    discover_scenario_dirs,
    export_hru_group_comparison,
    export_hru_point_comparison,
    export_rch_comparison,
    load_hru_variable_aggregation,
    scenario_label,
)
from swat_io.hru_output_parser import HRU_OUTPUT_VARIABLE_COLUMNS, _TABLE, hru_output_db_path
from swat_io.rch_parser import RCH_VARIABLE_COLUMNS, export_rch_timeseries_csvs, rch_timeseries_dir

# -- helpers de fixtures ------------------------------------------------------


def _make_scenario(batch_dir: Path, name: str) -> Path:
    scenario_dir = batch_dir / name
    (scenario_dir / "TxtInOut").mkdir(parents=True)
    return scenario_dir


def _write_hru_file(txtinout_dir: Path, *, sub: int, hru: int, land_use: str, soil: str, slope: str) -> None:
    text = (
        f"Subbasin:{sub}   Hru:{hru}   Luse:{land_use}   Soil: {soil}         Slope: {slope}\n"
        "        0.5000    | HRU_FR : Fraction of subbasin area contained in HRU\n"
    )
    (txtinout_dir / f"0000{sub}000{hru}.hru").write_text(text, encoding="utf-8")


def _write_rch_fixture(scenario_dir: Path, rows: list[dict]) -> None:
    columns = ["date", "reach"] + RCH_VARIABLE_COLUMNS
    df = pd.DataFrame(rows)
    for col in columns:
        if col not in df.columns:
            df[col] = 0.0
    df["date"] = pd.to_datetime(df["date"])
    export_rch_timeseries_csvs(df[columns], rch_timeseries_dir(scenario_dir))


def _write_hru_db(scenario_dir: Path, rows: list[dict]) -> Path:
    """rows: cada dict con al menos date/hru/AREA + las variables que use el test.
    Solo crea las columnas realmente usadas (no las 80) -- comparison_export
    únicamente hace SELECT de columnas puntuales, nunca SELECT *."""
    db_path = hru_output_db_path(scenario_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    variable_columns = sorted({key for row in rows for key in row if key not in ("date", "hru", "sub")})

    conn = sqlite3.connect(db_path)
    try:
        columns_sql = ", ".join(f'"{c}" REAL' for c in variable_columns)
        conn.execute(f"CREATE TABLE {_TABLE} (date TEXT, sub INTEGER, hru INTEGER, {columns_sql})")
        for row in rows:
            columns = ["date", "sub", "hru"] + variable_columns
            values = [row.get("date"), row.get("sub"), row.get("hru")] + [row.get(c) for c in variable_columns]
            placeholders = ", ".join("?" * len(columns))
            conn.execute(f"INSERT INTO {_TABLE} ({', '.join(columns)}) VALUES ({placeholders})", values)
        conn.commit()
    finally:
        conn.close()
    return db_path


# -- discover_scenario_dirs ----------------------------------------------------


def test_discover_scenario_dirs_sorts_numerically_not_alphabetically(tmp_path: Path):
    _make_scenario(tmp_path, "scenario_20pct")
    _make_scenario(tmp_path, "scenario_5pct")
    _make_scenario(tmp_path, "scenario_10pct")

    dirs = discover_scenario_dirs(tmp_path)

    assert [d.name for d in dirs] == ["scenario_5pct", "scenario_10pct", "scenario_20pct"]


def test_discover_scenario_dirs_ignores_folders_without_txtinout(tmp_path: Path):
    _make_scenario(tmp_path, "scenario_10pct")
    (tmp_path / "not_a_scenario").mkdir()

    dirs = discover_scenario_dirs(tmp_path)

    assert [d.name for d in dirs] == ["scenario_10pct"]


# -- aggregation config ---------------------------------------------------------


def test_load_hru_variable_aggregation_covers_all_variables_area_is_sum():
    aggregation = load_hru_variable_aggregation()

    assert set(aggregation) == set(HRU_OUTPUT_VARIABLE_COLUMNS)
    assert aggregation["AREA"] == "sum"
    assert aggregation["WYLD"] == "weighted_mean"


# -- RCH comparison -------------------------------------------------------------


def test_export_rch_comparison_combines_reaches_and_scenarios(tmp_path: Path):
    s10 = _make_scenario(tmp_path, "scenario_10pct")
    s20 = _make_scenario(tmp_path, "scenario_20pct")

    _write_rch_fixture(
        s10,
        [
            {"date": "2017-01-01", "reach": 1, "FLOW_OUT": 5.0},
            {"date": "2017-01-01", "reach": 2, "FLOW_OUT": 8.0},
        ],
    )
    _write_rch_fixture(
        s20,
        [
            {"date": "2017-01-01", "reach": 1, "FLOW_OUT": 4.0},
            {"date": "2017-01-01", "reach": 2, "FLOW_OUT": 7.0},
        ],
    )

    written = export_rch_comparison(tmp_path, ["FLOW_OUT"])

    assert len(written) == 1
    result = pd.read_csv(written[0])
    assert list(result.columns) == ["date", "reach", "scenario_10pct", "scenario_20pct"]
    result = result.sort_values("reach").reset_index(drop=True)
    assert result["scenario_10pct"].tolist() == pytest.approx([5.0, 8.0])
    assert result["scenario_20pct"].tolist() == pytest.approx([4.0, 7.0])


def test_export_rch_comparison_raises_without_scenarios(tmp_path: Path):
    with pytest.raises(ComparisonExportError):
        export_rch_comparison(tmp_path, ["FLOW_OUT"])


def test_export_rch_comparison_raises_without_organized_output(tmp_path: Path):
    _make_scenario(tmp_path, "scenario_10pct")

    with pytest.raises(ComparisonExportError):
        export_rch_comparison(tmp_path, ["FLOW_OUT"])


# -- HRU puntual ------------------------------------------------------------


def test_export_hru_point_comparison_one_column_per_scenario(tmp_path: Path):
    s10 = _make_scenario(tmp_path, "scenario_10pct")
    s20 = _make_scenario(tmp_path, "scenario_20pct")

    _write_hru_db(s10, [{"date": "2017-01-01", "hru": 5, "AREA": 1.0, "WYLD": 100.0}])
    _write_hru_db(s20, [{"date": "2017-01-01", "hru": 5, "AREA": 1.0, "WYLD": 90.0}])

    written = export_hru_point_comparison(tmp_path, sub=1, hru=5, variables=["WYLD"])

    assert len(written) == 1
    result = pd.read_csv(written[0])
    assert list(result.columns) == ["date", "scenario_10pct", "scenario_20pct"]
    assert result["scenario_10pct"].tolist() == pytest.approx([100.0])
    assert result["scenario_20pct"].tolist() == pytest.approx([90.0])


def test_export_hru_point_comparison_raises_when_no_data(tmp_path: Path):
    _make_scenario(tmp_path, "scenario_10pct")

    with pytest.raises(ComparisonExportError):
        export_hru_point_comparison(tmp_path, sub=1, hru=5, variables=["WYLD"])


# -- HRU agrupado -------------------------------------------------------------


def _build_group_batch(tmp_path: Path) -> tuple[Path, Path]:
    s10 = _make_scenario(tmp_path, "scenario_10pct")
    s20 = _make_scenario(tmp_path, "scenario_20pct")

    # Sub 1: HRU 1 y 2 son FRST (bosque), HRU 3 es PAST -- clasificación
    # estable entre escenarios (solo cambia HRU_FR, no se escribe acá).
    _write_hru_file(s10 / "TxtInOut", sub=1, hru=1, land_use="FRST", soil="1013090", slope="0-9999")
    _write_hru_file(s10 / "TxtInOut", sub=1, hru=2, land_use="FRST", soil="1013090", slope="0-9999")
    _write_hru_file(s10 / "TxtInOut", sub=1, hru=3, land_use="PAST", soil="1013090", slope="0-9999")
    _write_hru_file(s10 / "TxtInOut", sub=2, hru=4, land_use="FRST", soil="1013090", slope="0-9999")

    _write_hru_db(
        s10,
        [
            {"date": "2017-01-01", "sub": 1, "hru": 1, "AREA": 1.0, "WYLD": 100.0},
            {"date": "2017-01-01", "sub": 1, "hru": 2, "AREA": 3.0, "WYLD": 200.0},
            {"date": "2017-01-01", "sub": 1, "hru": 3, "AREA": 5.0, "WYLD": 999.0},  # PAST, no debe entrar
            {"date": "2017-01-01", "sub": 2, "hru": 4, "AREA": 2.0, "WYLD": 50.0},
        ],
    )
    _write_hru_db(
        s20,
        [
            {"date": "2017-01-01", "sub": 1, "hru": 1, "AREA": 1.0, "WYLD": 110.0},
            {"date": "2017-01-01", "sub": 1, "hru": 2, "AREA": 3.0, "WYLD": 210.0},
            {"date": "2017-01-01", "sub": 1, "hru": 3, "AREA": 5.0, "WYLD": 999.0},
            {"date": "2017-01-01", "sub": 2, "hru": 4, "AREA": 2.0, "WYLD": 60.0},
        ],
    )
    return s10, s20


def test_export_hru_group_comparison_basin_scope_weighted_mean(tmp_path: Path):
    _build_group_batch(tmp_path)

    written = export_hru_group_comparison(
        tmp_path,
        HRUGroupFilter(land_uses=["FRST"]),
        ["WYLD"],
        scope="basin",
    )

    assert len(written) == 1
    result = pd.read_csv(written[0])
    assert list(result.columns) == ["date", "scenario_10pct", "scenario_20pct"]
    # HRU 1,2,4 son FRST (AREA 1,3,2 / WYLD 100,200,50) -> weighted mean:
    expected_10pct = (1 * 100 + 3 * 200 + 2 * 50) / (1 + 3 + 2)
    expected_20pct = (1 * 110 + 3 * 210 + 2 * 60) / (1 + 3 + 2)
    assert result["scenario_10pct"].iloc[0] == pytest.approx(expected_10pct)
    assert result["scenario_20pct"].iloc[0] == pytest.approx(expected_20pct)


def test_export_hru_group_comparison_area_variable_uses_sum(tmp_path: Path):
    _build_group_batch(tmp_path)

    written = export_hru_group_comparison(
        tmp_path,
        HRUGroupFilter(land_uses=["FRST"]),
        ["AREA"],
        scope="basin",
    )

    result = pd.read_csv(written[0])
    assert result["scenario_10pct"].iloc[0] == pytest.approx(1.0 + 3.0 + 2.0)


def test_export_hru_group_comparison_scope_specific_subbasins_breaks_out_by_sub(tmp_path: Path):
    _build_group_batch(tmp_path)

    written = export_hru_group_comparison(
        tmp_path,
        HRUGroupFilter(land_uses=["FRST"]),
        ["WYLD"],
        scope=[1, 2],
    )

    result = pd.read_csv(written[0]).sort_values("sub").reset_index(drop=True)
    assert list(result.columns) == ["date", "sub", "scenario_10pct", "scenario_20pct"]
    sub1_expected = (1 * 100 + 3 * 200) / (1 + 3)
    sub2_expected = 50.0
    assert result.loc[result["sub"] == 1, "scenario_10pct"].iloc[0] == pytest.approx(sub1_expected)
    assert result.loc[result["sub"] == 2, "scenario_10pct"].iloc[0] == pytest.approx(sub2_expected)


def test_export_hru_group_comparison_raises_when_no_hru_matches_filter(tmp_path: Path):
    _build_group_batch(tmp_path)

    with pytest.raises(ComparisonExportError):
        export_hru_group_comparison(
            tmp_path,
            HRUGroupFilter(land_uses=["URBAN_DOES_NOT_EXIST"]),
            ["WYLD"],
            scope="basin",
        )


# -- opciones para la UI --------------------------------------------------------


def test_discover_hru_group_options_reads_from_first_scenario(tmp_path: Path):
    _build_group_batch(tmp_path)

    land_uses, slopes, soils = discover_hru_group_options(tmp_path)

    assert land_uses == ["FRST", "PAST"]


def test_discover_hru_selection_options_reads_subbasins_and_hrus(tmp_path: Path):
    s10, _s20 = _build_group_batch(tmp_path)

    subbasins, hrus_by_sub = discover_hru_selection_options(tmp_path)

    assert subbasins == [1, 2]
    assert hrus_by_sub[1] == [1, 2, 3]
    assert hrus_by_sub[2] == [4]


def test_scenario_label_is_the_folder_name(tmp_path: Path):
    scenario_dir = _make_scenario(tmp_path, "scenario_10pct")
    assert scenario_label(scenario_dir) == "scenario_10pct"
