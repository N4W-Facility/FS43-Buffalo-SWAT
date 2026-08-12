from pathlib import Path

import pandas as pd
import pytest

from swat_io.cio_parser import PRINT_FREQUENCY_DAILY, PRINT_FREQUENCY_MONTHLY, PRINT_FREQUENCY_YEARLY, RunSettings
from swat_io.sub_output_parser import (
    SUB_VARIABLE_COLUMNS,
    SubParseError,
    build_sub_timeseries,
    export_sub_timeseries_csvs,
    parse_sub_file,
    read_sub_timeseries_csv,
    read_sub_timeseries_dir,
)

_PRELUDE = (
    "1  1\n"
    "    SWAT Sep 7    VER 2018/Rev 670\n"
    "\n"
    "    General Input/Output section (file.cio):\n"
    "    8/26/2021 12:00:00 AM ARCGIS-SWAT interface AV\n"
    "\n"
    "\n"
    "\n"
    "       SUB      GIS  MON   AREAkm2  PRECIPmm SNOMELTmm ...\n"
)

# CHOLA (índice 19 de SUB_VARIABLE_COLUMNS) es 11 caracteres en el archivo
# real, el resto de las variables son 10 -- ver swat_io/sub_output_parser.py.
_VARIABLE_WIDTHS = [10] * 19 + [11] + [10] * 5
assert len(_VARIABLE_WIDTHS) == len(SUB_VARIABLE_COLUMNS)


def _row(sub: int, mon: int, *, area: float = 1.0, gis: int = 0) -> str:
    # MON se pega sin separador al campo AREA que le sigue -- reproduce
    # ese formato real (ver docstring de sub_output_parser) en vez de
    # dejar espacio entre ambos.
    values = [area] + [0.0] * (len(SUB_VARIABLE_COLUMNS) - 1)
    mon_field = str(mon).rjust(5)
    var_fields = "".join(f"{v:.4E}".rjust(w) for v, w in zip(values, _VARIABLE_WIDTHS))
    return f"BIGSUB{sub:5d}{gis:9d}{mon_field}{var_fields}\n"


def _write_sub(path: Path, rows: list[str]) -> None:
    path.write_text(_PRELUDE + "".join(rows), encoding="utf-8")


def test_parse_sub_file_reads_expected_columns_and_values(tmp_path: Path) -> None:
    sub_path = tmp_path / "output.sub"
    _write_sub(sub_path, [_row(1, 2017, area=20.21), _row(2, 2017, area=16.06)])

    df = parse_sub_file(sub_path)

    assert list(df.columns) == ["sub", "gis", "mon"] + SUB_VARIABLE_COLUMNS
    assert df["sub"].tolist() == [1, 2]
    assert df["mon"].tolist() == [2017, 2017]
    assert df["AREA"].tolist() == pytest.approx([20.21, 16.06])


def test_parse_sub_file_handles_mon_glued_to_area_at_any_digit_count(tmp_path: Path) -> None:
    # MON sin ceros a la izquierda y pegado directo al campo AREA -- ver
    # docstring del módulo. Un día de 3 dígitos (227) no debe corromper
    # el valor de AREA que sigue.
    sub_path = tmp_path / "output.sub"
    _write_sub(sub_path, [_row(1, 1, area=0.6270), _row(1, 227, area=0.6270), _row(1, 365, area=0.6270)])

    df = parse_sub_file(sub_path)

    assert df["mon"].tolist() == [1, 227, 365]
    assert df["AREA"].tolist() == pytest.approx([0.6270, 0.6270, 0.6270])


def test_parse_sub_file_raises_when_no_data_rows(tmp_path: Path) -> None:
    sub_path = tmp_path / "output.sub"
    sub_path.write_text(_PRELUDE, encoding="utf-8")

    with pytest.raises(SubParseError):
        parse_sub_file(sub_path)


def _settings(*, print_frequency: int, start_year: int, end_year: int, years_to_skip: int) -> RunSettings:
    return RunSettings(
        start_year=start_year,
        end_year=end_year,
        n_years=end_year - start_year + 1,
        years_to_skip=years_to_skip,
        print_frequency=print_frequency,
    )


def test_build_sub_timeseries_yearly_drops_average_annual_summary_row(tmp_path: Path) -> None:
    sub_path = tmp_path / "output.sub"
    _write_sub(sub_path, [_row(1, 2017), _row(1, 2018), _row(1, 2019), _row(1, 3)])  # 3: fila resumen
    df = parse_sub_file(sub_path)
    settings = _settings(print_frequency=PRINT_FREQUENCY_YEARLY, start_year=2012, end_year=2019, years_to_skip=5)

    timeseries = build_sub_timeseries(df, settings)

    assert list(timeseries["date"].dt.year) == [2017, 2018, 2019]
    assert "mon" not in timeseries.columns


def test_build_sub_timeseries_monthly_drops_annual_summary_row_and_assigns_dates(tmp_path: Path) -> None:
    sub_path = tmp_path / "output.sub"
    rows = [_row(1, m) for m in range(1, 13)] + [_row(1, 2018)]
    rows += [_row(1, m) for m in range(1, 13)] + [_row(1, 2019)]
    _write_sub(sub_path, rows)
    df = parse_sub_file(sub_path)
    settings = _settings(print_frequency=PRINT_FREQUENCY_MONTHLY, start_year=2016, end_year=2019, years_to_skip=2)

    timeseries = build_sub_timeseries(df, settings)

    assert len(timeseries) == 24
    assert timeseries["date"].iloc[0] == pd.Timestamp("2018-01-01")
    assert timeseries["date"].iloc[11] == pd.Timestamp("2018-12-01")
    assert timeseries["date"].iloc[12] == pd.Timestamp("2019-01-01")
    assert timeseries["date"].iloc[-1] == pd.Timestamp("2019-12-01")


def test_build_sub_timeseries_daily_rolls_over_year_on_leap_year(tmp_path: Path) -> None:
    sub_path = tmp_path / "output.sub"
    rows = [_row(1, d) for d in range(1, 367)]  # 2020 es bisiesto: 366 días
    _write_sub(sub_path, rows)
    df = parse_sub_file(sub_path)
    settings = _settings(print_frequency=PRINT_FREQUENCY_DAILY, start_year=2020, end_year=2020, years_to_skip=0)

    timeseries = build_sub_timeseries(df, settings)

    assert len(timeseries) == 366
    assert timeseries["date"].iloc[0] == pd.Timestamp("2020-01-01")
    assert timeseries["date"].iloc[-1] == pd.Timestamp("2020-12-31")


def test_export_and_read_sub_timeseries_round_trip(tmp_path: Path) -> None:
    data = {"sub": [1, 1, 2], "date": pd.to_datetime(["2017-01-01", "2018-01-01", "2017-01-01"])}
    for column in SUB_VARIABLE_COLUMNS:
        data[column] = [1.0, 2.0, 3.0]
    timeseries = pd.DataFrame(data)
    dest_dir = tmp_path / "sub_timeseries"

    written = export_sub_timeseries_csvs(timeseries, dest_dir)

    assert set(written) == {1, 2}
    sub_1 = read_sub_timeseries_csv(written[1])
    assert len(sub_1) == 2
    assert "sub" not in sub_1.columns

    reloaded = read_sub_timeseries_dir(dest_dir)
    assert sorted(reloaded["sub"].unique().tolist()) == [1, 2]
    assert len(reloaded) == 3


def test_read_sub_timeseries_dir_returns_empty_frame_when_missing(tmp_path: Path) -> None:
    reloaded = read_sub_timeseries_dir(tmp_path / "does_not_exist")

    assert reloaded.empty
    assert list(reloaded.columns) == ["sub", "date"] + SUB_VARIABLE_COLUMNS
