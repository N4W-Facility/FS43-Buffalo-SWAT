from pathlib import Path

from config.settings import ConfigManager
from scenarios.draft import read_draft
from scenarios.models import Project
from tests.helpers import make_synthetic_txtinout
from ui.parametrizacion_view import ParametrizacionView


def _make_project_and_config(tmp_path: Path) -> tuple[Project, ConfigManager]:
    resources_dir = Path(__file__).resolve().parents[2] / "resources"
    config = ConfigManager(resources_dir=resources_dir, config_file=tmp_path / "config.json")
    config.load_all()

    base_dir = tmp_path / "base" / "Buffalo_calibrated_annual"
    txtinout_dir = make_synthetic_txtinout(base_dir, {1: {"WET_FR": 0.2}, 2: {"WET_FR": 0.0}})
    project_dir = tmp_path / "workspace" / "Buffalo"
    project_dir.mkdir(parents=True)
    project = Project(
        watershed="Buffalo", base_model_dir=base_dir, base_txtinout_dir=txtinout_dir, project_dir=project_dir
    )
    return project, config


def test_parametrizacion_view_initializes_draft_and_shows_count(hidden_root, tmp_path: Path) -> None:
    project, config = _make_project_and_config(tmp_path)

    view = ParametrizacionView(hidden_root, config, project, "Buffalo_WET_MS_annual")

    assert view.draft_path.exists()
    assert "1" in view.count_label.cget("text")
    assert "2" in view.count_label.cget("text")


def test_parametrizacion_view_field_commit_persists_to_csv(hidden_root, tmp_path: Path) -> None:
    project, config = _make_project_and_config(tmp_path)
    view = ParametrizacionView(hidden_root, config, project, "Buffalo_WET_MS_annual")
    view._select_row(1)

    view._on_field_commit("wet_fr", 0.8)

    assert read_draft(view.draft_path).loc[1, "wet_fr"] == 0.8


def test_parametrizacion_view_field_error_does_not_touch_csv(hidden_root, tmp_path: Path) -> None:
    project, config = _make_project_and_config(tmp_path)
    view = ParametrizacionView(hidden_root, config, project, "Buffalo_WET_MS_annual")
    view._select_row(1)

    view._on_field_error("wet_fr", "'x' no es un número válido.")

    assert read_draft(view.draft_path).loc[1, "wet_fr"] == 0.2
    assert view.error_label.cget("text") != ""
