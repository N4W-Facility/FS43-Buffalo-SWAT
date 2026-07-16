"""Parseo de archivos .pnd, sección "Wetland inputs"."""
from __future__ import annotations

from pathlib import Path

from .models import WetlandParams
from .text_format import parse_value_code_file, write_value_code_file


def parse_pnd_file(path: Path, subbasin_id: int) -> WetlandParams:
    """Lee un archivo .pnd y devuelve los parámetros de humedal de la subcuenca."""
    raw = parse_value_code_file(path)
    return WetlandParams.from_raw(subbasin_id, raw, path)


_FIELD_TO_CODE = {
    "wet_fr": "WET_FR",
    "wet_nsa": "WET_NSA",
    "wet_nvol": "WET_NVOL",
    "wet_mxsa": "WET_MXSA",
    "wet_mxvol": "WET_MXVOL",
    "wet_vol": "WET_VOL",
    "wet_k": "WET_K",
}


def write_wetland_params(path: Path, values: dict[str, float]) -> None:
    """Escribe los parámetros editables de humedal en un .pnd.

    values usa las claves del formulario declarativo (wet_fr, wet_nsa,
    ...), no los códigos SWAT crudos.
    """
    updates = {_FIELD_TO_CODE[field_id]: value for field_id, value in values.items()}
    write_value_code_file(path, updates)
