from pathlib import Path

import pandas as pd
import pytest

from swat_io.cio_parser import PRINT_FREQUENCY_DAILY, PRINT_FREQUENCY_MONTHLY, PRINT_FREQUENCY_YEARLY, RunSettings
from swat_io.rch_parser import (
    RCH_VARIABLE_COLUMNS,
    RchParseError,
    build_rch_timeseries,
    export_rch_timeseries_csvs,
    parse_rch_file,
    read_rch_timeseries_csv,
    read_rch_timeseries_dir,
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
    "       RCH      GIS   MON     AREAkm2  FLOW_INcms FLOW_OUTcms ...\n"
)


def _row(reach: int, gis: int, mon: int, *, area: float = 1.0) -> str:
    values = [area] + [0.0] * (len(RCH_VARIABLE_COLUMNS) - 1)
    formatted = "  ".join(f"{v:.4E}" for v in values)
    return f"REACH   {reach:5d}{gis:9d}{mon:6d}  {formatted}\n"


def _write_rch(path: Path, rows: list[str]) -> None:
    path.write_text(_PRELUDE + "".join(rows), encoding="utf-8")


def test_parse_rch_file_reads_expected_columns_and_values(tmp_path: Path) -> None:
    rch_path = tmp_path / "output.rch"
    _write_rch(rch_path, [_row(1, 0, 2017, area=20.21), _row(2, 0, 2017, area=16.06)])

    df = parse_rch_file(rch_path)

    assert list(df.columns) == ["reach", "gis", "mon"] + RCH_VARIABLE_COLUMNS
    assert df["reach"].tolist() == [1, 2]
    assert df["mon"].tolist() == [2017, 2017]
    assert df["AREA"].tolist() == pytest.approx([20.21, 16.06])


def test_parse_rch_file_raises_on_wrong_column_count(tmp_path: Path) -> None:
    rch_path = tmp_path / "output.rch"
    rch_path.write_text(_PRELUDE + "REACH     1        0  2017  0.2021E+02\n", encoding="utf-8")

    with pytest.raises(RchParseError):
        parse_rch_file(rch_path)


def test_parse_rch_file_raises_when_no_data_rows(tmp_path: Path) -> None:
    rch_path = tmp_path / "output.rch"
    rch_path.write_text(_PRELUDE, encoding="utf-8")

    with pytest.raises(RchParseError):
        parse_rch_file(rch_path)


def _settings(*, print_frequency: int, start_year: int, end_year: int, years_to_skip: int) -> RunSettings:
    return RunSettings(
        start_year=start_year,
        end_year=end_year,
        n_years=end_year - start_year + 1,
        years_to_skip=years_to_skip,
        print_frequency=print_frequency,
    )


def test_build_rch_timeseries_yearly_drops_average_annual_summary_row(tmp_path: Path) -> None:
    rch_path = tmp_path / "output.rch"
    _write_rch(
        rch_path,
        [_row(1, 0, 2017), _row(1, 0, 2018), _row(1, 0, 2019), _row(1, 0, 3)],  # 3: fila resumen "average annual"
    )
    df = parse_rch_file(rch_path)
    settings = _settings(print_frequency=PRINT_FREQUENCY_YEARLY, start_year=2012, end_year=2019, years_to_skip=5)

    timeseries = build_rch_timeseries(df, settings)

    assert list(timeseries["date"].dt.year) == [2017, 2018, 2019]
    assert "mon" not in timeseries.columns


def test_build_rch_timeseries_monthly_drops_annual_summary_row_and_assigns_dates(tmp_path: Path) -> None:
    rch_path = tmp_path / "output.rch"
    rows = [_row(1, 0, m) for m in range(1, 13)] + [_row(1, 0, 2018)]
    rows += [_row(1, 0, m) for m in range(1, 13)] + [_row(1, 0, 2019)]
    _write_rch(rch_path, rows)
    df = parse_rch_file(rch_path)
    settings = _settings(print_frequency=PRINT_FREQUENCY_MONTHLY, start_year=2016, end_year=2019, years_to_skip=2)

    timeseries = build_rch_timeseries(df, settings)

    assert len(timeseries) == 24
    assert timeseries["date"].iloc[0] == pd.Timestamp("2018-01-01")
    assert timeseries["date"].iloc[11] == pd.Timestamp("2018-12-01")
    assert timeseries["date"].iloc[12] == pd.Timestamp("2019-01-01")
    assert timeseries["date"].iloc[-1] == pd.Timestamp("2019-12-01")


def test_build_rch_timeseries_daily_rolls_over_year_on_leap_year(tmp_path: Path) -> None:
    rch_path = tmp_path / "output.rch"
    rows = [_row(1, 0, d) for d in range(1, 367)]  # 2020 es bisiesto: 366 días
    _write_rch(rch_path, rows)
    df = parse_rch_file(rch_path)
    settings = _settings(print_frequency=PRINT_FREQUENCY_DAILY, start_year=2020, end_year=2020, years_to_skip=0)

    timeseries = build_rch_timeseries(df, settings)

    assert len(timeseries) == 366
    assert timeseries["date"].iloc[0] == pd.Timestamp("2020-01-01")
    assert timeseries["date"].iloc[-1] == pd.Timestamp("2020-12-31")


def test_export_and_read_rch_timeseries_round_trip(tmp_path: Path) -> None:
    data = {"reach": [1, 1, 2], "date": pd.to_datetime(["2017-01-01", "2018-01-01", "2017-01-01"])}
    for column in RCH_VARIABLE_COLUMNS:
        data[column] = [1.0, 2.0, 3.0]
    timeseries = pd.DataFrame(data)
    dest_dir = tmp_path / "rch_timeseries"

    written = export_rch_timeseries_csvs(timeseries, dest_dir)

    assert set(written) == {1, 2}
    reach_1 = read_rch_timeseries_csv(written[1])
    assert len(reach_1) == 2
    assert "reach" not in reach_1.columns

    reloaded = read_rch_timeseries_dir(dest_dir)
    assert sorted(reloaded["reach"].unique().tolist()) == [1, 2]
    assert len(reloaded) == 3


def test_read_rch_timeseries_dir_returns_empty_frame_when_missing(tmp_path: Path) -> None:
    reloaded = read_rch_timeseries_dir(tmp_path / "does_not_exist")

    assert reloaded.empty
    assert list(reloaded.columns) == ["reach", "date"] + RCH_VARIABLE_COLUMNS
