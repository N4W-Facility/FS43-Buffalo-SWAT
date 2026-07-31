from pathlib import Path

import pytest

from swat_io.hru.exceptions import HRUWriteError
from swat_io.hru.parser import parse_hru_text
from swat_io.hru.writer import write_hru_file


def _make_hru():
    return parse_hru_text(
        "        0.7500    | HRU_FR : Fraction of subbasin area contained in HRU\n"
    )


def test_write_requires_explicit_destination_argument() -> None:
    import inspect

    signature = inspect.signature(write_hru_file)
    assert "destination" in signature.parameters
    assert signature.parameters["destination"].default is inspect.Parameter.empty


def test_write_rejects_writing_over_source_path(tmp_path: Path) -> None:
    source = tmp_path / "source.hru"
    source.write_text("        0.7500    | HRU_FR : desc\n", encoding="utf-8")
    from swat_io.hru.parser import parse_hru_file

    hru = parse_hru_file(source)

    with pytest.raises(HRUWriteError):
        write_hru_file(hru, source, allow_overwrite=True)


def test_write_rejects_overwrite_without_flag(tmp_path: Path) -> None:
    destination = tmp_path / "out.hru"
    destination.write_text("old content", encoding="utf-8")
    hru = _make_hru()

    with pytest.raises(HRUWriteError):
        write_hru_file(hru, destination, allow_overwrite=False)

    assert destination.read_text(encoding="utf-8") == "old content"


def test_write_allows_overwrite_when_flag_set(tmp_path: Path) -> None:
    destination = tmp_path / "out.hru"
    destination.write_text("old content", encoding="utf-8")
    hru = _make_hru()

    write_hru_file(hru, destination, allow_overwrite=True)

    assert destination.read_text(encoding="utf-8") == hru.render()


def test_write_creates_backup_when_requested(tmp_path: Path) -> None:
    destination = tmp_path / "out.hru"
    destination.write_text("old content", encoding="utf-8")
    hru = _make_hru()

    write_hru_file(hru, destination, allow_overwrite=True, create_backup=True)

    backup = destination.with_name(destination.name + ".bak")
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == "old content"


def test_write_creates_destination_directory(tmp_path: Path) -> None:
    destination = tmp_path / "nested" / "dir" / "out.hru"
    hru = _make_hru()

    write_hru_file(hru, destination)

    assert destination.exists()


def test_write_cleans_up_temp_file_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination = tmp_path / "out.hru"
    hru = _make_hru()

    def _boom(*args, **kwargs):
        raise OSError("simulated failure")

    monkeypatch.setattr("swat_io.common.atomic_write.os.replace", _boom)

    with pytest.raises(HRUWriteError):
        write_hru_file(hru, destination)

    assert not destination.exists()
    leftover_tmp_files = list(tmp_path.glob(".*.tmp"))
    assert leftover_tmp_files == []


def test_write_non_atomic_mode_writes_file(tmp_path: Path) -> None:
    destination = tmp_path / "out.hru"
    hru = _make_hru()

    write_hru_file(hru, destination, atomic=False)

    assert destination.read_text(encoding="utf-8") == hru.render()
