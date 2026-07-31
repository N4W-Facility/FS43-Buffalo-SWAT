from pathlib import Path

import pytest

from swat_io.common.line_parser import split_lines_keep_newlines
from swat_io.hru.parser import parse_hru_file
from swat_io.hru.writer import write_hru_file

from tests.swat_io.hru.conftest import FIXTURES_DIR

_ALL_FIXTURES = sorted(p.name for p in FIXTURES_DIR.glob("*.hru"))


@pytest.mark.parametrize("fixture_name", _ALL_FIXTURES)
def test_roundtrip_unmodified_file_is_byte_identical(fixture_name: str, tmp_path: Path) -> None:
    source = FIXTURES_DIR / fixture_name
    original_bytes = source.read_bytes()

    hru = parse_hru_file(source)
    destination = tmp_path / fixture_name
    write_hru_file(hru, destination)

    assert destination.read_bytes() == original_bytes


def test_roundtrip_preserves_crlf(tmp_path: Path) -> None:
    source = FIXTURES_DIR / "000080008_crlf.hru"
    hru = parse_hru_file(source)
    destination = tmp_path / "out.hru"
    write_hru_file(hru, destination)

    assert b"\r\n" in destination.read_bytes()
    assert destination.read_bytes() == source.read_bytes()


def test_roundtrip_preserves_lf(tmp_path: Path) -> None:
    source = FIXTURES_DIR / "000010001.hru"
    hru = parse_hru_file(source)
    destination = tmp_path / "out.hru"
    write_hru_file(hru, destination)

    assert b"\r\n" not in destination.read_bytes()
    assert destination.read_bytes() == source.read_bytes()


def test_roundtrip_preserves_cp1252_encoding(tmp_path: Path) -> None:
    source = FIXTURES_DIR / "000090009_cp1252.hru"
    hru = parse_hru_file(source)
    assert hru.encoding == "cp1252"

    destination = tmp_path / "out.hru"
    write_hru_file(hru, destination)

    assert destination.read_bytes() == source.read_bytes()


def test_roundtrip_preserves_utf8_bom(tmp_path: Path) -> None:
    source = FIXTURES_DIR / "000100010_utf8bom.hru"
    hru = parse_hru_file(source)
    assert hru.encoding == "utf-8-sig"

    destination = tmp_path / "out.hru"
    write_hru_file(hru, destination)

    assert destination.read_bytes() == source.read_bytes()


def test_roundtrip_preserves_line_count(tmp_path: Path) -> None:
    source = FIXTURES_DIR / "000020002_unknown_lines.hru"
    original_line_count = len(split_lines_keep_newlines(source.read_text(encoding="utf-8")))

    hru = parse_hru_file(source)
    assert len(hru.lines) == original_line_count

    destination = tmp_path / "out.hru"
    write_hru_file(hru, destination)
    rewritten_line_count = len(split_lines_keep_newlines(destination.read_text(encoding="utf-8")))
    assert rewritten_line_count == original_line_count


def test_roundtrip_preserves_irregular_whitespace(tmp_path: Path) -> None:
    text = "    12.500   |   HRU_FR :   irregular spacing kept as-is\n"
    from swat_io.hru.parser import parse_hru_text

    hru = parse_hru_text(text)
    destination = tmp_path / "out.hru"
    write_hru_file(hru, destination)
    assert destination.read_text(encoding="utf-8") == text


def test_roundtrip_preserves_comments_verbatim(tmp_path: Path) -> None:
    source = FIXTURES_DIR / "000020002_unknown_lines.hru"
    hru = parse_hru_file(source)
    destination = tmp_path / "out.hru"
    write_hru_file(hru, destination)
    assert destination.read_bytes() == source.read_bytes()


def test_roundtrip_preserves_unknown_lines_verbatim(tmp_path: Path) -> None:
    source = FIXTURES_DIR / "000020002_unknown_lines.hru"
    hru = parse_hru_file(source)
    destination = tmp_path / "out.hru"
    write_hru_file(hru, destination)
    assert destination.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
