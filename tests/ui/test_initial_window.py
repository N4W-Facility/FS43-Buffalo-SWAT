from pathlib import Path

from config.settings import ConfigManager
from tests.helpers import make_synthetic_txtinout
from ui.initial_window import InitialWindowFrame


def _make_config(tmp_path: Path) -> ConfigManager:
    resources_dir = Path(__file__).resolve().parents[2] / "resources"
    config = ConfigManager(resources_dir=resources_dir, config_file=tmp_path / "config.json")
    config.load_all()
    config.paths.base_models_root = tmp_path / "models"
    config.paths.workspace_root = tmp_path / "workspace"
    make_synthetic_txtinout(tmp_path / "models" / "Buffalo" / "Buffalo_calibrated_annual", {1: {}})
    (tmp_path / "workspace").mkdir()
    return config


def test_initial_window_shows_no_selection_placeholder(hidden_root, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    frame = InitialWindowFrame(hidden_root, config, on_project_selected=lambda project: None)

    assert frame.path_entry.get() == config.text("project.no_selection")


def test_initial_window_create_flow_invokes_callback(hidden_root, tmp_path: Path, monkeypatch) -> None:
    config = _make_config(tmp_path)
    selected = []

    monkeypatch.setattr(
        "ui.initial_window.ask_choice",
        lambda parent, title, options, confirm_text, cancel_text: options[0],
    )

    frame = InitialWindowFrame(hidden_root, config, on_project_selected=lambda project: selected.append(project))
    frame._create_project()

    assert len(selected) == 1
    assert selected[0].watershed == "Buffalo"
    assert frame.path_entry.get() == str(selected[0].project_dir)
