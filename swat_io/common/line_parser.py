"""Utilidades genéricas para partir texto en líneas preservando su salto.

A diferencia de ``str.splitlines()``, aquí cada línea se devuelve como un
par ``(contenido_sin_salto, salto_original)`` para poder reconstruir el
archivo byte a byte, incluyendo el caso de que la última línea no termine
en salto de línea, o de que un archivo mezcle ``\\n`` y ``\\r\\n``.
"""
from __future__ import annotations

import re

_NEWLINE_RE = re.compile(r"(\r\n|\r|\n)$")


def split_lines_keep_newlines(text: str) -> list[tuple[str, str]]:
    """Parte ``text`` en pares ``(contenido, salto)``.

    ``salto`` es ``""`` para la última línea cuando el archivo no termina
    en salto de línea. Un texto vacío produce una lista vacía (no una
    línea vacía), reflejando que un archivo de 0 bytes no tiene líneas.
    """
    if text == "":
        return []
    result: list[tuple[str, str]] = []
    for raw_line in text.splitlines(keepends=True):
        match = _NEWLINE_RE.search(raw_line)
        if match:
            result.append((raw_line[: match.start()], match.group(1)))
        else:
            result.append((raw_line, ""))
    return result
