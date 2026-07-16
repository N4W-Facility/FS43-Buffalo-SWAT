from pathlib import Path

from config.settings import ConfigManager
from ui.config_dialog import show_config_dialog


def test_show_config_dialog_saves_valid_paths_and_calls_on_saved(hidden_root, tmp_path: Path) -> None:
    resources_dir = Path(__file__).resolve().parents[2] / "resources"
    config = ConfigManager(resources_dir=resources_dir, config_file=tmp_path / "config.json")
    config.load_all()

    exe = tmp_path / "swat2012.exe"
    exe.write_text("fake binary")
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    saved = []
    dialog = show_config_dialog(hidden_root, config, on_saved=lambda: saved.append(True))

    dialog.entries["swat_executable"].insert(0, str(exe))
    dialog.entries["base_models_root"].insert(0, str(models_dir))
    dialog.entries["workspace_root"].insert(0, str(workspace_dir))
    dialog.save_button.invoke()
    hidden_root.update()

    assert saved == [True]
    assert config.paths.swat_executable == exe
    assert config.paths.base_models_root == models_dir
    assert config.paths.workspace_root == workspace_dir


def test_show_config_dialog_shows_error_and_does_not_call_on_saved_when_invalid(hidden_root, tmp_path: Path) -> None:
    resources_dir = Path(__file__).resolve().parents[2] / "resources"
    config = ConfigManager(resources_dir=resources_dir, config_file=tmp_path / "config.json")
    config.load_all()

    saved = []
    dialog = show_config_dialog(hidden_root, config, on_saved=lambda: saved.append(True))

    dialog.entries["swat_executable"].insert(0, str(tmp_path / "missing.exe"))
    dialog.entries["base_models_root"].insert(0, str(tmp_path / "missing_models"))
    dialog.entries["workspace_root"].insert(0, str(tmp_path / "missing_workspace"))
    dialog.save_button.invoke()
    hidden_root.update()

    assert saved == []
    assert dialog.error_label.cget("text") != ""
