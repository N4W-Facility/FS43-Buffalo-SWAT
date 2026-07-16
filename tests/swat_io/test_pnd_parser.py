from pathlib import Path

from swat_io.pnd_parser import parse_pnd_file, write_wetland_params
from tests.helpers import write_synthetic_pnd


def test_write_wetland_params_updates_requested_fields(tmp_path: Path) -> None:
    path = tmp_path / "000010000.pnd"
    write_synthetic_pnd(path, {"WET_FR": 0.1, "WET_K": 50.0})

    write_wetland_params(path, {"wet_fr": 0.6, "wet_nsa": 20.5})

    params = parse_pnd_file(path, subbasin_id=1)
    assert params.wet_fr == 0.6
    assert params.wet_nsa_ha == 20.5
    assert params.wet_k_mmhr == 50.0  # untouched
