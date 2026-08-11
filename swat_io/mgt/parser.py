"""Parser de archivos .mgt con preservación exacta de estructura.

Dos gramáticas conviven en el mismo archivo (ver models.py): la cabecera
usa "<valor> | <NOMBRE> : <descripción>" (igual que .hru/.pnd/.sub); la
sección "Operation Schedule" es texto de ancho fijo sin nombres de columna
(ver operation_specs.py). Una línea se intenta primero como cabecera
(inequívoco: solo esa gramática usa "|"); si no calza y ya se vio el
marcador "Operation Schedule:", se intenta como operación de ancho fijo.
Cualquier línea que no encaje en ninguna se conserva como ``MGTRawLine``
sin intentar interpretarla de forma agresiva -- el parser nunca lanza una
excepción por una línea individual no reconocida.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..common.encoding import read_text_with_fallback
from ..common.line_parser import split_lines_keep_newlines
from .exceptions import MGTReadError
from .models import MGTFile, MGTHeaderLine, MGTMetadata, MGTOperation, MGTRawLine
from .operation_specs import COMMON_FIELDS, OPERATION_FIELD_SPECS

_VALUE_RE = re.compile(r"^(?P<prefix>[ \t]*)(?P<value>[^\s|]+)(?P<rest>.*)$")
_PARAMETER_REST_RE = re.compile(
    r"^(?P<pre_sep>[ \t]*)\|(?P<post_sep>[ \t]*)"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:[ \t]*:(?P<desc>.*))?[ \t]*$"
)

_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")

_HEADER_FIELD_RE = re.compile(r"\b(?P<label>Subbasin|Hru|Luse)\s*:\s*(?P<value>\S+)", re.IGNORECASE)
_FILENAME_ID_RE = re.compile(r"^(\d{9})$")

_MGT_OP_SPEC = next(f for f in COMMON_FIELDS if f.name == "MGT_OP")
_MONTH_SPEC = next(f for f in COMMON_FIELDS if f.name == "MONTH")
_DAY_SPEC = next(f for f in COMMON_FIELDS if f.name == "DAY")
_HUSC_SPEC = next(f for f in COMMON_FIELDS if f.name == "HUSC")


def _coerce(raw: str):
    if _INT_RE.match(raw):
        return int(raw)
    if _FLOAT_RE.match(raw):
        return float(raw)
    return raw


def _try_parse_header_line(line_number: int, content: str, newline: str) -> MGTHeaderLine | None:
    value_match = _VALUE_RE.match(content)
    if value_match is None:
        return None
    rest_match = _PARAMETER_REST_RE.match(value_match.group("rest"))
    if rest_match is None:
        return None

    raw_value = value_match.group("value")
    value_end = value_match.end("value")
    desc_group = rest_match.group("desc")

    return MGTHeaderLine(
        line_number=line_number,
        original_text=content,
        newline=newline,
        prefix=content[: value_match.start("value")],
        raw_value=raw_value,
        suffix=content[value_end:],
        original_raw_value=raw_value,
        parsed_value=_coerce(raw_value),
        parameter_name=rest_match.group("name"),
        description=desc_group.strip() if desc_group is not None else None,
    )


def _extract_field(content: str, spec) -> int | float | None:
    start0, end0 = spec.slice_bounds()
    if len(content) <= start0:
        return None
    raw = content[start0:end0].strip()
    if raw == "":
        return None
    if spec.decimals is None:
        return int(raw) if _INT_RE.match(raw) else None
    return float(raw) if _FLOAT_RE.match(raw) else None


def _try_parse_operation_line(line_number: int, content: str, newline: str) -> MGTOperation | None:
    raw_op = _extract_field(content, _MGT_OP_SPEC)
    if raw_op is None:
        return None
    mgt_op = raw_op

    fields = {spec.name: _extract_field(content, spec) for spec in OPERATION_FIELD_SPECS.get(mgt_op, ())}

    return MGTOperation(
        mgt_op=mgt_op,
        month=_extract_field(content, _MONTH_SPEC),
        day=_extract_field(content, _DAY_SPEC),
        husc=_extract_field(content, _HUSC_SPEC),
        fields=fields,
        line_number=line_number,
        original_text=content,
        newline=newline,
        modified=False,
    )


def _scan_header_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in _HEADER_FIELD_RE.finditer(text):
        label = match.group("label").lower()
        fields.setdefault(label, match.group("value"))
    return fields


def _filename_ids(path: Path) -> tuple[int, int] | None:
    match = _FILENAME_ID_RE.match(path.stem)
    if match is None:
        return None
    raw = int(match.group(1))
    return raw // 10000, raw % 10000


def _extract_metadata(lines: list, source_path: Path | None) -> MGTMetadata:
    raw_lines = [line for line in lines if isinstance(line, MGTRawLine)]

    header_fields: dict[str, str] = {}
    for raw_line in raw_lines:
        header_fields.update(
            {k: v for k, v in _scan_header_fields(raw_line.original_text).items() if k not in header_fields}
        )

    title = None
    if lines and isinstance(lines[0], MGTRawLine) and lines[0].original_text.strip():
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

    return MGTMetadata(subbasin=subbasin, hru=hru, land_use=header_fields.get("luse"), title=title)


def parse_mgt_text(text: str, *, source_path: Path | None = None, encoding: str = "utf-8") -> MGTFile:
    """Parsea el contenido ya decodificado de un archivo .mgt."""
    lines: list = []
    schedule_started = False
    newline_counts: dict[str, int] = {}

    for line_number, (content, newline) in enumerate(split_lines_keep_newlines(text), start=1):
        if newline:
            newline_counts[newline] = newline_counts.get(newline, 0) + 1

        header_line = _try_parse_header_line(line_number, content, newline)
        if header_line is not None:
            lines.append(header_line)
            continue

        if schedule_started:
            op_line = _try_parse_operation_line(line_number, content, newline)
            if op_line is not None:
                lines.append(op_line)
                continue

        raw_line = MGTRawLine(line_number=line_number, original_text=content, newline=newline)
        lines.append(raw_line)
        if not schedule_started and content.strip().lower().startswith("operation schedule"):
            schedule_started = True

    dominant_newline = max(newline_counts, key=lambda k: newline_counts[k]) if newline_counts else "\n"
    metadata = _extract_metadata(lines, source_path)
    return MGTFile(source_path=source_path, encoding=encoding, newline=dominant_newline, lines=lines, metadata=metadata)


def parse_mgt_file(path: str | Path) -> MGTFile:
    """Lee y parsea un archivo .mgt desde disco."""
    path = Path(path)
    try:
        decoded = read_text_with_fallback(path)
    except OSError as exc:
        raise MGTReadError(f"No se pudo leer {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise MGTReadError(f"No se pudo decodificar {path} con las codificaciones soportadas: {exc}") from exc

    return parse_mgt_text(decoded.text, source_path=path, encoding=decoded.encoding)
