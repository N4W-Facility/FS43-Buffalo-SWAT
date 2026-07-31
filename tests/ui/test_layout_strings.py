"""No depende de renderizado real: solo valida que los YAML de layout carguen
y que cada label_key/unit_key que referencian exista en resources/strings/en.json
— evita textos faltantes en pantalla sin necesidad de montar widgets."""
import json
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_LAYOUT_DIR = _ROOT / "resources" / "layout"
_STRINGS_PATH = _ROOT / "resources" / "strings" / "en.json"


def _load_strings() -> dict:
    return json.loads(_STRINGS_PATH.read_text(encoding="utf-8"))


def test_summary_stats_layout_label_keys_exist_in_strings() -> None:
    strings = _load_strings()
    layout = yaml.safe_load((_LAYOUT_DIR / "summary_stats.yaml").read_text(encoding="utf-8"))

    assert layout["stats"], "summary_stats.yaml no debe quedar vacío"
    for spec in layout["stats"]:
        assert spec["label_key"] in strings
        unit_key = spec.get("unit_key")
        if unit_key:
            assert unit_key in strings


def test_project_metadata_layout_label_keys_exist_in_strings() -> None:
    strings = _load_strings()
    layout = yaml.safe_load((_LAYOUT_DIR / "project_metadata.yaml").read_text(encoding="utf-8"))

    assert layout["fields"], "project_metadata.yaml no debe quedar vacío"
    for field in layout["fields"]:
        assert field["label_key"] in strings


def test_wetland_params_layout_label_keys_exist_in_strings() -> None:
    strings = _load_strings()
    layout = yaml.safe_load((_LAYOUT_DIR / "wetland_params.yaml").read_text(encoding="utf-8"))

    assert layout["fields"], "wetland_params.yaml no debe quedar vacío"
    for field in layout["fields"]:
        assert field["label_key"] in strings
        assert len(field["range"]) == 2


def test_wetland_params_layout_matches_pnd_parser_fields() -> None:
    from swat_io.pnd_parser import _FIELD_TO_CODE

    layout = yaml.safe_load((_LAYOUT_DIR / "wetland_params.yaml").read_text(encoding="utf-8"))

    layout_ids = {field["id"] for field in layout["fields"]}
    assert layout_ids == set(_FIELD_TO_CODE.keys())
