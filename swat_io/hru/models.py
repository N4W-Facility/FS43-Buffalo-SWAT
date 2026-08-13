"""Modelo de datos para archivos .hru de SWAT2012 rev. 670.

Diseño de ``HRUParameterLine`` (deliberadamente distinto de un esquema con
muchos campos de espacios en blanco por separado): cada línea paramétrica
guarda ``prefix`` (todo lo anterior al valor), ``raw_value``/``suffix``
(el valor y todo lo posterior, tal cual). Esto garantiza que
``prefix + raw_value + suffix == original_text`` siempre, incluso después
de modificar el valor, sin necesidad de reconstruir separador, nombre o
descripción por separado: al no tocarlos nunca, quedan preservados por
construcción. Ver docs/hru_module.md para más detalle.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

from .exceptions import HRUModificationError

ParamValue = Union[int, float, str]


@dataclass
class HRURawLine:
    """Línea que no sigue la gramática de parámetro (encabezado, comentario,
    línea en blanco, o cualquier línea que no se pudo interpretar)."""

    line_number: int
    original_text: str
    newline: str


@dataclass
class HRUParameterLine:
    """Línea con forma ``<valor> | <NOMBRE> : <descripción>`` (descripción y
    espacios variables opcionales)."""

    line_number: int
    original_text: str
    newline: str

    prefix: str
    raw_value: str
    suffix: str

    original_raw_value: str
    original_parsed_value: ParamValue | None
    parsed_value: ParamValue | None

    parameter_name: str
    description: str | None

    modified: bool = False

    def render(self) -> str:
        return self.prefix + self.raw_value + self.suffix


@dataclass
class HRUMetadata:
    subbasin: int | None = None
    hru: int | None = None
    gis_id: str | None = None
    land_use: str | None = None
    soil: str | None = None
    slope_class: str | None = None
    title: str | None = None


HRULine = Union[HRURawLine, HRUParameterLine]


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
    """Reformatea el campo de valor de una línea .hru al modificarla.

    Reglas (ver CLAUDE.md / prompt.md, sección "Modificación de
    parámetros"): mantener el ancho de campo original cuando sea posible,
    mantener el número de decimales del valor original cuando el nuevo
    valor sea compatible, nunca truncar el valor, y ampliar el campo (no
    reducirlo) cuando el valor formateado no quepa en el ancho original.
    """
    width = len(original_raw_value)

    if isinstance(new_value, str):
        formatted = new_value
    else:
        decimals = _decimal_places(original_raw_value)
        if decimals is None:
            # El campo original no era numérico reconocible: no hay una
            # precisión de referencia que preservar, se usa la
            # representación natural del valor.
            formatted = repr(new_value) if isinstance(new_value, float) else str(new_value)
        elif decimals == 0:
            if isinstance(new_value, int) or float(new_value).is_integer():
                formatted = str(int(new_value))
            else:
                # El original era un entero pero el nuevo valor tiene
                # parte decimal: no se trunca, se conserva tal cual.
                formatted = repr(float(new_value))
        else:
            formatted = f"{float(new_value):.{decimals}f}"

    if len(formatted) < width:
        formatted = formatted.rjust(width)
    return formatted


@dataclass
class HRUFile:
    """Representación completa y editable de un archivo .hru."""

    source_path: Path | None
    encoding: str
    lines: list[HRULine]
    metadata: HRUMetadata = field(default_factory=HRUMetadata)

    def get_parameter(self, name: str) -> HRUParameterLine | None:
        """Primera línea de parámetro cuyo nombre coincide (sin distinguir
        mayúsculas/minúsculas). ``None`` si no existe."""
        name_upper = name.upper()
        for line in self.lines:
            if isinstance(line, HRUParameterLine) and line.parameter_name.upper() == name_upper:
                return line
        return None

    def get_parameters(self, name: str) -> list[HRUParameterLine]:
        """Todas las líneas de parámetro con ese nombre (para detectar
        duplicados; ver validation.py)."""
        name_upper = name.upper()
        return [
            line
            for line in self.lines
            if isinstance(line, HRUParameterLine) and line.parameter_name.upper() == name_upper
        ]

    def has_parameter(self, name: str) -> bool:
        return self.get_parameter(name) is not None

    def get_value(self, name: str, default: ParamValue | float | None = None):
        param = self.get_parameter(name)
        return param.parsed_value if param is not None else default

    def set_value(self, name: str, value: ParamValue) -> None:
        """Modifica únicamente el campo de valor del parámetro ``name``.

        No crea parámetros nuevos: si ``name`` no existe se lanza
        ``HRUModificationError``, coherente con la regla de no introducir
        parámetros no presentes en el archivo original.
        """
        param = self.get_parameter(name)
        if param is None:
            raise HRUModificationError(
                f"Parameter '{name}' does not exist in "
                f"{self.source_path if self.source_path else '<no path>'}; "
                "new parameters are not created."
            )
        param.raw_value = format_value_field(param.original_raw_value, value)
        param.parsed_value = value
        param.modified = True

    def to_parameter_dict(self) -> dict[str, ParamValue | None]:
        """Diccionario {NOMBRE_EN_MAYUSCULAS: valor}. Ante duplicados,
        conserva el valor de la primera ocurrencia (ver validation.py para
        el reporte de duplicados)."""
        result: dict[str, ParamValue | None] = {}
        for line in self.lines:
            if isinstance(line, HRUParameterLine):
                key = line.parameter_name.upper()
                if key not in result:
                    result[key] = line.parsed_value
        return result

    def copy(self) -> "HRUFile":
        """Copia profunda e independiente (para preview_modifications)."""
        return copy.deepcopy(self)

    def validate(self) -> list:
        from .validation import validate_hru_file

        return validate_hru_file(self)

    def render(self) -> str:
        """Texto completo del archivo. Si ninguna línea fue modificada,
        es idéntico byte a byte al original (mismo texto, misma
        codificación al volver a escribirse)."""
        parts: list[str] = []
        for line in self.lines:
            if isinstance(line, HRUParameterLine):
                parts.append(line.render())
            else:
                parts.append(line.original_text)
            parts.append(line.newline)
        return "".join(parts)
