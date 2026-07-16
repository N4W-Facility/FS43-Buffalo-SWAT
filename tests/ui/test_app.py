from pathlib import Path

from config.settings import AppPaths
from ui.app import App


def test_app_shows_config_dialog_when_paths_incomplete(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("config.settings.DEFAULT_CONFIG_FILE", tmp_path / "config.json")
    opened = []
    monkeypatch.setattr(
        "ui.app.show_config_dialog",
        lambda parent, config, on_saved: opened.append(True),
    )

    app = App()
    try:
        assert opened == [True]
    finally:
        app.destroy()


def test_app_shows_initial_window_when_paths_already_complete(tmp_path: Path, monkeypatch) -> None:
    exe = tmp_path / "swat2012.exe"
    exe.write_text("fake binary")
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    monkeypatch.setattr("config.settings.DEFAULT_CONFIG_FILE", tmp_path / "config.json")

    from config.settings import ConfigManager

    seed = ConfigManager(config_file=tmp_path / "config.json")
    seed.save_paths(
        AppPaths(swat_executable=exe, base_models_root=models_dir, workspace_root=workspace_dir)
    )

    app = App()
    try:
        assert app._current_frame is not None
        assert app._current_frame.__class__.__name__ == "InitialWindowFrame"
    finally:
        app.destroy()
