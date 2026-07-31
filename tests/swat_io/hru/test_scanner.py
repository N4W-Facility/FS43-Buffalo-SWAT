from pathlib import Path

import pytest

from swat_io.hru.scanner import find_hru_files, parse_hru_directory

_HRU_CONTENT = "        0.7500    | HRU_FR : Fraction of subbasin area contained in HRU\n"


def _write_hru(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_HRU_CONTENT, encoding="utf-8")


def test_find_hru_files_recurses_into_subfolders(tmp_path: Path) -> None:
    _write_hru(tmp_path / "000010001.hru")
    _write_hru(tmp_path / "sub" / "000020002.hru")

    found = find_hru_files(tmp_path, recursive=True)

    assert len(found) == 2


def test_find_hru_files_non_recursive_ignores_subfolders(tmp_path: Path) -> None:
    _write_hru(tmp_path / "000010001.hru")
    _write_hru(tmp_path / "sub" / "000020002.hru")

    found = find_hru_files(tmp_path, recursive=False)

    assert [p.name for p in found] == ["000010001.hru"]


def test_find_hru_files_ignores_temp_lock_files(tmp_path: Path) -> None:
    _write_hru(tmp_path / "000010001.hru")
    _write_hru(tmp_path / "~$000010001.hru")

    found = find_hru_files(tmp_path)

    assert [p.name for p in found] == ["000010001.hru"]


def test_find_hru_files_ignores_backup_extension(tmp_path: Path) -> None:
    _write_hru(tmp_path / "000010001.hru")
    _write_hru(tmp_path / "000010001.hru.bak")

    found = find_hru_files(tmp_path)

    assert [p.name for p in found] == ["000010001.hru"]


def test_find_hru_files_ignores_hidden_folders(tmp_path: Path) -> None:
    _write_hru(tmp_path / "000010001.hru")
    _write_hru(tmp_path / ".hidden" / "000020002.hru")

    found = find_hru_files(tmp_path)

    assert [p.name for p in found] == ["000010001.hru"]


def test_find_hru_files_returns_deterministically_sorted_paths(tmp_path: Path) -> None:
    _write_hru(tmp_path / "000030003.hru")
    _write_hru(tmp_path / "000010001.hru")
    _write_hru(tmp_path / "000020002.hru")

    found = find_hru_files(tmp_path)

    assert found == sorted(found)


def test_find_hru_files_missing_root_returns_empty(tmp_path: Path) -> None:
    assert find_hru_files(tmp_path / "does_not_exist") == []


def test_parse_hru_directory_continues_on_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    good_path = tmp_path / "000010001.hru"
    bad_path = tmp_path / "000020002.hru"
    _write_hru(good_path)
    _write_hru(bad_path)

    import swat_io.hru.scanner as scanner_module
    from swat_io.hru.exceptions import HRUReadError

    real_parse = scanner_module.parse_hru_file

    def _flaky_parse(path):
        if Path(path) == bad_path:
            raise HRUReadError("archivo simuladamente dañado")
        return real_parse(path)

    monkeypatch.setattr(scanner_module, "parse_hru_file", _flaky_parse)

    result = parse_hru_directory(tmp_path, continue_on_error=True)

    assert len(result.files) == 1
    assert result.files[0].source_path == good_path
    assert len(result.errors) == 1
    assert result.errors[0].path == bad_path
    assert result.errors[0].error_type == "HRUReadError"
    assert "dañado" in result.errors[0].message


def test_parse_hru_directory_raises_when_continue_on_error_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad_path = tmp_path / "000020002.hru"
    _write_hru(bad_path)

    import swat_io.hru.scanner as scanner_module
    from swat_io.hru.exceptions import HRUReadError

    def _always_fails(path):
        raise HRUReadError("archivo simuladamente dañado")

    monkeypatch.setattr(scanner_module, "parse_hru_file", _always_fails)

    with pytest.raises(HRUReadError):
        parse_hru_directory(tmp_path, continue_on_error=False)
