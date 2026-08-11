"""Motor de aplicación masiva de una NbS a un conjunto de HRU.

Dada una NbS ya creada (scenarios.nbs.NbSDefinition) y una lista de HRU
objetivo (subcuenca, hru), escribe:

- ``plant.dat``: solo si la NbS crea una cobertura nueva, y solo la primera
  vez (si ya existe un registro con ese CPNM -- p. ej. porque esta misma
  NbS ya se aplicó antes en esta sesión -- se reutiliza su ICNUM en vez de
  duplicar el registro). El ICNUM se resuelve en este momento
  (``max(ICNUM)+1``), no al crear la NbS: plant.dat pudo haber cambiado
  entre medio.
- ``.hru`` y ``.mgt`` de cada HRU objetivo: parámetros de superficie, IGRO/
  PLANT_ID/condición inicial/CN2 (por el HYDGRP real de esa HRU, ver
  swat_io.sol_parser), el calendario de operaciones completo (se reemplaza
  entero, no se parchea -- ver guía del proyecto sección 12-13), y el texto
  "Luse:<CPNM>" de la línea de título de ambos archivos (reportado por el
  usuario, 2026-08-11: swat_io.hru.parser/swat_io.mgt.parser leen ese texto
  como ``metadata.land_use``, y scenarios.nbs_analysis lo usa para decidir
  qué HRU "tienen" una cobertura al escanear combinaciones existentes --
  dejarlo desactualizado haría que una HRU recién convertida siguiera
  apareciendo bajo su cobertura vieja en cualquier escaneo futuro).
  ``.sol`` deliberadamente NO se toca ni siquiera para esto: la guía del
  proyecto lo marca sin excepciones como archivo que un cambio de cobertura
  nunca modifica (sección 3.3), y ninguna función de escaneo de esta app
  lee el texto "Luse:" de `.sol` -- solo swat_io.sol_parser.read_hydrologic_group,
  que no depende de él.

Mismo patrón in-place ya aceptado para Wetlands/HRUs (ver CLAUDE.md, aviso
de deuda técnica bajo "Aislamiento por escenario"): escribe directo sobre
el TxtInOut del proyecto abierto. Cada HRU se escribe todo-o-nada: un
fallo puntual (HSG sin CN2 definido, validación .hru, error de E/S) se
reporta y no aborta el resto del lote -- mismo criterio que el Materialize
de HRUs y el batch de escenarios de cobertura.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from swat_io.common.atomic_write import atomic_write_bytes
from swat_io.hru.models import HRURawLine
from swat_io.hru.parser import parse_hru_file
from swat_io.mgt.models import MGTOperation, MGTRawLine
from swat_io.mgt.parser import parse_mgt_file
from swat_io.plant.models import LINE2_FIELDS, LINE3_FIELDS, LINE4_FIELDS, LINE5_FIELDS, build_plant_record
from swat_io.plant.parser import parse_plant_dat_file
from swat_io.sol_parser import read_hydrologic_group

_LUSE_TITLE_RE = re.compile(r"(Luse\s*:\s*)(\S+)", re.IGNORECASE)


def _update_luse_title(lines: list, raw_line_type: type, new_lulc: str) -> None:
    """Reemplaza el texto "Luse:<codigo>" de la línea de título/encabezado
    (nunca una línea de parámetro) por ``new_lulc``, preservando el resto
    de la línea intacta. Solo mira líneas de tipo ``raw_line_type``
    (``HRURawLine``/``MGTRawLine``): una línea de parámetro
    (``HRUParameterLine``/``MGTHeaderLine``) ignora ``original_text`` al
    renderizar (usa prefix+raw_value+suffix), así que editarla ahí no
    tendría ningún efecto -- ver models.py de cada módulo.
    """
    for line in lines:
        if not isinstance(line, raw_line_type):
            continue
        new_text, count = _LUSE_TITLE_RE.subn(lambda m: m.group(1) + new_lulc, line.original_text, count=1)
        if count:
            line.original_text = new_text
            return

from .nbs import NbSDefinition

_REQUIRED_PHYSIOLOGY_FIELDS = LINE2_FIELDS + LINE3_FIELDS + LINE4_FIELDS + LINE5_FIELDS


class NbSApplyError(Exception):
    """La NbS no se puede aplicar tal como está definida (falla antes de
    tocar ningún archivo)."""


@dataclass
class NbSApplyHRUResult:
    subbasin: int
    hru: int
    status: str  # "applied" | "error"
    message: str = ""


@dataclass
class NbSApplyReport:
    nbs_name: str
    plant_id: int | None
    cpnm: str | None
    results: list[NbSApplyHRUResult] = field(default_factory=list)

    @property
    def applied_count(self) -> int:
        return sum(1 for r in self.results if r.status == "applied")

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.results if r.status == "error")


def validate_nbs_definition(nbs: NbSDefinition, plant_dat) -> list[str]:
    """Validación de conjunto de una NbS (ver guía sección 23): lista de
    errores que impiden aplicarla. Lista vacía si está completa. Expuesta
    también para que la UI la use antes de guardar la NbS (no solo al
    aplicarla), y así avisar temprano en vez de recién al aplicar."""
    errors: list[str] = []

    if nbs.new_coverage is None:
        if plant_dat.get_record_by_cpnm(nbs.target_lulc) is None:
            errors.append(f"La cobertura objetivo '{nbs.target_lulc}' no existe en plant.dat de este proyecto.")
    else:
        if len(nbs.new_coverage.cpnm) != 4:
            errors.append("CPNM de la cobertura nueva debe tener exactamente 4 caracteres.")
        missing_phys = [n for n in _REQUIRED_PHYSIOLOGY_FIELDS if n not in nbs.new_coverage.physiology]
        if missing_phys:
            errors.append("Faltan campos de fisiología vegetal: " + ", ".join(missing_phys))

    if nbs.hru_params.get("CANMX") is None:
        errors.append("Falta CANMX (obligatorio para cualquier cambio de cobertura).")
    if nbs.hru_params.get("OV_N") is None:
        errors.append("Falta OV_N (obligatorio para cualquier cambio de cobertura).")

    igro = nbs.mgt_initial.get("IGRO")
    if igro is None:
        errors.append("Falta IGRO (obligatorio: 0 si no hay cobertura creciendo al inicio, 1 si sí).")
    elif int(igro) == 1:
        for name in ("LAI_INIT", "BIO_INIT", "PHU_PLT"):
            if nbs.mgt_initial.get(name) is None:
                errors.append(f"Falta {name} (obligatorio cuando IGRO=1).")

    if not nbs.cn2_by_hsg:
        errors.append("La NbS no define ningún valor de CN2 por grupo hidrológico de suelo.")

    return errors


def _resolve_plant_id(project_txtinout: Path, nbs: NbSDefinition, plant_dat) -> tuple[int, str]:
    if nbs.new_coverage is None:
        record = plant_dat.get_record_by_cpnm(nbs.target_lulc)
        assert record is not None  # ya validado por validate_nbs_definition
        return record.icnum, record.cpnm

    existing = plant_dat.get_record_by_cpnm(nbs.new_coverage.cpnm)
    if existing is not None:
        return existing.icnum, existing.cpnm

    new_icnum = plant_dat.next_icnum()
    record = build_plant_record(
        icnum=new_icnum,
        cpnm=nbs.new_coverage.cpnm,
        idc=nbs.new_coverage.idc,
        values=nbs.new_coverage.physiology,
    )
    plant_dat.append_record(record)
    atomic_write_bytes(project_txtinout / "plant.dat", plant_dat.render().encode(plant_dat.encoding))
    return new_icnum, record.cpnm


def _apply_to_one_hru(
    txtinout_dir: Path,
    subbasin: int,
    hru: int,
    nbs: NbSDefinition,
    plant_id: int,
) -> NbSApplyHRUResult:
    stem = f"{subbasin:05d}{hru:04d}"
    hru_path = txtinout_dir / f"{stem}.hru"
    mgt_path = txtinout_dir / f"{stem}.mgt"
    sol_path = txtinout_dir / f"{stem}.sol"

    if not hru_path.exists() or not mgt_path.exists():
        return NbSApplyHRUResult(subbasin, hru, "error", "No se encontraron los archivos .hru/.mgt de esa HRU.")

    hydgrp = read_hydrologic_group(sol_path) if sol_path.exists() else None
    cn2_value = nbs.cn2_by_hsg.get(hydgrp) if hydgrp else None
    if cn2_value is None:
        return NbSApplyHRUResult(
            subbasin, hru, "error",
            f"La NbS no define CN2 para el grupo hidrológico de suelo de esta HRU "
            f"({hydgrp or 'desconocido'}); no se escribió nada en esta HRU.",
        )

    hru_file = parse_hru_file(hru_path)
    _update_luse_title(hru_file.lines, HRURawLine, nbs.target_lulc)
    for name, value in nbs.hru_params.items():
        if value is not None and hru_file.has_parameter(name):
            hru_file.set_value(name, value)

    blocking = [issue for issue in hru_file.validate() if issue.severity == "ERROR"]
    if blocking:
        return NbSApplyHRUResult(
            subbasin, hru, "error",
            "Validación .hru falló: " + "; ".join(issue.message for issue in blocking),
        )

    mgt_file = parse_mgt_file(mgt_path)
    _update_luse_title(mgt_file.lines, MGTRawLine, nbs.target_lulc)
    mgt_file.set_header_value("IGRO", nbs.mgt_initial.get("IGRO"))
    mgt_file.set_header_value("PLANT_ID", plant_id)
    for name in ("LAI_INIT", "BIO_INIT", "PHU_PLT"):
        value = nbs.mgt_initial.get(name)
        if value is not None:
            mgt_file.set_header_value(name, value)
    mgt_file.set_header_value("CN2", cn2_value)

    new_operations = []
    for op in nbs.operations:
        fields = dict(op.fields)
        if op.mgt_op == 1:
            # La operación "plant" tiene su propio PLANT_ID (distinto del de
            # cabecera). La NbS no puede conocer el ICNUM final al crearse
            # (se resuelve recién al aplicar, ver _resolve_plant_id) --
            # se inyecta acá, sin depender de lo que haya en la NbS.
            fields["PLANT_ID"] = plant_id
        new_operations.append(
            MGTOperation(mgt_op=op.mgt_op, month=op.month, day=op.day, husc=op.husc, fields=fields, modified=True)
        )
    mgt_file.replace_operations(new_operations)

    atomic_write_bytes(hru_path, hru_file.render().encode(hru_file.encoding))
    atomic_write_bytes(mgt_path, mgt_file.render().encode(mgt_file.encoding))

    return NbSApplyHRUResult(subbasin, hru, "applied")


def apply_nbs(project_dir: str | Path, nbs: NbSDefinition, targets: list[tuple[int, int]]) -> NbSApplyReport:
    """Aplica ``nbs`` a cada ``(subbasin, hru)`` de ``targets``.

    Lanza ``NbSApplyError`` sin tocar ningún archivo si la NbS misma está
    incompleta (validación de conjunto, ver guía sección 23). Un fallo
    puntual por HRU (HSG sin CN2, validación .hru, E/S) se reporta en
    ``NbSApplyReport.results`` y no aborta el resto del lote.
    """
    txtinout_dir = Path(project_dir) / "TxtInOut"
    plant_dat = parse_plant_dat_file(txtinout_dir / "plant.dat")

    definition_errors = validate_nbs_definition(nbs, plant_dat)
    if definition_errors:
        raise NbSApplyError("La NbS no se puede aplicar: " + "; ".join(definition_errors))

    plant_id, cpnm = _resolve_plant_id(txtinout_dir, nbs, plant_dat)

    report = NbSApplyReport(nbs_name=nbs.name, plant_id=plant_id, cpnm=cpnm)
    for subbasin, hru in targets:
        try:
            result = _apply_to_one_hru(txtinout_dir, subbasin, hru, nbs, plant_id)
        except Exception as exc:  # noqa: BLE001 - se reporta y se sigue, un fallo puntual no aborta el lote
            result = NbSApplyHRUResult(subbasin, hru, "error", str(exc))
        report.results.append(result)

    return report
