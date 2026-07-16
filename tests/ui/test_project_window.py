from pathlib import Path

from config.settings import ConfigManager
from engine.configure import configure_scenario
from scenarios.models import Project
from tests.helpers import make_synthetic_txtinout
from ui.project_window import ProjectWindowFrame


def _make_project_and_config(tmp_path: Path) -> tuple[Project, ConfigManager]:
    resources_dir = Path(__file__).resolve().parents[2] / "resources"
    config = ConfigManager(resources_dir=resources_dir, config_file=tmp_path / "config.json")
    config.load_all()
    config.paths.swat_executable = tmp_path / "swat2012.exe"
    config.paths.swat_executable.write_text("fake binary")
    config.paths.target_executable_name = "swatUser.exe"

    base_dir = tmp_path / "base" / "Buffalo_calibrated_annual"
    txtinout_dir = make_synthetic_txtinout(base_dir, {1: {"WET_FR": 0.2}})
    project_dir = tmp_path / "workspace" / "Buffalo"
    project_dir.mkdir(parents=True)
    project = Project(
        watershed="Buffalo", base_model_dir=base_dir, base_txtinout_dir=txtinout_dir, project_dir=project_dir
    )
    return project, config


def test_project_window_starts_with_configure_disabled(hidden_root, tmp_path: Path) -> None:
    project, config = _make_project_and_config(tmp_path)
    frame = ProjectWindowFrame(hidden_root, config, project)

    assert frame.configure_button.cget("state") == "disabled"


def test_project_window_setting_a_scenario_enables_configure_and_shows_form(hidden_root, tmp_path: Path) -> None:
    project, config = _make_project_and_config(tmp_path)
    frame = ProjectWindowFrame(hidden_root, config, project)

    frame._activate_scenario("Buffalo_WET_MS_annual")

    assert frame.configure_button.cget("state") == "normal"
    assert frame.scenario_label.cget("text") == "Buffalo_WET_MS_annual"
    assert len(frame.content.winfo_children()) == 1


def test_project_window_configure_scenario_materializes_and_disables_button(hidden_root, tmp_path: Path) -> None:
    project, config = _make_project_and_config(tmp_path)
    frame = ProjectWindowFrame(hidden_root, config, project)
    frame._activate_scenario("Buffalo_WET_MS_annual")

    frame._configure_scenario()

    assert (project.project_dir / "Buffalo_WET_MS_annual" / "TxtInOut" / "swatUser.exe").exists()
    assert frame.configure_button.cget("state") == "disabled"
