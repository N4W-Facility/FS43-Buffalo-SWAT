"""Parseo de archivos .sub (información general de subcuenca)."""
from __future__ import annotations

from pathlib import Path

from .models import SubbasinInfo
from .text_format import parse_value_code_file


def parse_sub_file(path: Path, subbasin_id: int) -> SubbasinInfo:
    """Lee un archivo .sub y devuelve la información general de la subcuenca."""
    raw = parse_value_code_file(path)
    return SubbasinInfo.from_raw(subbasin_id, raw, path)
