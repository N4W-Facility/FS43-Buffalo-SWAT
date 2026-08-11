"""Formateo de un campo de valor al modificar una línea "<valor> | <NOMBRE> :
<descripción>" de un archivo SWAT de texto plano.

Extraído como utilidad compartida (ver CLAUDE.md, sección swat_io/common/)
para que cualquier parser con esta misma gramática -- hoy .hru
(swat_io.hru.models), y .mgt (swat_io.mgt.models) -- la reutilice en vez
de reimplementarla. swat_io.hru.models mantiene su propia copia histórica
por no tocar código ya probado sin necesidad; los parsers nuevos deben
importar desde aquí.
"""
from __future__ import annotations

import re
from typing import Union

ParamValue = Union[int, float, str]

_NUMERIC_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")


def _decimal_places(raw_value: str) -> int | None:
    """Número de decimales de ``raw_value`` si es numérico, si no ``None``."""
    if not _NUMERIC_RE.match(raw_value):
        return None
    mantissa = raw_value.split("e")[0].split("E")[0]
    if "." not in mantissa:
        return 0
    return len(mantissa.split(".")[1])


def format_value_field(original_raw_value: str, new_value: ParamValue) -> str:
    """Reformatea el campo de valor de una línea al modificarla.

    Mantiene el ancho de campo original cuando sea posible, mantiene el
    número de decimales del valor original cuando el nuevo valor sea
    compatible, nunca trunca el valor, y amplía el campo (no lo reduce)
    cuando el valor formateado no cabe en el ancho original.
    """
    width = len(original_raw_value)

    if isinstance(new_value, str):
        formatted = new_value
    else:
        decimals = _decimal_places(original_raw_value)
        if decimals is None:
            formatted = repr(new_value) if isinstance(new_value, float) else str(new_value)
        elif decimals == 0:
            if isinstance(new_value, int) or float(new_value).is_integer():
                formatted = str(int(new_value))
            else:
                formatted = repr(float(new_value))
        else:
            formatted = f"{float(new_value):.{decimals}f}"

    if len(formatted) < width:
        formatted = formatted.rjust(width)
    return formatted
