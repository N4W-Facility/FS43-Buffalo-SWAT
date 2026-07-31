import pytest

from swat_io.hru.models import HRUParameterLine, HRURawLine
from swat_io.hru.parser import parse_hru_file, parse_hru_text

from tests.swat_io.hru.conftest import fixture_path


def test_parse_hru_file_reads_valid_file() -> None:
    hru = parse_hru_file(fixture_path("000010001.hru"))
    assert hru.lines
    assert hru.source_path == fixture_path("000010001.hru")


def test_parse_recognizes_known_parameter() -> None:
    hru = parse_hru_file(fixture_path("000010001.hru"))
    assert hru.has_parameter("HRU_FR")
    assert hru.get_value("HRU_FR") == pytest.approx(0.75)


def test_parse_recognizes_integer_value() -> None:
    hru = parse_hru_text("      5    | NROT : Some integer parameter\n")
    assert hru.get_value("NROT") == 5
    assert isinstance(hru.get_value("NROT"), int)


def test_parse_recognizes_decimal_value() -> None:
    hru = parse_hru_file(fixture_path("000010001.hru"))
    value = hru.get_value("HRU_FR")
    assert isinstance(value, float)
    assert value == pytest.approx(0.75)


def test_parse_recognizes_scientific_notation() -> None:
    hru = parse_hru_file(fixture_path("000010001.hru"))
    value = hru.get_value("POT_FR")
    assert isinstance(value, float)
    assert value == pytest.approx(1.25e-05)


def test_parse_preserves_unknown_textual_value() -> None:
    hru = parse_hru_text("SWAT2012    | MODEL_TAG : Non-numeric value kept as text\n")
    value = hru.get_value("MODEL_TAG")
    assert value == "SWAT2012"
    assert isinstance(value, str)


def test_parse_preserves_unrecognized_lines_as_raw() -> None:
    hru = parse_hru_file(fixture_path("000020002_unknown_lines.hru"))
    raw_texts = [line.original_text for line in hru.lines if isinstance(line, HRURawLine)]
    assert "this line has no pipe separator at all" in raw_texts
    assert any(text.startswith("*") for text in raw_texts)


def test_parse_preserves_blank_lines() -> None:
    hru = parse_hru_file(fixture_path("000020002_unknown_lines.hru"))
    assert any(isinstance(line, HRURawLine) and line.original_text == "" for line in hru.lines)


def test_parse_preserves_comment_lines() -> None:
    hru = parse_hru_file(fixture_path("000020002_unknown_lines.hru"))
    comment_lines = [
        line
        for line in hru.lines
        if isinstance(line, HRURawLine) and line.original_text.startswith("*")
    ]
    assert len(comment_lines) == 1
    assert "no sigue la gramática" in comment_lines[0].original_text


def test_parse_extracts_metadata_from_header() -> None:
    hru = parse_hru_file(fixture_path("000010001.hru"))
    assert hru.metadata.subbasin == 1
    assert hru.metadata.hru == 1
    assert hru.metadata.land_use == "AGRL"
    assert hru.metadata.soil == "1013090"
    assert hru.metadata.slope_class == "0-9999"


def test_parse_handles_duplicate_parameters() -> None:
    hru = parse_hru_file(fixture_path("000030003_duplicate.hru"))
    occurrences = hru.get_parameters("HRU_FR")
    assert len(occurrences) == 2
    # get_parameter debe devolver la primera ocurrencia.
    assert hru.get_parameter("HRU_FR").parsed_value == pytest.approx(0.5)
    assert occurrences[1].parsed_value == pytest.approx(0.6)


def test_parse_handles_missing_parameter() -> None:
    hru = parse_hru_file(fixture_path("000040004_missing_hrufr.hru"))
    assert not hru.has_parameter("HRU_FR")
    assert hru.get_value("HRU_FR") is None
    assert hru.get_value("HRU_FR", default=-1) == -1


@pytest.mark.parametrize(
    "line_text",
    [
        "0.7500|HRU_FR:Fraction of subbasin area\n",
        "      0.7500 | HRU_FR\n",
        "      0.7500    | hru_fr : Description\n",
        "       0.7500    | HRU_FR : Fraction of subbasin area contained in HRU\n",
    ],
)
def test_parse_handles_variable_whitespace(line_text: str) -> None:
    hru = parse_hru_text(line_text)
    param = hru.get_parameter("HRU_FR")
    assert param is not None
    assert param.parsed_value == pytest.approx(0.75)


def test_parser_does_not_fail_on_malformed_line() -> None:
    # No debe lanzar excepción: la línea se conserva como HRURawLine.
    hru = parse_hru_text("   || broken separator line\n")
    assert isinstance(hru.lines[0], HRURawLine)


def test_parse_lowercase_parameter_name_lookup_is_case_insensitive() -> None:
    hru = parse_hru_text("      0.7500    | hru_fr : Description\n")
    assert hru.has_parameter("HRU_FR")
    assert hru.has_parameter("hru_fr")
    param = hru.get_parameter("HRU_FR")
    assert isinstance(param, HRUParameterLine)
    assert param.parameter_name == "hru_fr"  # se conserva el nombre original
