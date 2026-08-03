from pathlib import Path

import pandas as pd
import pytest

from swat_io.cio_parser import PRINT_FREQUENCY_DAILY, PRINT_FREQUENCY_MONTHLY, PRINT_FREQUENCY_YEARLY, RunSettings
from swat_io.hru_output_parser import (
    HRU_OUTPUT_VARIABLE_COLUMNS,
    HruOutputParseError,
    _VARIABLE_COLSPECS,
    build_hru_output_database,
    export_single_series_csv,
    export_subbasin_variable_csv,
    list_hrus_for_subbasin,
    list_subbasins,
    read_hru_series,
    read_subbasin_variable_wide,
)

_PRELUDE = (
    "1  1\n"
    "    SWAT Sep 7    VER 2018/Rev 670\n"
    "\n"
    "    General Input/Output section (file.cio):\n"
    "    9/7/2021 12:00:00 AM ARCGIS-SWAT interface AV\n"
    "\n"
    "\n"
    "\n"
    "LULC  HRU       GIS  SUB  MGT  MON   AREAkm2  PRECIPmm ...\n"
)


def _prefix(sub: int, hru: int, mon) -> str:
    tokens = ["LULC", str(hru), "000010001", str(sub), "0", str(mon)]
    return " ".join(tokens).ljust(34)


def _variables_block(overrides: dict[str, float] | None = None) -> str:
    overrides = overrides or {}
    parts = []
    for name, (start, end) in zip(HRU_OUTPUT_VARIABLE_COLUMNS, _VARIABLE_COLSPECS):
        width = end - start
        value = overrides.get(name, 0.0)
        token = f"{value:.3f}"
        if len(token) > width:
            token = f"{value:.1f}"
        parts.append(token.rjust(width))
    return "".join(parts)


def _row(sub: int, hru: int, mon, overrides: dict[str, float] | None = None) -> str:
    return _prefix(sub, hru, mon) + _variables_block(overrides) + "\n"


def _write_hru(path: Path, rows: list[str]) -> None:
    path.write_text(_PRELUDE + "".join(rows), encoding="utf-8")


def _settings(*, print_frequency: int, start_year: int, end_year: int, years_to_skip: int) -> RunSettings:
    return RunSettings(
        start_year=start_year,
        end_year=end_year,
        n_years=end_year - start_year + 1,
        years_to_skip=years_to_skip,
        print_frequency=print_frequency,
    )


def test_build_hru_output_database_yearly_drops_average_annual_summary_row(tmp_path: Path) -> None:
    hru_path = tmp_path / "output.hru"
    _write_hru(
        hru_path,
        [
            _row(1, 1, 2017, {"AREA": 20.21}),
            _row(1, 1, 2018, {"AREA": 20.21}),
            _row(1, 1, 2019, {"AREA": 20.21}),
            _row(1, 1, 3),  # "average annual" (3 años promediados), no un año calendario
            _row(1, 2, 2017, {"AREA": 5.0}),
            _row(1, 2, 2018, {"AREA": 5.0}),
            _row(1, 2, 2019, {"AREA": 5.0}),
            _row(1, 2, 3),
        ],
    )
    settings = _settings(print_frequency=PRINT_FREQUENCY_YEARLY, start_year=2012, end_year=2019, years_to_skip=5)
    db_path = tmp_path / "hru_timeseries.db"

    summary = build_hru_output_database(hru_path, settings, db_path)

    assert summary["rows"] == 6
    assert summary["hrus"] == 2
    assert summary["subbasins"] == 1
    assert list_subbasins(db_path) == [1]
    assert list_hrus_for_subbasin(db_path, 1) == [1, 2]

    series = read_hru_series(db_path, 1, "AREA")
    assert len(series) == 3
    assert series.tolist() == pytest.approx([20.21, 20.21, 20.21])
    assert list(series.index.year) == [2017, 2018, 2019]


def test_build_hru_output_database_raises_when_no_data_rows(tmp_path: Path) -> None:
    hru_path = tmp_path / "output.hru"
    hru_path.write_text(_PRELUDE, encoding="utf-8")
    settings = _settings(print_frequency=PRINT_FREQUENCY_YEARLY, start_year=2012, end_year=2019, years_to_skip=5)

    with pytest.raises(HruOutputParseError):
        build_hru_output_database(hru_path, settings, tmp_path / "hru_timeseries.db")


def test_build_hru_output_database_raises_on_malformed_prefix(tmp_path: Path) -> None:
    hru_path = tmp_path / "output.hru"
    bad_line = "LULC 1 2017" + _variables_block() + "\n"  # prefijo con menos de 6 tokens
    _write_hru(hru_path, [bad_line])
    settings = _settings(print_frequency=PRINT_FREQUENCY_YEARLY, start_year=2012, end_year=2019, years_to_skip=5)

    with pytest.raises(HruOutputParseError):
        build_hru_output_database(hru_path, settings, tmp_path / "hru_timeseries.db")


def test_build_hru_output_database_monthly_drops_annual_summary_row_and_assigns_dates(tmp_path: Path) -> None:
    hru_path = tmp_path / "output.hru"
    rows = [_row(1, 1, m) for m in range(1, 13)] + [_row(1, 1, 2018)]
    rows += [_row(1, 1, m) for m in range(1, 13)] + [_row(1, 1, 2019)]
    _write_hru(hru_path, rows)
    settings = _settings(print_frequency=PRINT_FREQUENCY_MONTHLY, start_year=2016, end_year=2019, years_to_skip=2)
    db_path = tmp_path / "hru_timeseries.db"

    summary = build_hru_output_database(hru_path, settings, db_path)

    assert summary["rows"] == 24
    series = read_hru_series(db_path, 1, "AREA")
    assert len(series) == 24
    assert series.index[0] == pd.Timestamp("2018-01-01")
    assert series.index[11] == pd.Timestamp("2018-12-01")
    assert series.index[12] == pd.Timestamp("2019-01-01")
    assert series.index[-1] == pd.Timestamp("2019-12-01")


def test_build_hru_output_database_daily_rolls_over_year_on_leap_year(tmp_path: Path) -> None:
    hru_path = tmp_path / "output.hru"
    rows = [_row(1, 1, d) for d in range(1, 367)]  # 2020 es bisiesto: 366 días
    _write_hru(hru_path, rows)
    settings = _settings(print_frequency=PRINT_FREQUENCY_DAILY, start_year=2020, end_year=2020, years_to_skip=0)
    db_path = tmp_path / "hru_timeseries.db"

    summary = build_hru_output_database(hru_path, settings, db_path)

    assert summary["rows"] == 366
    series = read_hru_series(db_path, 1, "AREA")
    assert series.index[0] == pd.Timestamp("2020-01-01")
    assert series.index[-1] == pd.Timestamp("2020-12-31")


def test_overflow_asterisks_become_nan(tmp_path: Path) -> None:
    hru_path = tmp_path / "output.hru"
    prefix = _prefix(1, 1, 2017)
    block = list(_variables_block())
    start, end = _VARIABLE_COLSPECS[0]  # AREA
    for i in range(start - 34, end - 34):
        block[i] = "*"
    line = prefix + "".join(block) + "\n"
    _write_hru(hru_path, [line])
    settings = _settings(print_frequency=PRINT_FREQUENCY_YEARLY, start_year=2012, end_year=2019, years_to_skip=5)
    db_path = tmp_path / "hru_timeseries.db"

    build_hru_output_database(hru_path, settings, db_path)

    series = read_hru_series(db_path, 1, "AREA")
    assert pd.isna(series.iloc[0])


def test_read_subbasin_variable_wide_and_export_round_trip(tmp_path: Path) -> None:
    hru_path = tmp_path / "output.hru"
    _write_hru(
        hru_path,
        [
            _row(1, 1, 2017, {"WYLD": 100.0}),
            _row(1, 2, 2017, {"WYLD": 200.0}),
            _row(2, 3, 2017, {"WYLD": 300.0}),
        ],
    )
    settings = _settings(print_frequency=PRINT_FREQUENCY_YEARLY, start_year=2012, end_year=2017, years_to_skip=5)
    db_path = tmp_path / "hru_timeseries.db"
    build_hru_output_database(hru_path, settings, db_path)

    wide = read_subbasin_variable_wide(db_path, 1, "WYLD")
    assert list(wide.columns) == ["hru_1", "hru_2"]
    assert wide.iloc[0].tolist() == pytest.approx([100.0, 200.0])

    subbasin_csv = export_subbasin_variable_csv(db_path, 1, "WYLD", tmp_path / "sub1_wyld.csv")
    reloaded = pd.read_csv(subbasin_csv)
    assert list(reloaded.columns) == ["date", "hru_1", "hru_2"]

    series_csv = export_single_series_csv(db_path, 3, "WYLD", tmp_path / "hru3_wyld.csv")
    reloaded_series = pd.read_csv(series_csv)
    assert reloaded_series["WYLD"].tolist() == pytest.approx([300.0])
