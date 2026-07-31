from pathlib import Path

from swat_io.pnd_parser import (
    _FIELD_TO_ATTR,
    _FIELD_TO_CODE,
    parse_pnd_file,
    wetland_params_to_field_values,
    write_wetland_params,
)
from tests.helpers import write_synthetic_pnd


def test_write_wetland_params_updates_requested_fields(tmp_path: Path) -> None:
    path = tmp_path / "000010000.pnd"
    write_synthetic_pnd(path, {"WET_FR": 0.1, "WET_K": 50.0})

    write_wetland_params(path, {"wet_fr": 0.6, "wet_nsa": 20.5})

    params = parse_pnd_file(path, subbasin_id=1)
    assert params.wet_fr == 0.6
    assert params.wet_nsa_ha == 20.5
    assert params.wet_k_mmhr == 50.0  # untouched


def test_field_to_code_and_field_to_attr_cover_the_same_20_fields() -> None:
    assert set(_FIELD_TO_CODE.keys()) == set(_FIELD_TO_ATTR.keys())
    assert len(_FIELD_TO_CODE) == 20


def test_write_wetland_params_updates_all_20_fields(tmp_path: Path) -> None:
    path = tmp_path / "000010000.pnd"
    write_synthetic_pnd(path, {})

    write_wetland_params(path, {field_id: 3.0 for field_id in _FIELD_TO_CODE})

    params = parse_pnd_file(path, subbasin_id=1)
    values = wetland_params_to_field_values(params)
    assert all(value == 3.0 for value in values.values())


def test_wetland_params_to_field_values_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "000010000.pnd"
    write_synthetic_pnd(path, {"WET_FR": 0.42, "CHLAW": 0.15, "WETEVCOEFF": 0.6})

    params = parse_pnd_file(path, subbasin_id=1)
    values = wetland_params_to_field_values(params)

    assert values["wet_fr"] == 0.42
    assert values["chlaw"] == 0.15
    assert values["wetevcoeff"] == 0.6
