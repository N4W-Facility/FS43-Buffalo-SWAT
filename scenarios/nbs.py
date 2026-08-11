"""Modelo de datos y almacenamiento de la biblioteca de NbS (Soluciones
basadas en la Naturaleza) -- pestaña NbS (asistente de cambio/creación de
cobertura, ver CLAUDE.md).

Una NbS agrupa todo lo que la guía del proyecto exige para representar
correctamente un cambio de cobertura vegetal en SWAT2012 rev670 (no solo un
PLANT_ID): opcionalmente un registro fisiológico nuevo en plant.dat,
parámetros de superficie (.hru: CANMX, OV_N, RSDIN), condición inicial y
CN2 por grupo hidrológico de suelo (.mgt), y el calendario completo de
operaciones de manejo (.mgt) -- ver
SWAT2012_rev670_guia_general_cambio_creacion_coberturas.md.

Se guarda en JSON (no CSV: el calendario de operaciones es una lista de
longitud variable, mal representada en una fila plana) en
<proyecto>/tool_outputs/nbs_library.json -- una lista de NbS por proyecto;
el usuario puede crear varias antes de aplicar ninguna (ver
scenarios/nbs_apply.py). Sin dependencias de UI ni de swat2012.exe.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from swat_io.tool_outputs import tool_outputs_dir

HYDROLOGIC_SOIL_GROUPS: tuple[str, ...] = ("A", "B", "C", "D")

_LIBRARY_FILENAME = "nbs_library.json"


class NbSError(Exception):
    """Error del modelo o almacenamiento de una NbS."""


@dataclass
class NbSOperation:
    """Una operación de manejo del calendario de la NbS (ver
    swat_io.mgt.operation_specs para el significado de ``mgt_op`` y de las
    claves válidas de ``fields`` según el tipo de operación)."""

    mgt_op: int
    month: int | None = None
    day: int | None = None
    husc: float | None = None
    fields: dict[str, float | int | None] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"mgt_op": self.mgt_op, "month": self.month, "day": self.day, "husc": self.husc, "fields": dict(self.fields)}

    @staticmethod
    def from_dict(data: dict) -> "NbSOperation":
        return NbSOperation(
            mgt_op=data["mgt_op"],
            month=data.get("month"),
            day=data.get("day"),
            husc=data.get("husc"),
            fields=dict(data.get("fields", {})),
        )


@dataclass
class NbSNewCoverage:
    """Fisiología vegetal de una cobertura nueva (registro plant.dat). El
    ICNUM no se guarda aquí: se resuelve como max(ICNUM)+1 en el momento de
    aplicar (ver scenarios/nbs_apply.py), no al crear la NbS -- plant.dat
    puede haber cambiado entre medio (otra NbS con cobertura nueva ya
    aplicada, u otro proyecto)."""

    cpnm: str
    idc: int
    physiology: dict[str, float | int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"cpnm": self.cpnm, "idc": self.idc, "physiology": dict(self.physiology)}

    @staticmethod
    def from_dict(data: dict) -> "NbSNewCoverage":
        return NbSNewCoverage(cpnm=data["cpnm"], idc=data["idc"], physiology=dict(data.get("physiology", {})))


@dataclass
class NbSDefinition:
    name: str
    target_lulc: str  # CPNM de la cobertura objetivo (existente o nueva)
    new_coverage: NbSNewCoverage | None  # None si target_lulc ya existe en plant.dat

    hru_params: dict[str, float | None] = field(default_factory=dict)  # CANMX, OV_N, RSDIN
    mgt_initial: dict[str, float | int | None] = field(default_factory=dict)  # IGRO, LAI_INIT, BIO_INIT, PHU_PLT
    cn2_by_hsg: dict[str, float] = field(default_factory=dict)  # subconjunto de HYDROLOGIC_SOIL_GROUPS
    operations: list[NbSOperation] = field(default_factory=list)

    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "target_lulc": self.target_lulc,
            "new_coverage": self.new_coverage.to_dict() if self.new_coverage is not None else None,
            "hru_params": dict(self.hru_params),
            "mgt_initial": dict(self.mgt_initial),
            "cn2_by_hsg": dict(self.cn2_by_hsg),
            "operations": [op.to_dict() for op in self.operations],
            "description": self.description,
        }

    @staticmethod
    def from_dict(data: dict) -> "NbSDefinition":
        new_coverage_data = data.get("new_coverage")
        return NbSDefinition(
            name=data["name"],
            target_lulc=data["target_lulc"],
            new_coverage=NbSNewCoverage.from_dict(new_coverage_data) if new_coverage_data is not None else None,
            hru_params=dict(data.get("hru_params", {})),
            mgt_initial=dict(data.get("mgt_initial", {})),
            cn2_by_hsg=dict(data.get("cn2_by_hsg", {})),
            operations=[NbSOperation.from_dict(op) for op in data.get("operations", [])],
            description=data.get("description", ""),
        )


def library_path(project_dir: Path | str) -> Path:
    """Ruta de la biblioteca de NbS del proyecto (no crea la carpeta;
    ``tool_outputs_dir`` sí, se usa al guardar)."""
    return Path(project_dir) / "tool_outputs" / _LIBRARY_FILENAME


def load_library(project_dir: Path | str) -> list[NbSDefinition]:
    """Lee la biblioteca de NbS del proyecto. Lista vacía si todavía no
    existe (proyecto sin ninguna NbS creada)."""
    path = library_path(project_dir)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [NbSDefinition.from_dict(item) for item in raw]


def save_library(project_dir: Path | str, definitions: list[NbSDefinition]) -> Path:
    path = tool_outputs_dir(project_dir) / _LIBRARY_FILENAME
    data = [d.to_dict() for d in definitions]
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(path)
    return path


def add_or_replace(project_dir: Path | str, definition: NbSDefinition) -> list[NbSDefinition]:
    """Agrega ``definition`` a la biblioteca, o reemplaza la existente con
    el mismo nombre (los nombres de NbS son únicos dentro de un proyecto)."""
    definitions = [d for d in load_library(project_dir) if d.name != definition.name]
    definitions.append(definition)
    save_library(project_dir, definitions)
    return definitions


def delete_definition(project_dir: Path | str, name: str) -> list[NbSDefinition]:
    definitions = [d for d in load_library(project_dir) if d.name != name]
    save_library(project_dir, definitions)
    return definitions
