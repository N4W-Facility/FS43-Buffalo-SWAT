import json
from pathlib import Path

_STRINGS_PATH = Path(__file__).resolve().parents[2] / "resources" / "strings" / "es.json"

_REQUIRED_NEW_KEYS = [
    "config.target_executable_name",
    "config.error.invalid_directory",
    "project.open_or_create",
    "project.no_selection",
    "project.no_scenario",
    "project.action.create",
    "project.action.open",
    "scenario.abbreviation",
    "scenario.timestep",
    "scenario.error.duplicate_name",
    "wetland.count",
    "wetland.import_csv",
    "wetland.import_error",
    "wetland.import_success",
    "action.configure_scenario",
]


def test_es_json_has_new_keys() -> None:
    strings = json.loads(_STRINGS_PATH.read_text(encoding="utf-8"))
    missing = [key for key in _REQUIRED_NEW_KEYS if key not in strings]
    assert missing == []


def test_wetland_count_has_expected_placeholders() -> None:
    strings = json.loads(_STRINGS_PATH.read_text(encoding="utf-8"))
    assert strings["wetland.count"].format(with_wetland=3, total=84) == "3 de 84 subcuencas con humedal"
