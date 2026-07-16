from pathlib import Path

from scenarios.project import open_or_create_project


def test_open_or_create_project_creates_directory(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    base_model_dir = tmp_path / "base" / "Buffalo_calibrated_annual"
    base_txtinout_dir = base_model_dir / "TxtInOut"

    project = open_or_create_project(workspace_root, "Buffalo", base_model_dir, base_txtinout_dir)

    assert project.project_dir == workspace_root / "Buffalo"
    assert project.project_dir.is_dir()
    assert project.watershed == "Buffalo"
    assert project.base_model_dir == base_model_dir
    assert project.base_txtinout_dir == base_txtinout_dir


def test_open_or_create_project_is_idempotent(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    base_model_dir = tmp_path / "base" / "Buffalo_calibrated_annual"
    base_txtinout_dir = base_model_dir / "TxtInOut"

    open_or_create_project(workspace_root, "Buffalo", base_model_dir, base_txtinout_dir)
    project = open_or_create_project(workspace_root, "Buffalo", base_model_dir, base_txtinout_dir)

    assert project.project_dir.is_dir()
