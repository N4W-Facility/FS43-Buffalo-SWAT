"""Parser de plant.dat/crop.dat con preservación exacta de estructura.

El archivo es una secuencia estricta de bloques de 5 líneas (un registro
vegetal cada uno, ver models.py); a diferencia de .hru/.mgt, no hay
encabezado, comentarios ni líneas sueltas -- verificado contra el
plant.dat real de tres modelos del proyecto. Si el conteo de líneas no es
múltiplo de 5 se considera un archivo no reconocido (no se intenta
adivinar dónde empieza/termina cada registro).
"""
from __future__ import annotations

import re
from pathlib import Path

from ..common.encoding import read_text_with_fallback
from ..common.line_parser import split_lines_keep_newlines
from .exceptions import PlantDatParseError, PlantDatReadError
from .models import LINE2_FIELDS, LINE3_FIELDS, LINE4_FIELDS, LINE5_FIELDS, PlantDatFile, PlantRecord

_TOKEN_RE = re.compile(r"\S+")
_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def _coerce_numeric(raw: str):
    if _INT_RE.match(raw):
        return int(raw)
    if _FLOAT_RE.match(raw):
        return float(raw)
    return raw


def _fill_line_fields(fields: dict, line_text: str, names: list[str]) -> None:
    values = _tokens(line_text)
    for i, name in enumerate(names):
        fields[name] = _coerce_numeric(values[i]) if i < len(values) else None


def _parse_record(chunk: list[tuple[str, str]], record_index: int, source_path: Path | None) -> PlantRecord:
    (l1, nl1), (l2, nl2), (l3, nl3), (l4, nl4), (l5, nl5) = chunk

    t1 = _tokens(l1)
    if len(t1) < 3:
        raise PlantDatParseError(
            f"{source_path or '<texto>'}: registro #{record_index + 1} de plant.dat -- la línea 1 "
            f"('{l1}') no tiene los 3 campos esperados (ICNUM CPNM IDC)."
        )
    if not _INT_RE.match(t1[0]) or not _INT_RE.match(t1[2]):
        raise PlantDatParseError(
            f"{source_path or '<texto>'}: registro #{record_index + 1} de plant.dat -- ICNUM/IDC no "
            f"numéricos en la línea 1 ('{l1}')."
        )

    icnum = int(t1[0])
    cpnm = t1[1]
    idc = int(t1[2])

    fields: dict = {"ICNUM": icnum, "CPNM": cpnm, "IDC": idc}
    _fill_line_fields(fields, l2, LINE2_FIELDS)
    _fill_line_fields(fields, l3, LINE3_FIELDS)
    _fill_line_fields(fields, l4, LINE4_FIELDS)
    _fill_line_fields(fields, l5, LINE5_FIELDS)

    return PlantRecord(
        icnum=icnum, cpnm=cpnm, idc=idc,
        line1=l1, newline1=nl1,
        line2=l2, newline2=nl2,
        line3=l3, newline3=nl3,
        line4=l4, newline4=nl4,
        line5=l5, newline5=nl5,
        fields=fields,
    )


def parse_plant_dat_text(text: str, *, source_path: Path | None = None, encoding: str = "utf-8") -> PlantDatFile:
    """Parsea el contenido ya decodificado de un archivo plant.dat/crop.dat."""
    physical_lines = split_lines_keep_newlines(text)
    while physical_lines and physical_lines[-1][0].strip() == "":
        physical_lines.pop()

    if len(physical_lines) % 5 != 0:
        raise PlantDatParseError(
            f"{source_path or '<texto>'}: se esperaban bloques de 5 líneas por registro vegetal, "
            f"pero el archivo tiene {len(physical_lines)} líneas de contenido (no es múltiplo de 5)."
        )

    records = [
        _parse_record(physical_lines[i:i + 5], i // 5, source_path)
        for i in range(0, len(physical_lines), 5)
    ]

    return PlantDatFile(source_path=source_path, encoding=encoding, records=records)


def parse_plant_dat_file(path: str | Path) -> PlantDatFile:
    """Lee y parsea un archivo plant.dat/crop.dat desde disco."""
    path = Path(path)
    try:
        decoded = read_text_with_fallback(path)
    except OSError as exc:
        raise PlantDatReadError(f"No se pudo leer {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise PlantDatReadError(f"No se pudo decodificar {path} con las codificaciones soportadas: {exc}") from exc

    return parse_plant_dat_text(decoded.text, source_path=path, encoding=decoded.encoding)
