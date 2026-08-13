"""Validación de archivos .hru ya parseados.

Los problemas detectados no son todos fatales: se clasifican en niveles
INFO / WARNING / ERROR (ver ``HRUValidationIssue.severity``) y se
reportan todos, sin detener el proceso.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..common.line_parser import split_lines_keep_newlines
from .models import HRUFile, HRUParameterLine, HRURawLine

SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"
SEVERITY_ERROR = "ERROR"

_METADATA_FIELDS = ("subbasin", "hru", "land_use", "soil")


@dataclass
class HRUValidationIssue:
    severity: str
    code: str
    message: str
    path: Path | None
    line_number: int | None
    parameter: str | None


def _issue(
    severity: str,
    code: str,
    message: str,
    path: Path | None,
    line_number: int | None,
    parameter: str | None,
) -> HRUValidationIssue:
    return HRUValidationIssue(
        severity=severity, code=code, message=message, path=path, line_number=line_number, parameter=parameter
    )


def _looks_parametric(text: str) -> bool:
    """Heurística para detectar una línea sin parsear que "parece" un
    parámetro (contiene el separador '|' pero no encajó en la gramática)."""
    return "|" in text and text.strip() != ""


def _filename_ids(path: Path) -> tuple[int, int] | None:
    from .parser import _filename_ids as parser_filename_ids

    return parser_filename_ids(path)


def validate_hru_file(hru_file: HRUFile) -> list[HRUValidationIssue]:
    issues: list[HRUValidationIssue] = []
    path = hru_file.source_path

    if not hru_file.lines:
        issues.append(_issue(SEVERITY_ERROR, "EMPTY_FILE", "The .hru file is empty.", path, None, None))
        return issues

    parameter_lines = [line for line in hru_file.lines if isinstance(line, HRUParameterLine)]
    if not parameter_lines:
        issues.append(
            _issue(SEVERITY_ERROR, "NO_PARAMETERS", "No parameter was recognized in the file.", path, None, None)
        )

    by_name: dict[str, list[HRUParameterLine]] = {}
    for line in parameter_lines:
        by_name.setdefault(line.parameter_name.upper(), []).append(line)

    for name, occurrences in by_name.items():
        if len(occurrences) > 1:
            issues.append(
                _issue(
                    SEVERITY_WARNING,
                    "DUPLICATE_PARAMETER",
                    f"Parameter {name} appears {len(occurrences)} times (lines "
                    f"{[o.line_number for o in occurrences]}).",
                    path,
                    occurrences[0].line_number,
                    name,
                )
            )

    hru_fr_lines = by_name.get("HRU_FR", [])
    if not hru_fr_lines:
        issues.append(_issue(SEVERITY_ERROR, "MISSING_HRU_FR", "Parameter HRU_FR was not found.", path, None, "HRU_FR"))
    else:
        hru_fr_value = hru_fr_lines[0].parsed_value
        if not isinstance(hru_fr_value, (int, float)):
            issues.append(
                _issue(
                    SEVERITY_ERROR,
                    "HRU_FR_NOT_NUMERIC",
                    f"HRU_FR is not numeric: {hru_fr_value!r}.",
                    path,
                    hru_fr_lines[0].line_number,
                    "HRU_FR",
                )
            )
        else:
            if hru_fr_value < 0:
                issues.append(
                    _issue(
                        SEVERITY_ERROR,
                        "HRU_FR_NEGATIVE",
                        f"HRU_FR is negative: {hru_fr_value}.",
                        path,
                        hru_fr_lines[0].line_number,
                        "HRU_FR",
                    )
                )
            if hru_fr_value > 1:
                issues.append(
                    _issue(
                        SEVERITY_ERROR,
                        "HRU_FR_OUT_OF_RANGE",
                        f"HRU_FR greater than 1: {hru_fr_value}.",
                        path,
                        hru_fr_lines[0].line_number,
                        "HRU_FR",
                    )
                )

    metadata = hru_file.metadata
    missing_metadata = [name for name in _METADATA_FIELDS if getattr(metadata, name) is None]
    if missing_metadata:
        issues.append(
            _issue(
                SEVERITY_INFO,
                "MISSING_METADATA",
                f"Missing metadata: {', '.join(missing_metadata)}.",
                path,
                None,
                None,
            )
        )

    if path is not None:
        filename_ids = _filename_ids(path)
        if filename_ids is not None and metadata.subbasin is not None and metadata.hru is not None:
            filename_subbasin, filename_hru = filename_ids
            if (filename_subbasin, filename_hru) != (metadata.subbasin, metadata.hru):
                issues.append(
                    _issue(
                        SEVERITY_WARNING,
                        "METADATA_FILENAME_MISMATCH",
                        f"The content indicates subbasin={metadata.subbasin}, hru={metadata.hru}, "
                        f"but the filename indicates subbasin={filename_subbasin}, hru={filename_hru}. "
                        "The content takes priority.",
                        path,
                        None,
                        None,
                    )
                )

    for line in hru_file.lines:
        if isinstance(line, HRURawLine) and _looks_parametric(line.original_text):
            issues.append(
                _issue(
                    SEVERITY_WARNING,
                    "UNPARSED_PARAMETRIC_LINE",
                    "The line contains '|' but could not be parsed as a parameter.",
                    path,
                    line.line_number,
                    None,
                )
            )

    rendered_line_count = len(split_lines_keep_newlines(hru_file.render()))
    if rendered_line_count != len(hru_file.lines):
        issues.append(
            _issue(
                SEVERITY_ERROR,
                "RENDER_LINE_MISMATCH",
                f"Rendering produced {rendered_line_count} lines, expected {len(hru_file.lines)}.",
                path,
                None,
                None,
            )
        )

    if hru_file.encoding not in ("utf-8", "utf-8-sig"):
        issues.append(
            _issue(
                SEVERITY_INFO,
                "NON_UTF8_ENCODING",
                f"The file was decoded with '{hru_file.encoding}' (not UTF-8).",
                path,
                None,
                None,
            )
        )

    return issues
