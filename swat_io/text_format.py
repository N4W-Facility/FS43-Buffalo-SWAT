"""Parser genérico para el formato de línea de archivos de texto SWAT2012.

Formato compartido por .sub, .pnd y otros archivos de entrada:

    <valor>    | <CODIGO> : <descripción>

Ejemplo real (.pnd):

               0.001    | WET_FR : Fraction of subbasin area that drains into wetlands
"""
from __future__ import annotations

import re
from pathlib import Path

_LINE_PATTERN = re.compile(
    r"^\s*(?P<value>\S+)\s*\|\s*(?P<code>[A-Za-z0-9_]+)\s*:\s*(?P<desc>.*)$"
)


def parse_value_code_file(path: Path) -> dict[str, str]:
    """Lee un archivo SWAT de texto plano y devuelve {CODIGO: valor_crudo}.

    Ignora líneas que no siguen el patrón "valor | CODIGO : descripción"
    (encabezados de sección, bloques de arreglos, líneas en blanco). Los
    valores se devuelven como string sin convertir; la conversión a
    int/float es responsabilidad de la capa de modelos.
    """
    values: dict[str, str] = {}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            match = _LINE_PATTERN.match(line)
            if match:
                values[match.group("code")] = match.group("value")
    return values
