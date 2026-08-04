import json
from pathlib import Path

_STRINGS_PATH = Path(__file__).resolve().parents[2] / "resources" / "strings" / "en.json"

_REQUIRED_KEYS = [
    "app.title",
    "tab.project",
    "tab.summary",
    "tab.results",
    "results_tab.title",
    "results_tab.organize_button",
    "results_tab.no_rch_hint",
    "results_tab.reach_label",
    "results_tab.variable_label",
    "tab.hru_results",
    "tab.batch",
    "batch_tab.title",
    "batch_tab.destination_label",
    "batch_tab.config_csv_label",
    "batch_tab.load_csv_button",
    "batch_tab.download_template_button",
    "batch_tab.preview_title",
    "batch_tab.run_button",
    "hru_results_tab.title",
    "hru_results_tab.organize_button",
    "hru_results_tab.no_hru_output_hint",
    "hru_results_tab.subbasin_label",
    "hru_results_tab.hru_label",
    "hru_results_tab.variable_label",
    "hru_results_tab.export_series_button",
    "hru_results_tab.export_subbasin_button",
    "project.shapefiles_title",
    "project.subbasin_shp_label",
    "project.reach_shp_label",
    "project.error.invalid_shp",
    "config.target_executable_name",
    "config.error.invalid_directory",
    "project.open",
    "project.change",
    "project.empty_hint",
    "project.name",
    "project.description",
    "project.edit",
    "project.edit_title",
    "project.error.no_txtinout",
    "project.no_selection",
    "project.no_scenario",
    "project.load",
    "scenario.name",
    "scenario.error.duplicate_name",
    "wetland.count",
    "wetland.import_csv",
    "wetland.import_error",
    "wetland.import_success",
    "action.parametrizacion",
    "action.save",
    "action.cancel",
    "menu.wetlands",
    "summary.disabled_hint",
    "summary.run",
    "summary.check_wetlands",
    "summary.check_hru",
    "summary.group_wetlands",
    "summary.group_hru",
    "summary.generated_at",
    "summary.never",
    "summary.open_output_folder",
    "summary.error",
    "stat.subbasins",
    "stat.total_area",
    "stat.wetland_area",
    "stat.wetland_coverage",
    "stat.subbasins_with_wetland",
    "stat.hru_count",
    "stat.land_use_count",
    "stat.simulation_period",
    "unit.km2",
    "unit.ha",
    "unit.pct",
    "unit.years",
]


def test_en_json_has_required_keys() -> None:
    strings = json.loads(_STRINGS_PATH.read_text(encoding="utf-8"))
    missing = [key for key in _REQUIRED_KEYS if key not in strings]
    assert missing == []


def test_wetland_count_has_expected_placeholders() -> None:
    strings = json.loads(_STRINGS_PATH.read_text(encoding="utf-8"))
    assert strings["wetland.count"].format(with_wetland=3, total=84) == "3 of 84 subbasins with wetland"


def test_summary_generated_at_has_timestamp_placeholder() -> None:
    strings = json.loads(_STRINGS_PATH.read_text(encoding="utf-8"))
    formatted = strings["summary.generated_at"].format(timestamp="2026-07-30T12:00:00")
    assert formatted == "Generated: 2026-07-30T12:00:00"
