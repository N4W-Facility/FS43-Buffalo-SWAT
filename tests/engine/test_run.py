import subprocess
from pathlib import Path

import pytest

from engine.run import run_scenario


class _FakeStream:
    """Iterable línea a línea con .close(), como el file-like object real que
    devuelve Popen (a diferencia de un iterator/list plano, que no tiene
    close() y dispararía un AttributeError en pump())."""

    def __init__(self, lines) -> None:
        self._iterator = iter(lines)

    def __iter__(self):
        return self._iterator

    def close(self) -> None:
        pass


class _FakePopen:
    """Simula el subprocess.Popen real: stdout/stderr son iterables línea a
    línea (como el file-like object real, que bloquea hasta la próxima línea
    o EOF), y wait() recién fija returncode -- igual que un proceso real que
    termina después de que sus streams se agotan."""

    def __init__(self, args, *, returncode: int, stdout_lines=(), stderr_lines=()):
        self.args = args
        self._returncode = returncode
        self.stdout = _FakeStream(stdout_lines)
        self.stderr = _FakeStream(stderr_lines)
        self.returncode: int | None = None

    def wait(self) -> int:
        self.returncode = self._returncode
        return self.returncode


@pytest.fixture
def txtinout_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "TxtInOut"
    directory.mkdir()
    return directory


@pytest.fixture
def swat_executable(tmp_path: Path) -> Path:
    exe = tmp_path / "rev670_64rel.exe"
    exe.write_text("fake binary")
    return exe


def test_run_scenario_copies_executable_into_txtinout_with_target_name(
    monkeypatch: pytest.MonkeyPatch, txtinout_dir: Path, swat_executable: Path
) -> None:
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen(a[0], returncode=0))

    run_scenario(txtinout_dir, swat_executable, "swatUser.exe")

    target = txtinout_dir / "swatUser.exe"
    assert target.exists()
    assert target.read_text() == swat_executable.read_text()
    # el ejecutable configurado por el usuario nunca se modifica en su lugar
    assert swat_executable.exists()


def test_run_scenario_success_on_exit_code_zero(
    monkeypatch: pytest.MonkeyPatch, txtinout_dir: Path, swat_executable: Path
) -> None:
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: _FakePopen(a[0], returncode=0, stdout_lines=["done"])
    )

    result = run_scenario(txtinout_dir, swat_executable, "swatUser.exe")

    assert result.success is True
    assert result.exit_code == 0
    assert result.stdout == "done"
    assert result.elapsed_seconds >= 0


def test_run_scenario_failure_on_nonzero_exit_code(
    monkeypatch: pytest.MonkeyPatch, txtinout_dir: Path, swat_executable: Path
) -> None:
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *a, **k: _FakePopen(a[0], returncode=1, stderr_lines=["fatal error"]),
    )

    result = run_scenario(txtinout_dir, swat_executable, "swatUser.exe")

    assert result.success is False
    assert result.exit_code == 1
    assert result.stderr == "fatal error"


def test_run_scenario_runs_with_cwd_set_to_txtinout(
    monkeypatch: pytest.MonkeyPatch, txtinout_dir: Path, swat_executable: Path
) -> None:
    captured_kwargs = {}

    def fake_popen(args, **kwargs):
        captured_kwargs.update(kwargs)
        return _FakePopen(args, returncode=0)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    run_scenario(txtinout_dir, swat_executable, "swatUser.exe")

    assert captured_kwargs["cwd"] == txtinout_dir


def test_run_scenario_reports_progress(
    monkeypatch: pytest.MonkeyPatch, txtinout_dir: Path, swat_executable: Path
) -> None:
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen(a[0], returncode=0))
    messages: list[str] = []

    run_scenario(txtinout_dir, swat_executable, "swatUser.exe", on_progress=messages.append)

    assert messages


def test_run_scenario_reports_progress_per_line_as_they_arrive(
    monkeypatch: pytest.MonkeyPatch, txtinout_dir: Path, swat_executable: Path
) -> None:
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *a, **k: _FakePopen(a[0], returncode=0, stdout_lines=["line1", "line2"]),
    )
    messages: list[str] = []

    result = run_scenario(txtinout_dir, swat_executable, "swatUser.exe", on_progress=messages.append)

    # primer mensaje antes de arrancar el proceso, luego uno por línea nueva
    assert messages[0] == "Running swatUser.exe..."
    assert messages[-1] == "line1\nline2"
    assert result.stdout == "line1\nline2"
