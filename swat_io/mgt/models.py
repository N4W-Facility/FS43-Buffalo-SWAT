"""Modelo de datos para archivos .mgt de SWAT2012 rev. 670.

Tres tipos de línea (mismo espíritu que swat_io.hru.models):

- ``MGTRawLine``: encabezados de sección, título, comentarios, cualquier
  línea que no siga ninguna de las dos gramáticas reconocidas.
- ``MGTHeaderLine``: línea "<valor> | <NOMBRE> : <descripción>" de la
  cabecera (IGRO, PLANT_ID, CN2, etc. -- misma gramática que .pnd/.sub).
- ``MGTOperation``: una línea de la sección "Operation Schedule", texto de
  ancho fijo sin nombres de columna en el archivo (ver operation_specs.py).
  Si no fue modificada, se re-emite ``original_text`` tal cual (round-trip
  byte a byte); si se modificó o se creó desde cero (NbS), se renderiza a
  ancho fijo desde ``fields`` con las columnas documentadas.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

from ..common.field_formatting import ParamValue, format_value_field
from .exceptions import MGTModificationError
from .operation_specs import COMMON_FIELDS, OPERATION_FIELD_SPECS, FieldSpec


@dataclass
class MGTRawLine:
    line_number: int
    original_text: str
    newline: str


@dataclass
class MGTHeaderLine:
    line_number: int
    original_text: str
    newline: str

    prefix: str
    raw_value: str
    suffix: str

    original_raw_value: str
    parsed_value: ParamValue | None

    parameter_name: str
    description: str | None

    modified: bool = False

    def render(self) -> str:
        return self.prefix + self.raw_value + self.suffix


def _format_operation_field(value: ParamValue | None, spec: FieldSpec) -> str:
    width = spec.end - spec.start + 1
    if value is None:
        return " " * width
    if spec.decimals is None:
        text = str(int(value))
    else:
        text = f"{float(value):.{spec.decimals}f}"
    return text.rjust(width) if len(text) < width else text


@dataclass
class MGTOperation:
    """Una operación de manejo (siembra, cosecha, pastoreo, etc.).

    ``fields`` guarda únicamente los campos propios del ``mgt_op`` (ver
    operation_specs.OPERATION_FIELD_SPECS), ya convertidos a int/float;
    ``None`` si ese campo está en blanco en el archivo.
    """

    mgt_op: int
    month: int | None = None
    day: int | None = None
    husc: float | None = None
    fields: dict[str, ParamValue | None] = field(default_factory=dict)

    line_number: int | None = None
    original_text: str | None = None
    newline: str = "\n"
    modified: bool = False

    def render(self) -> str:
        if self.original_text is not None and not self.modified:
            return self.original_text

        specs = OPERATION_FIELD_SPECS.get(self.mgt_op, ())
        max_end = max([f.end for f in COMMON_FIELDS] + [f.end for f in specs], default=18)
        chars: list[str] = [" "] * max_end

        def place(spec: FieldSpec, value: ParamValue | None) -> None:
            nonlocal chars
            text = _format_operation_field(value, spec)
            start0, _ = spec.slice_bounds()
            needed_end = start0 + len(text)
            if needed_end > len(chars):
                chars.extend([" "] * (needed_end - len(chars)))
            chars[start0:start0 + len(text)] = list(text)

        common_values = {"MONTH": self.month, "DAY": self.day, "HUSC": self.husc, "MGT_OP": self.mgt_op}
        for spec in COMMON_FIELDS:
            place(spec, common_values[spec.name])
        for spec in specs:
            place(spec, self.fields.get(spec.name))

        return "".join(chars).rstrip()


MGTLine = Union[MGTRawLine, MGTHeaderLine, MGTOperation]


@dataclass
class MGTMetadata:
    subbasin: int | None = None
    hru: int | None = None
    land_use: str | None = None
    title: str | None = None


@dataclass
class MGTFile:
    source_path: Path | None
    encoding: str
    newline: str
    lines: list[MGTLine]
    metadata: MGTMetadata = field(default_factory=MGTMetadata)

    def get_header_value(self, name: str) -> ParamValue | None:
        line = self._find_header_line(name)
        return line.parsed_value if line is not None else None

    def set_header_value(self, name: str, value: ParamValue) -> None:
        line = self._find_header_line(name)
        if line is None:
            raise MGTModificationError(
                f"El parámetro '{name}' no existe en la cabecera de "
                f"{self.source_path if self.source_path else '<sin ruta>'}; no se crean parámetros nuevos."
            )
        line.raw_value = format_value_field(line.original_raw_value, value)
        line.parsed_value = value
        line.modified = True

    def _find_header_line(self, name: str) -> MGTHeaderLine | None:
        name_upper = name.upper()
        for line in self.lines:
            if isinstance(line, MGTHeaderLine) and line.parameter_name.upper() == name_upper:
                return line
        return None

    def operations(self) -> list[MGTOperation]:
        return [line for line in self.lines if isinstance(line, MGTOperation)]

    def replace_operations(self, new_operations: list[MGTOperation]) -> None:
        """Reemplaza toda la sección "Operation Schedule" por
        ``new_operations``. La cabecera y cualquier línea anterior a esa
        sección quedan intactas; si ya no quedaba ninguna operación en el
        archivo (caso límite), las nuevas se agregan al final."""
        result: list[MGTLine] = []
        inserted = False
        for line in self.lines:
            if isinstance(line, MGTOperation):
                if not inserted:
                    result.extend(new_operations)
                    inserted = True
                continue
            result.append(line)
            if (
                not inserted
                and isinstance(line, MGTRawLine)
                and line.original_text.strip().lower().startswith("operation schedule")
            ):
                result.extend(new_operations)
                inserted = True
        if not inserted:
            result.extend(new_operations)
        self.lines = result

    def copy(self) -> "MGTFile":
        return copy.deepcopy(self)

    def render(self) -> str:
        parts: list[str] = []
        for line in self.lines:
            if isinstance(line, MGTOperation):
                parts.append(line.render())
                parts.append(line.newline if line.original_text is not None else self.newline)
            elif isinstance(line, MGTHeaderLine):
                parts.append(line.render())
                parts.append(line.newline)
            else:
                parts.append(line.original_text)
                parts.append(line.newline)
        return "".join(parts)
