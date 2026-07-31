from swat_io.hru.parser import parse_hru_file, parse_hru_text
from swat_io.hru.validation import validate_hru_file

from tests.swat_io.hru.conftest import fixture_path


def _codes(issues) -> set[str]:
    return {issue.code for issue in issues}


def test_validate_flags_empty_file() -> None:
    hru = parse_hru_file(fixture_path("000070007_empty.hru"))

    issues = validate_hru_file(hru)

    assert len(issues) == 1
    assert issues[0].severity == "ERROR"
    assert issues[0].code == "EMPTY_FILE"


def test_validate_flags_file_with_no_parameters() -> None:
    hru = parse_hru_text("* solo un comentario, sin parámetros\n\n")

    issues = validate_hru_file(hru)

    assert "NO_PARAMETERS" in _codes(issues)


def test_validate_flags_duplicate_parameters() -> None:
    hru = parse_hru_file(fixture_path("000030003_duplicate.hru"))

    issues = validate_hru_file(hru)

    duplicate_issues = [i for i in issues if i.code == "DUPLICATE_PARAMETER"]
    assert len(duplicate_issues) == 1
    assert duplicate_issues[0].severity == "WARNING"
    assert duplicate_issues[0].parameter == "HRU_FR"


def test_validate_flags_missing_hru_fr() -> None:
    hru = parse_hru_file(fixture_path("000040004_missing_hrufr.hru"))

    issues = validate_hru_file(hru)

    assert any(i.code == "MISSING_HRU_FR" and i.severity == "ERROR" for i in issues)


def test_validate_flags_non_numeric_hru_fr() -> None:
    hru = parse_hru_text("   TEXTO    | HRU_FR : valor no numérico\n")

    issues = validate_hru_file(hru)

    assert any(i.code == "HRU_FR_NOT_NUMERIC" for i in issues)


def test_validate_flags_negative_hru_fr() -> None:
    hru = parse_hru_text("  -0.5000    | HRU_FR : negativo\n")

    issues = validate_hru_file(hru)

    assert any(i.code == "HRU_FR_NEGATIVE" for i in issues)


def test_validate_flags_hru_fr_above_one() -> None:
    hru = parse_hru_file(fixture_path("000050005_out_of_range.hru"))

    issues = validate_hru_file(hru)

    assert any(i.code == "HRU_FR_OUT_OF_RANGE" for i in issues)


def test_validate_flags_missing_metadata() -> None:
    hru = parse_hru_text("        0.5000    | HRU_FR : sin encabezado de metadatos\n")

    issues = validate_hru_file(hru)

    missing = [i for i in issues if i.code == "MISSING_METADATA"]
    assert len(missing) == 1
    assert missing[0].severity == "INFO"


def test_validate_flags_metadata_filename_mismatch() -> None:
    hru = parse_hru_file(fixture_path("000060006.hru"))

    issues = validate_hru_file(hru)

    mismatch = [i for i in issues if i.code == "METADATA_FILENAME_MISMATCH"]
    assert len(mismatch) == 1
    assert mismatch[0].severity == "WARNING"
    # El contenido debe ganar sobre el nombre de archivo.
    assert hru.metadata.subbasin == 1
    assert hru.metadata.hru == 1


def test_validate_flags_unparsed_parametric_line() -> None:
    hru = parse_hru_file(fixture_path("000020002_unknown_lines.hru"))

    issues = validate_hru_file(hru)

    assert any(i.code == "UNPARSED_PARAMETRIC_LINE" for i in issues)


def test_validate_flags_non_utf8_encoding() -> None:
    hru = parse_hru_file(fixture_path("000090009_cp1252.hru"))

    issues = validate_hru_file(hru)

    assert any(i.code == "NON_UTF8_ENCODING" and i.severity == "INFO" for i in issues)


def test_validate_valid_file_has_no_errors() -> None:
    hru = parse_hru_file(fixture_path("000010001.hru"))

    issues = validate_hru_file(hru)

    assert not any(i.severity == "ERROR" for i in issues)


def test_hru_file_validate_method_matches_module_function() -> None:
    hru = parse_hru_file(fixture_path("000040004_missing_hrufr.hru"))

    assert [i.code for i in hru.validate()] == [i.code for i in validate_hru_file(hru)]
