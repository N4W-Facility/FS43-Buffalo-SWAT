from pathlib import Path

from swat_io.text_format import parse_value_code_file, write_value_code_file


def test_write_value_code_file_updates_only_matching_codes(tmp_path: Path) -> None:
    path = tmp_path / "sample.pnd"
    path.write_text(
        "Wetland inputs:\n"
        "           0.000    | WET_FR : Fraction of subbasin area that drains into wetlands\n"
        "          42.400    | WET_NSA: Surface area of wetlands at normal water level [ha]\n",
        encoding="utf-8",
    )

    write_value_code_file(path, {"WET_FR": 0.4})

    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert lines[1] == "           0.400    | WET_FR : Fraction of subbasin area that drains into wetlands"
    assert lines[2] == "          42.400    | WET_NSA: Surface area of wetlands at normal water level [ha]"


def test_write_value_code_file_round_trips_through_parser(tmp_path: Path) -> None:
    path = tmp_path / "sample.pnd"
    path.write_text(
        "           0.000    | WET_FR : desc\n"
        "         106.000    | WET_MXSA: desc\n",
        encoding="utf-8",
    )

    write_value_code_file(path, {"WET_FR": 0.75, "WET_MXSA": 12.5})

    parsed = parse_value_code_file(path)
    assert float(parsed["WET_FR"]) == 0.75
    assert float(parsed["WET_MXSA"]) == 12.5


def test_write_value_code_file_ignores_unrelated_codes(tmp_path: Path) -> None:
    path = tmp_path / "sample.pnd"
    original = "           0.000    | WET_K : desc\n"
    path.write_text(original, encoding="utf-8")

    write_value_code_file(path, {"WET_FR": 1.0})

    assert path.read_text(encoding="utf-8") == original


def test_write_value_code_file_decimals_zero_writes_plain_integers(tmp_path: Path) -> None:
    path = tmp_path / "file.cio"
    path.write_text(
        "               8    | NBYR : Number of years simulated\n"
        "            2012    | IYR : Beginning year of simulation\n",
        encoding="utf-8",
    )

    write_value_code_file(path, {"NBYR": 5.0, "IYR": 2015.0}, decimals=0)

    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert lines[0] == "               5    | NBYR : Number of years simulated"
    assert lines[1] == "            2015    | IYR : Beginning year of simulation"
