"""Parser de archivos .hru con preservación exacta de estructura.

Gramática reconocida por línea, de forma flexible (los espacios en torno
al separador ``|`` y a los dos puntos son variables u opcionales):

    <valor> | <NOMBRE> : <descripción>
    <valor>|<NOMBRE>:<descripción>
    <valor> | <NOMBRE>

Cualquier línea que no encaje (encabezados, líneas en blanco, comentarios,
líneas dañadas) se conserva como ``HRURawLine`` sin intentar interpretarla
de forma agresiva. El parser nunca lanza una excepción por una línea
individual no reconocida.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..common.encoding import read_text_with_fallback
from ..common.line_parser import split_lines_keep_newlines
from .exceptions import HRUReadError
from .models import HRUFile, HRUMetadata, HRUParameterLine, HRURawLine, ParamValue

# Primer token no-blanco de la línea (el valor) y todo lo que sigue. El
# valor no puede contener '|': el separador puede venir pegado al valor
# sin espacio ("0.7500|HRU_FR:desc"), así que no basta con cortar en el
# primer espacio.
_VALUE_RE = re.compile(r"^(?P<prefix>[ \t]*)(?P<value>[^\s|]+)(?P<rest>.*)$")

# Lo que debe seguir al valor para que la línea cuente como parámetro:
# separador "|", nombre de parámetro, y opcionalmente ": descripción".
_PARAMETER_REST_RE = re.compile(
    r"^(?P<pre_sep>[ \t]*)\|(?P<post_sep>[ \t]*)"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:[ \t]*:(?P<desc>.*))?[ \t]*$"
)

_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")

_HEADER_FIELD_RE = re.compile(
    r"\b(?P<label>Subbasin|Hru|Luse|Soil|Slope|Gis)\s*:\s*(?P<value>\S+)",
    re.IGNORECASE,
)

_FILENAME_ID_RE = re.compile(r"^(\d{9})$")


def _coerce_value(raw_value: str) -> ParamValue:
    """Convierte el token de valor a int/float cuando es posible; si no,
    lo conserva como texto sin alterarlo."""
    if _INT_RE.match(raw_value):
        return int(raw_value)
    if _FLOAT_RE.match(raw_value):
        return float(raw_value)
    return raw_value


def _parse_line(line_number: int, content: str, newline: str) -> HRURawLine | HRUParameterLine:
    value_match = _VALUE_RE.match(content)
    if value_match is None:
        # Línea en blanco (o solo espacios): no hay token de valor.
        return HRURawLine(line_number=line_number, original_text=content, newline=newline)

    rest_match = _PARAMETER_REST_RE.match(value_match.group("rest"))
    if rest_match is None:
        return HRURawLine(line_number=line_number, original_text=content, newline=newline)

    raw_value = value_match.group("value")
    value_end = value_match.end("value")
    desc_group = rest_match.group("desc")
    description = desc_group.strip() if desc_group is not None else None
    parsed_value = _coerce_value(raw_value)

    return HRUParameterLine(
        line_number=line_number,
        original_text=content,
        newline=newline,
        prefix=content[: value_match.start("value")],
        raw_value=raw_value,
        suffix=content[value_end:],
        original_raw_value=raw_value,
        original_parsed_value=parsed_value,
        parsed_value=parsed_value,
        parameter_name=rest_match.group("name"),
        description=description,
    )


def _filename_ids(path: Path) -> tuple[int, int] | None:
    """Subcuenca y HRU implícitos en el nombre de archivo (convención
    NNNNNMMMM.hru, igual que .sub/.pnd: 5 dígitos de subcuenca + 4 de HRU).

    Devuelve None si el nombre no sigue esa convención; no se asume que
    todos los archivos .hru la respeten.
    """
    match = _FILENAME_ID_RE.match(path.stem)
    if match is None:
        return None
    raw = int(match.group(1))
    return raw // 10000, raw % 10000


def _scan_header_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in _HEADER_FIELD_RE.finditer(text):
        label = match.group("label").lower()
        fields.setdefault(label, match.group("value"))
    return fields


def _extract_metadata(lines: list, source_path: Path | None) -> HRUMetadata:
    """Extrae metadatos con prioridad: contenido del archivo primero,
    nombre de archivo como último recurso (nunca al revés)."""
    raw_lines = [line for line in lines if isinstance(line, HRURawLine)]

    header_fields: dict[str, str] = {}
    for raw_line in raw_lines:
        header_fields.update(
            {k: v for k, v in _scan_header_fields(raw_line.original_text).items() if k not in header_fields}
        )

    title = None
    if lines and isinstance(lines[0], HRURawLine) and lines[0].original_text.strip():
        title = lines[0].original_text.strip()

    def _as_int(value: str | None) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    subbasin = _as_int(header_fields.get("subbasin"))
    hru = _as_int(header_fields.get("hru"))

    if (subbasin is None or hru is None) and source_path is not None:
        filename_ids = _filename_ids(source_path)
        if filename_ids is not None:
            fallback_subbasin, fallback_hru = filename_ids
            subbasin = subbasin if subbasin is not None else fallback_subbasin
            hru = hru if hru is not None else fallback_hru

    return HRUMetadata(
        subbasin=subbasin,
        hru=hru,
        gis_id=header_fields.get("gis"),
        land_use=header_fields.get("luse"),
        soil=header_fields.get("soil"),
        slope_class=header_fields.get("slope"),
        title=title,
    )


def parse_hru_text(
    text: str,
    *,
    source_path: Path | None = None,
    encoding: str = "utf-8",
) -> HRUFile:
    """Parsea el contenido ya decodificado de un archivo .hru."""
    lines: list = []
    for line_number, (content, newline) in enumerate(split_lines_keep_newlines(text), start=1):
        lines.append(_parse_line(line_number, content, newline))

    metadata = _extract_metadata(lines, source_path)
    return HRUFile(source_path=source_path, encoding=encoding, lines=lines, metadata=metadata)


def parse_hru_file(path: str | Path) -> HRUFile:
    """Lee y parsea un archivo .hru desde disco.

    La lectura es el comportamiento por defecto de este módulo; la
    escritura (writer.write_hru_file) siempre exige una ruta destino
    explícita, nunca implícita a partir de esta función.
    """
    path = Path(path)
    try:
        decoded = read_text_with_fallback(path)
    except OSError as exc:
        raise HRUReadError(f"No se pudo leer {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise HRUReadError(f"No se pudo decodificar {path} con las codificaciones soportadas: {exc}") from exc

    return parse_hru_text(decoded.text, source_path=path, encoding=decoded.encoding)
