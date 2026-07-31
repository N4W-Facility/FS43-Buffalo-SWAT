from pathlib import Path

import pytest

from swat_io.cio_parser import CioParseError, parse_file_cio


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
