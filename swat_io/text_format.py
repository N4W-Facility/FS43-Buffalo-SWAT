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


def write_value_code_file(path: Path, updates: dict[str, float], *, decimals: int = 3) -> None:
    """Reescribe, sobre el mismo archivo, solo el valor numérico de las
    líneas cuyo CODIGO está en updates.

    El resto de cada línea (separador, código, descripción, salto de
    línea) queda exactamente igual. El nuevo valor se formatea justificado
    a la derecha dentro del ancho de campo que ya tenía esa línea (no se
    asume un ancho fijo global). decimals=3 por defecto (parámetros
    físicos de .pnd/.sub); file.cio usa decimals=0 -- sus campos
    (NBYR, IYR, IPRINT, NYSKIP) son enteros y swat2012.exe podría no
    tolerar un punto decimal en ese campo.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        match = _LINE_PATTERN.match(line)
        if match and match.group("code") in updates:
            width = match.end("value")
            new_value = updates[match.group("code")]
            formatted = f"{new_value:>{width}.{decimals}f}"
            line = formatted + line[match.end("value"):]
        new_lines.append(line)

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
