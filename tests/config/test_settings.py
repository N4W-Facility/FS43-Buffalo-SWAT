from pathlib import Path

from config.settings import AppPaths, ConfigManager, validate_app_paths


def test_app_paths_round_trip_including_target_executable_name(tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"
    manager = ConfigManager(config_file=config_file)
    exe = tmp_path / "swat2012.exe"
    exe.write_text("fake binary")
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    paths = AppPaths(
        swat_executable=exe,
        base_models_root=models_dir,
        workspace_root=workspace_dir,
        target_executable_name="custom.exe",
    )
    manager.save_paths(paths)

    reloaded = ConfigManager(config_file=config_file)
    loaded_paths = reloaded._load_paths()

    assert loaded_paths.swat_executable == exe
    assert loaded_paths.base_models_root == models_dir
    assert loaded_paths.workspace_root == workspace_dir
    assert loaded_paths.target_executable_name == "custom.exe"


def test_app_paths_default_target_executable_name() -> None:
    assert AppPaths().target_executable_name == "swatUser.exe"


def test_theme_path_points_at_theme_json(tmp_path: Path) -> None:
    manager = ConfigManager(resources_dir=tmp_path, config_file=tmp_path / "config.json")
    assert manager.theme_path() == tmp_path / "theme" / "swat_light.json"


def test_validate_app_paths_valid(tmp_path: Path) -> None:
    exe = tmp_path / "swat2012.exe"
    exe.write_text("fake binary")
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    assert validate_app_paths(exe, models_dir, workspace_dir) is None


def test_validate_app_paths_invalid_executable(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    error = validate_app_paths(tmp_path / "missing.exe", models_dir, workspace_dir)

    assert error == "config.error.invalid_executable"


def test_validate_app_paths_invalid_directory(tmp_path: Path) -> None:
    exe = tmp_path / "swat2012.exe"
    exe.write_text("fake binary")

    error = validate_app_paths(exe, tmp_path / "missing_models", tmp_path / "missing_workspace")

    assert error == "config.error.invalid_directory"
