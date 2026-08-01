from pathlib import Path

import pytest

from swat_io.cio_parser import (
    CioParseError,
    parse_file_cio,
    parse_run_settings,
    write_run_settings,
)

_FULL_CIO = (
    "               8    | NBYR : Number of years simulated\n"
    "            2012    | IYR : Beginning year of simulation\n"
    "               1    | IDAF : Beginning julian day of simulation\n"
    "             365    | IDAL : Ending julian day of simulation\n"
    "               2    | IPRINT: print code (month, day, year)\n"
    "               5    | NYSKIP: number of years to skip output printing/summarization\n"
)


def test_parse_file_cio_reads_start_end_and_n_years(tmp_path: Path) -> None:
    cio_path = tmp_path / "file.cio"
    cio_path.write_text(
        "Master Watershed File: file.cio\n"
        "General Input/Output section (file.cio):\n"
        "               8    | NBYR : Number of years simulated\n"
        "            2012    | IYR : Beginning year of simulation\n"
        "               1    | IDAF : Beginning julian day of simulation\n",
        encoding="utf-8",
    )

    period = parse_file_cio(cio_path)

    assert period.start_year == 2012
    assert period.end_year == 2019
    assert period.n_years == 8


def test_parse_file_cio_single_year_period(tmp_path: Path) -> None:
    cio_path = tmp_path / "file.cio"
    cio_path.write_text(
        "               1    | NBYR : Number of years simulated\n"
        "            2000    | IYR : Beginning year of simulation\n",
        encoding="utf-8",
    )

    period = parse_file_cio(cio_path)

    assert period.start_year == 2000
    assert period.end_year == 2000


def test_parse_file_cio_missing_code_raises(tmp_path: Path) -> None:
    cio_path = tmp_path / "file.cio"
    cio_path.write_text("            2012    | IYR : Beginning year of simulation\n", encoding="utf-8")

    with pytest.raises(CioParseError):
        parse_file_cio(cio_path)


def test_parse_file_cio_non_integer_value_raises(tmp_path: Path) -> None:
    cio_path = tmp_path / "file.cio"
    cio_path.write_text(
        "             N/A    | NBYR : Number of years simulated\n"
        "            2012    | IYR : Beginning year of simulation\n",
        encoding="utf-8",
    )

    with pytest.raises(CioParseError):
        parse_file_cio(cio_path)


def test_parse_run_settings_reads_all_four_codes(tmp_path: Path) -> None:
    cio_path = tmp_path / "file.cio"
    cio_path.write_text(_FULL_CIO, encoding="utf-8")

    settings = parse_run_settings(cio_path)

    assert settings.start_year == 2012
    assert settings.end_year == 2019
    assert settings.n_years == 8
    assert settings.years_to_skip == 5
    assert settings.print_frequency == 2


def test_parse_run_settings_missing_nyskip_raises(tmp_path: Path) -> None:
    cio_path = tmp_path / "file.cio"
    cio_path.write_text(
        "               8    | NBYR : Number of years simulated\n"
        "            2012    | IYR : Beginning year of simulation\n"
        "               2    | IPRINT: print code (month, day, year)\n",
        encoding="utf-8",
    )

    with pytest.raises(CioParseError):
        parse_run_settings(cio_path)


def test_parse_run_settings_nyskip_out_of_range_raises(tmp_path: Path) -> None:
    cio_path = tmp_path / "file.cio"
    cio_path.write_text(
        "               8    | NBYR : Number of years simulated\n"
        "            2012    | IYR : Beginning year of simulation\n"
        "               2    | IPRINT: print code (month, day, year)\n"
        "               8    | NYSKIP: number of years to skip output printing/summarization\n",
        encoding="utf-8",
    )

    with pytest.raises(CioParseError):
        parse_run_settings(cio_path)


def test_write_run_settings_round_trips_through_parser(tmp_path: Path) -> None:
    cio_path = tmp_path / "file.cio"
    cio_path.write_text(_FULL_CIO, encoding="utf-8")

    write_run_settings(cio_path, start_year=2010, end_year=2015, years_to_skip=2, print_frequency=0)

    settings = parse_run_settings(cio_path)
    assert settings.start_year == 2010
    assert settings.end_year == 2015
    assert settings.n_years == 6
    assert settings.years_to_skip == 2
    assert settings.print_frequency == 0


def test_write_run_settings_preserves_untouched_codes(tmp_path: Path) -> None:
    cio_path = tmp_path / "file.cio"
    cio_path.write_text(_FULL_CIO, encoding="utf-8")

    write_run_settings(cio_path, start_year=2010, end_year=2015, years_to_skip=2, print_frequency=0)

    content = cio_path.read_text(encoding="utf-8")
    assert "IDAF : Beginning julian day of simulation" in content
    assert "               1    | IDAF" in content
    assert "             365    | IDAL" in content


def test_write_run_settings_rejects_end_year_before_start_year(tmp_path: Path) -> None:
    cio_path = tmp_path / "file.cio"
    cio_path.write_text(_FULL_CIO, encoding="utf-8")

    with pytest.raises(ValueError):
        write_run_settings(cio_path, start_year=2015, end_year=2010, years_to_skip=0, print_frequency=2)


def test_write_run_settings_rejects_years_to_skip_out_of_range(tmp_path: Path) -> None:
    cio_path = tmp_path / "file.cio"
    cio_path.write_text(_FULL_CIO, encoding="utf-8")

    with pytest.raises(ValueError):
        write_run_settings(cio_path, start_year=2010, end_year=2015, years_to_skip=6, print_frequency=2)


def test_write_run_settings_rejects_invalid_print_frequency(tmp_path: Path) -> None:
    cio_path = tmp_path / "file.cio"
    cio_path.write_text(_FULL_CIO, encoding="utf-8")

    with pytest.raises(ValueError):
        write_run_settings(cio_path, start_year=2010, end_year=2015, years_to_skip=0, print_frequency=9)
