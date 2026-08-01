import subprocess
from pathlib import Path

import pytest

from engine.run import run_scenario


def _fake_completed_process(args, *, returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr=stderr)


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
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _fake_completed_process(a[0], returncode=0)
    )

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
        subprocess,
        "run",
        lambda *a, **k: _fake_completed_process(a[0], returncode=0, stdout="done", stderr=""),
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
        "run",
        lambda *a, **k: _fake_completed_process(a[0], returncode=1, stdout="", stderr="fatal error"),
    )

    result = run_scenario(txtinout_dir, swat_executable, "swatUser.exe")

    assert result.success is False
    assert result.exit_code == 1
    assert result.stderr == "fatal error"


def test_run_scenario_runs_with_cwd_set_to_txtinout(
    monkeypatch: pytest.MonkeyPatch, txtinout_dir: Path, swat_executable: Path
) -> None:
    captured_kwargs = {}

    def fake_run(args, **kwargs):
        captured_kwargs.update(kwargs)
        return _fake_completed_process(args, returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    run_scenario(txtinout_dir, swat_executable, "swatUser.exe")

    assert captured_kwargs["cwd"] == txtinout_dir


def test_run_scenario_reports_progress(
    monkeypatch: pytest.MonkeyPatch, txtinout_dir: Path, swat_executable: Path
) -> None:
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _fake_completed_process(a[0], returncode=0)
    )
    messages: list[str] = []

    run_scenario(txtinout_dir, swat_executable, "swatUser.exe", on_progress=messages.append)

    assert messages
