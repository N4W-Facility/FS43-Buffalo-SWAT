"""Modelo de datos para plant.dat/crop.dat (base vegetal) de SWAT2012 rev. 670.

Formato: bloques de exactamente 5 líneas de texto libre (separado por
espacios, sin ancho de columna fijo) por registro vegetal -- ver SWAT2012
Input/Output File Documentation, capítulo 14
(swat.tamu.edu/media/69341/ch14_input_plantdb.pdf) y la guía del proyecto
(SWAT2012_rev670_guia_general_cambio_creacion_coberturas.md, sección 16-17).

Hallazgo verificado contra el plant.dat real de tres modelos distintos del
proyecto (Buffalo, Crooked, Cattaraugus -- idénticos entre sí, base vegetal
estándar sin personalizar): la línea 5 tiene solo 5 campos (``BIO_LEAF
MAT_YRS BMX_TREES EXT_COEF BMDIEOFF``), no los 7 que trae la documentación
oficial más reciente de SWAT2012 IO (que agrega ``RSR1C``/``RSR2C``). Esos
dos campos NO se exponen porque no existen en el archivo real que usa el
ejecutable rev670 de este proyecto -- inventarlos violaría la regla de "no
inventar parámetros" (ver guía, sección 24).

Cada línea de un registro se guarda como texto crudo (para poder editar un
único token sin alterar el resto de la línea, formato libre) más su salto
de línea original; ``PlantRecord.fields`` es la vista ya convertida a
int/float/str.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..common.field_formatting import ParamValue, format_value_field
from .exceptions import PlantDatModificationError

LINE1_FIELDS: list[str] = ["ICNUM", "CPNM", "IDC"]
LINE2_FIELDS: list[str] = ["BIO_E", "HVSTI", "BLAI", "FRGRW1", "LAIMX1", "FRGRW2", "LAIMX2", "DLAI", "CHTMX", "RDMX"]
LINE3_FIELDS: list[str] = [
    "T_OPT", "T_BASE", "CNYLD", "CPYLD",
    "PLTNFR1", "PLTNFR2", "PLTNFR3", "PLTPFR1", "PLTPFR2", "PLTPFR3",
]
LINE4_FIELDS: list[str] = [
    "WSYF", "USLE_C", "GSI", "VPDFR", "FRGMAX", "WAVP", "CO2HI", "BIOEHI", "RSDCO_PL", "ALAI_MIN",
]
LINE5_FIELDS: list[str] = ["BIO_LEAF", "MAT_YRS", "BMX_TREES", "EXT_COEF", "BMDIEOFF"]

# Campos de fisiología editables/requeribles para una cobertura nueva (todo
# lo del registro salvo ICNUM, que se resuelve aparte como max+1).
ALL_PHYSIOLOGY_FIELDS: list[str] = ["CPNM", "IDC"] + LINE2_FIELDS + LINE3_FIELDS + LINE4_FIELDS + LINE5_FIELDS

_TOKEN_RE = re.compile(r"\S+")

_LINE_FIELD_MAP: dict[str, tuple[int, int]] = {}
for _names, _line_no in ((LINE1_FIELDS, 1), (LINE2_FIELDS, 2), (LINE3_FIELDS, 3), (LINE4_FIELDS, 4), (LINE5_FIELDS, 5)):
    for _idx, _name in enumerate(_names):
        _LINE_FIELD_MAP[_name] = (_line_no, _idx)


@dataclass
class PlantRecord:
    icnum: int
    cpnm: str
    idc: int

    line1: str
    newline1: str
    line2: str
    newline2: str
    line3: str
    newline3: str
    line4: str
    newline4: str
    line5: str
    newline5: str

    fields: dict[str, ParamValue | None] = field(default_factory=dict)

    def get(self, name: str) -> ParamValue | None:
        return self.fields.get(name.upper())

    def set(self, name: str, value: ParamValue) -> None:
        name = name.upper()
        if name not in _LINE_FIELD_MAP:
            raise PlantDatModificationError(
                f"El campo '{name}' no existe en el registro vegetal ICNUM={self.icnum}."
            )
        line_no, token_index = _LINE_FIELD_MAP[name]
        line_attr = f"line{line_no}"
        text = getattr(self, line_attr)
        matches = list(_TOKEN_RE.finditer(text))
        if token_index >= len(matches):
            raise PlantDatModificationError(
                f"La línea {line_no} del registro ICNUM={self.icnum} no tiene el campo '{name}' "
                "(la línea tiene menos tokens de los esperados)."
            )
        match = matches[token_index]
        formatted = format_value_field(match.group(0), value)
        setattr(self, line_attr, text[: match.start()] + formatted + text[match.end():])
        self.fields[name] = value
        if name == "ICNUM":
            self.icnum = int(value)
        elif name == "CPNM":
            self.cpnm = str(value)
        elif name == "IDC":
            self.idc = int(value)

    def render(self) -> str:
        return (
            self.line1 + self.newline1
            + self.line2 + self.newline2
            + self.line3 + self.newline3
            + self.line4 + self.newline4
            + self.line5 + self.newline5
        )

    def copy(self) -> "PlantRecord":
        return copy.deepcopy(self)


@dataclass
class PlantDatFile:
    source_path: Path | None
    encoding: str
    records: list[PlantRecord]

    def get_record(self, icnum: int) -> PlantRecord | None:
        for record in self.records:
            if record.icnum == icnum:
                return record
        return None

    def get_record_by_cpnm(self, cpnm: str) -> PlantRecord | None:
        cpnm_upper = cpnm.upper()
        for record in self.records:
            if record.cpnm.upper() == cpnm_upper:
                return record
        return None

    def max_icnum(self) -> int:
        return max((r.icnum for r in self.records), default=0)

    def next_icnum(self) -> int:
        """ICNUM a asignar a una cobertura nueva: max(ICNUM existentes) + 1
        (política de numeración obligatoria de SWAT2012 rev670: únicos,
        ordenados, compactos, consecutivos -- sin huecos arbitrarios, ver
        guía del proyecto sección 19.4). Se resuelve en el momento de
        aplicar, no al crear la NbS -- ver CLAUDE.md/diseño NbS."""
        return self.max_icnum() + 1

    def is_cpnm_taken(self, cpnm: str) -> bool:
        return self.get_record_by_cpnm(cpnm) is not None

    def append_record(self, record: PlantRecord) -> None:
        if self.get_record(record.icnum) is not None:
            raise PlantDatModificationError(f"Ya existe un registro vegetal con ICNUM={record.icnum}.")
        if self.is_cpnm_taken(record.cpnm):
            raise PlantDatModificationError(f"Ya existe un registro vegetal con CPNM='{record.cpnm}'.")
        self.records.append(record)

    def copy(self) -> "PlantDatFile":
        return copy.deepcopy(self)

    def render(self) -> str:
        return "".join(record.render() for record in self.records)


def build_plant_record(
    icnum: int,
    cpnm: str,
    idc: int,
    values: dict[str, ParamValue],
    *,
    newline: str = "\r\n",
) -> PlantRecord:
    """Construye un ``PlantRecord`` nuevo desde cero (cobertura fisiológica
    nueva). Exige TODOS los campos de ``ALL_PHYSIOLOGY_FIELDS`` en
    ``values`` (sin CPNM/IDC, que se pasan aparte) -- regla de no invención
    de la guía del proyecto: no se rellenan valores por defecto en
    silencio si al usuario le falta indicar alguno.
    """
    if len(cpnm) != 4:
        raise PlantDatModificationError(f"CPNM debe tener exactamente 4 caracteres ('{cpnm}' tiene {len(cpnm)}).")

    numeric_fields = LINE2_FIELDS + LINE3_FIELDS + LINE4_FIELDS + LINE5_FIELDS
    missing = [name for name in numeric_fields if name not in values]
    if missing:
        raise PlantDatModificationError(
            "Faltan campos de fisiología vegetal para crear el nuevo registro: " + ", ".join(missing)
        )

    def _fmt(name: str) -> str:
        value = values[name]
        if name == "MAT_YRS":
            return str(int(value))
        return f"{float(value):.4f}"

    line1 = f"{icnum:4d}  {cpnm.upper():<4s} {idc:2d}"
    line2 = "  " + "   ".join(_fmt(n) for n in LINE2_FIELDS)
    line3 = "  " + "   ".join(_fmt(n) for n in LINE3_FIELDS)
    line4 = "  " + "   ".join(_fmt(n) for n in LINE4_FIELDS)
    line5 = "  " + "   ".join(_fmt(n) for n in LINE5_FIELDS)

    fields: dict[str, ParamValue | None] = {"ICNUM": icnum, "CPNM": cpnm.upper(), "IDC": idc}
    for name in numeric_fields:
        fields[name] = int(values[name]) if name == "MAT_YRS" else float(values[name])

    return PlantRecord(
        icnum=icnum,
        cpnm=cpnm.upper(),
        idc=idc,
        line1=line1, newline1=newline,
        line2=line2, newline2=newline,
        line3=line3, newline3=newline,
        line4=line4, newline4=newline,
        line5=line5, newline5=newline,
        fields=fields,
    )
