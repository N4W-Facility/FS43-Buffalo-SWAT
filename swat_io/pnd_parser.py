"""Parseo de archivos .pnd, sección "Wetland inputs"."""
from __future__ import annotations

from pathlib import Path

from .models import WetlandParams
from .text_format import parse_value_code_file


def parse_pnd_file(path: Path, subbasin_id: int) -> WetlandParams:
    """Lee un archivo .pnd y devuelve los parámetros de humedal de la subcuenca."""
    raw = parse_value_code_file(path)
    return WetlandParams.from_raw(subbasin_id, raw, path)
