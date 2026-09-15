"""Motor de aplicación masiva de una NbS a un conjunto de HRU.

Dada una NbS ya creada (scenarios.nbs.NbSDefinition) y una lista de HRU
objetivo (subcuenca, hru), escribe:

- ``plant.dat``: en la práctica ya no ocurre acá -- desde 2026-08-11 el
  wizard llama a ``sync_new_coverage_to_plant_dat`` al guardar la NbS
  (creación o edición), así que una cobertura nueva ya está configurada en
  plant.dat antes de que exista ningún HRU objetivo. ``_resolve_plant_id``
  se queda como red de seguridad para NbS creadas antes de este cambio (o
  con la biblioteca JSON editada a mano): si ``new_coverage.icnum`` es
  None o el registro no aparece, resuelve el ICNUM ahí mismo
  (``max(ICNUM)+1`` o reutilizando un registro con el mismo CPNM).
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

**Bug real corregido 2026-09-15** (reportado por el usuario: "Could not
find the .hru/.mgt files" en subcuencas != 1): el nombre de archivo
``NNNNNMMMM.hru`` codifica la posición LOCAL de esa HRU dentro de su
subcuenca (1..cantidad de HRU de esa subcuenca), pero el "Hru:" que
``swat_io.hru.parser`` lee del HEADER (``metadata.hru``, lo que
``plan_area_allocation``/``plan_mass_area_allocation`` usan para armar
``targets``) es el número GLOBAL de esa HRU en toda la cuenca --
confirmado contra el modelo real Buffalo: la subcuenca 2 tiene archivos
``000020001..000020080`` cuyos headers dicen ``Hru:88..167``.
Reconstruir el nombre de archivo a partir de ese número (lo que hacía
``_apply_to_one_hru`` antes) solo "funcionaba" en la subcuenca 1 por
coincidencia (ahí el rango global arranca en 1, igual que el local); en
cualquier otra subcuenca apuntaba a un archivo que no existe. Verificado
contra las 55 subcuencas reales del modelo Buffalo que ninguna otra tiene
superposición entre su rango local y su rango global de header, así que
el fallo siempre fue un error limpio de "no encontrado", nunca una
escritura silenciosa sobre la HRU equivocada. ``_index_subbasin_hru_paths``
resuelve la ruta real buscando entre los archivos reales de la subcuenca
cuál tiene ese número de header, en vez de asumir que coincide con el
nombre de archivo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from scenarios.activity_log import log_action
from scenarios.hru_draft import list_subbasin_hru_files
from scenarios.nbs_analysis import discover_non_plant_land_uses
from swat_io.common.atomic_write import atomic_write_bytes
from swat_io.discovery import discover_subbasins
from swat_io.hru.models import HRURawLine
from swat_io.hru.parser import parse_hru_file
from swat_io.mgt.models import MGTOperation, MGTRawLine
from swat_io.mgt.parser import parse_mgt_file
from swat_io.plant.models import LINE2_FIELDS, LINE3_FIELDS, LINE4_FIELDS, LINE5_FIELDS, build_plant_record
from swat_io.plant.parser import parse_plant_dat_file
from swat_io.sol_parser import read_hydrologic_group
from swat_io.sub_parser import parse_sub_file
from swat_io.tool_outputs import tool_outputs_dir

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
    # HRU_FR (fracción del área de la subcuenca que ocupa esta HRU, no de
    # la cuenca completa) tal como estaba en el .hru al momento de aplicar
    # -- la NbS nunca la modifica (solo cambia cobertura/manejo, no área),
    # así que es el mismo valor antes y después. None si el .hru no llegó
    # a parsearse (ej. archivo no encontrado).
    hru_fr: float | None = None


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


def validate_nbs_definition(nbs: NbSDefinition, plant_dat, real_land_uses: set[str] | None = None) -> list[str]:
    """Validación de conjunto de una NbS (ver guía sección 23): lista de
    errores que impiden aplicarla. Lista vacía si está completa. Expuesta
    también para que la UI la use antes de guardar la NbS (no solo al
    aplicarla), y así avisar temprano en vez de recién al aplicar.

    ``real_land_uses`` (2026-09-15, ver
    scenarios.nbs_analysis.discover_non_plant_land_uses): coberturas reales
    del proyecto que no están en plant.dat -- típicamente urbanas
    (URBN/URLD/URMD/URHD). Un target "existing" ahí es válido, pero como no
    tiene registro en plant.dat, su PLANT_ID/IURBAN/URBLU no se pueden
    resolver por CPNM (ver _resolve_plant_id): deben venir completos de
    ``mgt_initial``, poblado por el paso "Copy from existing" del wizard
    contra una HRU real de ese tipo -- nunca inventados."""
    errors: list[str] = []

    if nbs.new_coverage is None:
        if plant_dat.get_record_by_cpnm(nbs.target_lulc) is None:
            if not (real_land_uses and nbs.target_lulc in real_land_uses):
                errors.append(f"Target coverage '{nbs.target_lulc}' does not exist in this project's plant.dat.")
            else:
                for name in ("PLANT_ID", "IURBAN", "URBLU"):
                    if nbs.mgt_initial.get(name) is None:
                        errors.append(
                            f"Missing {name} (required for a non-vegetal target coverage like "
                            f"'{nbs.target_lulc}' -- use \"Copy from existing\" to pull it from a real HRU "
                            "of that type)."
                        )
    else:
        if len(nbs.new_coverage.cpnm) != 4:
            errors.append("The new coverage's CPNM must be exactly 4 characters.")
        missing_phys = [n for n in _REQUIRED_PHYSIOLOGY_FIELDS if n not in nbs.new_coverage.physiology]
        if missing_phys:
            errors.append("Missing plant physiology fields: " + ", ".join(missing_phys))

    if nbs.hru_params.get("CANMX") is None:
        errors.append("Missing CANMX (required for any coverage change).")
    if nbs.hru_params.get("OV_N") is None:
        errors.append("Missing OV_N (required for any coverage change).")

    igro = nbs.mgt_initial.get("IGRO")
    if igro is None:
        errors.append("Missing IGRO (required: 0 if no coverage is growing at the start, 1 if there is).")
    elif int(igro) == 1:
        for name in ("LAI_INIT", "BIO_INIT", "PHU_PLT"):
            if nbs.mgt_initial.get(name) is None:
                errors.append(f"Missing {name} (required when IGRO=1).")

    if not nbs.cn2_by_hsg:
        errors.append("The NbS does not define any CN2 value by soil hydrologic group.")

    return errors


def sync_new_coverage_to_plant_dat(project_dir: str | Path, nbs: NbSDefinition) -> NbSDefinition:
    """Crea o actualiza en plant.dat el registro de ``nbs.new_coverage``,
    de inmediato al guardar la NbS desde el wizard -- pedido explícito del
    usuario, 2026-08-11: antes esto se resolvía recién al aplicar (ver
    ``_resolve_plant_id``); ahora una cobertura nueva queda configurada en
    plant.dat tan pronto la NbS se guarda, sin esperar a que se aplique a
    ninguna HRU. No-op si ``nbs.new_coverage`` es None (cobertura
    existente, nada que sincronizar).

    Reencuentra el registro por ICNUM (``nbs.new_coverage.icnum``) cuando
    ya se sincronizó antes -- así una edición que renombra el CPNM sigue
    actualizando el mismo registro en vez de crear uno nuevo. Si el ICNUM
    todavía es None (primera vez) pero el CPNM ya existe en plant.dat
    (otra NbS, u otro proceso, ya lo creó), se adopta ese registro en vez
    de duplicarlo -- mismo criterio que ya tenía ``_resolve_plant_id`` para
    el flujo de aplicar. Devuelve ``nbs`` con ``new_coverage.icnum``
    poblado; lanza ``NbSApplyError`` sin escribir nada si el CPNM pedido ya
    pertenece a otro registro distinto del propio.
    """
    if nbs.new_coverage is None:
        return nbs

    txtinout_dir = Path(project_dir) / "TxtInOut"
    plant_dat = parse_plant_dat_file(txtinout_dir / "plant.dat")
    coverage = nbs.new_coverage

    record = plant_dat.get_record(coverage.icnum) if coverage.icnum is not None else None

    if record is None:
        by_cpnm = plant_dat.get_record_by_cpnm(coverage.cpnm)
        if by_cpnm is not None:
            record = by_cpnm
        else:
            new_icnum = plant_dat.next_icnum()
            record = build_plant_record(
                icnum=new_icnum, cpnm=coverage.cpnm, idc=coverage.idc, values=coverage.physiology,
            )
            plant_dat.append_record(record)
            atomic_write_bytes(txtinout_dir / "plant.dat", plant_dat.render().encode(plant_dat.encoding))
            coverage.icnum = record.icnum
            log_action(project_dir, "NBS", f"Created plant.dat record for new coverage '{coverage.cpnm}' (ICNUM={record.icnum}).")
            return nbs

    conflicting = plant_dat.get_record_by_cpnm(coverage.cpnm)
    if conflicting is not None and conflicting.icnum != record.icnum:
        raise NbSApplyError(
            f"Could not sync plant.dat: code '{coverage.cpnm}' already belongs to another record "
            f"(ICNUM={conflicting.icnum})."
        )

    record.set("CPNM", coverage.cpnm.upper())
    record.set("IDC", coverage.idc)
    for name, value in coverage.physiology.items():
        record.set(name, value)
    atomic_write_bytes(txtinout_dir / "plant.dat", plant_dat.render().encode(plant_dat.encoding))
    coverage.icnum = record.icnum
    log_action(project_dir, "NBS", f"Updated plant.dat record for coverage '{coverage.cpnm}' (ICNUM={record.icnum}).")
    return nbs


def _resolve_plant_id(project_txtinout: Path, nbs: NbSDefinition, plant_dat) -> tuple[int, str]:
    if nbs.new_coverage is None:
        record = plant_dat.get_record_by_cpnm(nbs.target_lulc)
        if record is not None:
            return record.icnum, record.cpnm
        # Cobertura real sin registro en plant.dat (ej. urbana) -- ya
        # validado por validate_nbs_definition que mgt_initial trae
        # PLANT_ID (además de IURBAN/URBLU, escritos en _apply_to_one_hru):
        # no hay CPNM que resolver, target_lulc ya es la etiqueta final.
        return int(nbs.mgt_initial["PLANT_ID"]), nbs.target_lulc

    # Camino normal desde 2026-08-11: el wizard ya sincronizó plant.dat al
    # guardar la NbS (ver sync_new_coverage_to_plant_dat), así que el ICNUM
    # ya está resuelto -- solo confirmar que el registro sigue existiendo.
    if nbs.new_coverage.icnum is not None:
        record = plant_dat.get_record(nbs.new_coverage.icnum)
        if record is not None:
            return record.icnum, record.cpnm

    # Recuperación / compatibilidad con NbS creadas antes de este cambio
    # (icnum nunca sincronizado, o el registro desapareció de plant.dat).
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


def _index_subbasin_hru_paths(txtinout_dir: Path, subbasin: int) -> dict[int, Path]:
    """{Hru real del header: ruta .hru real} para toda una subcuenca.

    El sufijo numérico del NOMBRE de archivo (``NNNNNMMMM.hru``) es la
    posición LOCAL de esa HRU dentro de la subcuenca (1..cantidad de HRU de
    esa subcuenca); el "Hru:" del HEADER (``hru_file.metadata.hru``, lo que
    ``plan_area_allocation``/``plan_mass_area_allocation`` usan para armar
    ``targets``) es en cambio el número GLOBAL de esa HRU en toda la cuenca
    -- confirmado contra un modelo real (Buffalo, 2026-09-15): la
    subcuenca 2 tiene archivos ``000020001..000020080`` cuyos headers dicen
    ``Hru:88..167``. Reconstruir el nombre de archivo a partir del número
    de header (lo que hacía esta función antes) solo funciona por
    coincidencia en la subcuenca 1 (ahí el rango global empieza en 1, igual
    que el local) -- en cualquier otra subcuenca apunta a un archivo que no
    existe. Esta función resuelve la ruta real buscando, entre los
    archivos reales de esa subcuenca, cuál tiene ese número en su header."""
    index: dict[int, Path] = {}
    for path in list_subbasin_hru_files(txtinout_dir, subbasin):
        hru_file = parse_hru_file(path)
        if hru_file.metadata.hru is not None:
            index[hru_file.metadata.hru] = path
    return index


def _apply_to_one_hru(
    hru_path: Path,
    subbasin: int,
    hru: int,
    nbs: NbSDefinition,
    plant_id: int,
) -> NbSApplyHRUResult:
    mgt_path = hru_path.with_suffix(".mgt")
    sol_path = hru_path.with_suffix(".sol")

    if not hru_path.exists() or not mgt_path.exists():
        return NbSApplyHRUResult(subbasin, hru, "error", "Could not find the .hru/.mgt files for that HRU.")

    # HRU_FR se lee del .hru real antes de cualquier cambio -- la NbS nunca
    # la modifica (solo CANMX/OV_N/RSDIN, nunca el área), así que capturarla
    # acá ya es el valor final para el reporte, se aplique o no el resto.
    hru_file = parse_hru_file(hru_path)
    hru_fr = hru_file.get_value("HRU_FR")

    hydgrp = read_hydrologic_group(sol_path) if sol_path.exists() else None
    cn2_value = nbs.cn2_by_hsg.get(hydgrp) if hydgrp else None
    if cn2_value is None:
        return NbSApplyHRUResult(
            subbasin, hru, "error",
            f"The NbS does not define CN2 for this HRU's soil hydrologic group "
            f"({hydgrp or 'unknown'}); nothing was written to this HRU.",
            hru_fr=hru_fr,
        )

    _update_luse_title(hru_file.lines, HRURawLine, nbs.target_lulc)
    for name, value in nbs.hru_params.items():
        if value is not None and hru_file.has_parameter(name):
            hru_file.set_value(name, value)

    blocking = [issue for issue in hru_file.validate() if issue.severity == "ERROR"]
    if blocking:
        return NbSApplyHRUResult(
            subbasin, hru, "error",
            ".hru validation failed: " + "; ".join(issue.message for issue in blocking),
            hru_fr=hru_fr,
        )

    mgt_file = parse_mgt_file(mgt_path)
    _update_luse_title(mgt_file.lines, MGTRawLine, nbs.target_lulc)
    mgt_file.set_header_value("IGRO", nbs.mgt_initial.get("IGRO"))
    mgt_file.set_header_value("PLANT_ID", plant_id)
    for name in ("LAI_INIT", "BIO_INIT", "PHU_PLT"):
        value = nbs.mgt_initial.get(name)
        if value is not None:
            mgt_file.set_header_value(name, value)
    # IURBAN/URBLU (2026-09-15): solo presentes en mgt_initial para un
    # target no vegetal (ej. urbano, ver validate_nbs_definition) --
    # ausentes en cualquier NbS vegetal normal, así que este bloque no
    # cambia el comportamiento existente.
    for name in ("IURBAN", "URBLU"):
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

    return NbSApplyHRUResult(subbasin, hru, "applied", hru_fr=hru_fr)


def apply_nbs(
    project_dir: str | Path,
    nbs: NbSDefinition,
    targets: list[tuple[int, int]],
    *,
    on_hru_result: Callable[[NbSApplyHRUResult], None] | None = None,
) -> NbSApplyReport:
    """Aplica ``nbs`` a cada ``(subbasin, hru)`` de ``targets``.

    Lanza ``NbSApplyError`` sin tocar ningún archivo si la NbS misma está
    incompleta (validación de conjunto, ver guía sección 23). Un fallo
    puntual por HRU (HSG sin CN2, validación .hru, E/S) se reporta en
    ``NbSApplyReport.results`` y no aborta el resto del lote.

    ``on_hru_result``, si se da, se invoca justo después de procesar cada
    HRU (con el mismo ``NbSApplyHRUResult`` que queda en
    ``report.results``) -- pedido explícito del usuario, 2026-08-14: quería
    ver el detalle de cada HRU reflejado en el log mientras la aplicación
    corre, no solo al terminar. Sin formateo de texto acá (eso es capa de
    UI, ver ui/tab_nbs.py) para no mezclar mensajes traducibles en un
    módulo de scenarios/ sin dependencias de UI.
    """
    txtinout_dir = Path(project_dir) / "TxtInOut"
    plant_dat = parse_plant_dat_file(txtinout_dir / "plant.dat")

    real_land_uses = set(discover_non_plant_land_uses(txtinout_dir, plant_dat))
    definition_errors = validate_nbs_definition(nbs, plant_dat, real_land_uses)
    if definition_errors:
        raise NbSApplyError("The NbS cannot be applied: " + "; ".join(definition_errors))

    plant_id, cpnm = _resolve_plant_id(txtinout_dir, nbs, plant_dat)

    report = NbSApplyReport(nbs_name=nbs.name, plant_id=plant_id, cpnm=cpnm)
    # Índice de rutas reales por subcuenca, construido una sola vez por
    # subcuenca (no por target) -- ver _index_subbasin_hru_paths sobre por
    # qué no se puede reconstruir el nombre de archivo desde (subbasin, hru).
    hru_paths_by_subbasin: dict[int, dict[int, Path]] = {}
    for subbasin, hru in targets:
        try:
            index = hru_paths_by_subbasin.setdefault(subbasin, _index_subbasin_hru_paths(txtinout_dir, subbasin))
            hru_path = index.get(hru)
            if hru_path is None:
                result = NbSApplyHRUResult(subbasin, hru, "error", "Could not find the .hru/.mgt files for that HRU.")
            else:
                result = _apply_to_one_hru(hru_path, subbasin, hru, nbs, plant_id)
        except Exception as exc:  # noqa: BLE001 - se reporta y se sigue, un fallo puntual no aborta el lote
            result = NbSApplyHRUResult(subbasin, hru, "error", str(exc))
        report.results.append(result)
        if on_hru_result is not None:
            on_hru_result(result)

    log_action(
        project_dir,
        "NBS_APPLY",
        f"Applied NbS '{nbs.name}' (cpnm={cpnm}): {report.applied_count}/{len(targets)} HRU(s) applied, "
        f"{report.error_count} error(s).",
    )

    return report


_APPLY_REPORT_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _subbasin_area_ha_by_id(txtinout_dir: Path, subbasin_ids: set[int]) -> dict[int, float | None]:
    """Área real (ha) de cada subcuenca en ``subbasin_ids``, leída de su
    .sub (SUB_KM * 100 -- mismo cálculo que scenarios.nbs_area_apply). None
    para una subcuenca sin .sub localizable o que no pudo parsearse, en vez
    de abortar el reporte entero por una subcuenca puntual.

    ``discover_subbasins`` escanea *todo* el TxtInOut y lanza si encuentra
    un .sub sin su .pnd correspondiente (ver swat_io.discovery) -- un
    problema en una subcuenca ajena a esta aplicación no debe tumbar la
    generación del reporte de auditoría después de que ya se escribió todo
    en disco, así que ese fallo también degrada a "área desconocida" en vez
    de propagar la excepción."""
    if not subbasin_ids:
        return {}
    try:
        entries = {s.subbasin_id: s for s in discover_subbasins(txtinout_dir) if s.subbasin_id in subbasin_ids}
    except Exception:  # noqa: BLE001 - reporte de auditoría no debe fallar por un .pnd/.sub ajeno
        return {subbasin_id: None for subbasin_id in subbasin_ids}
    areas: dict[int, float | None] = {}
    for subbasin_id in subbasin_ids:
        entry = entries.get(subbasin_id)
        if entry is None:
            areas[subbasin_id] = None
            continue
        try:
            areas[subbasin_id] = parse_sub_file(entry.sub_file, subbasin_id).area_km2 * 100
        except Exception:  # noqa: BLE001 - un .sub puntual roto no debe tumbar el reporte
            areas[subbasin_id] = None
    return areas


def write_apply_report_csv(project_dir: str | Path, report: NbSApplyReport, applied_at: datetime) -> Path:
    """Escribe un CSV en tool_outputs/ con una fila por HRU objetivo de esta
    aplicación (subbasin, hru, status, hru_fr, hru_area_ha, message) --
    pedido explícito del usuario, 2026-08-12: quería un reporte auditable
    de qué HRU cambió cada aplicación de una NbS, qué fracción de su
    subcuenca (HRU_FR) representaba cada una en ese momento, y el área
    equivalente en hectáreas. hru_area_ha = hru_fr * área real de esa
    subcuenca (de su .sub, SUB_KM*100 -- nunca un valor inventado); queda
    en blanco si hru_fr es None (HRU cuyo .hru no llegó a parsearse) o si
    no se pudo leer el .sub de esa subcuenca. Los targets pueden abarcar
    más de una subcuenca (Apply manual no resetea la selección al cambiar
    de subcuenca), así que el área se resuelve una vez por subcuenca única,
    no por fila. Incluye también las HRU que fallaron (status="error"), con
    hru_fr/hru_area_ha si el .hru llegó a parsearse antes del fallo -- así
    el CSV documenta el intento completo, no solo lo aplicado. Un nombre de
    archivo con timestamp evita pisar el reporte de una aplicación anterior
    de la misma NbS."""
    txtinout_dir = Path(project_dir) / "TxtInOut"
    subbasin_ids = {r.subbasin for r in report.results}
    area_by_subbasin = _subbasin_area_ha_by_id(txtinout_dir, subbasin_ids)

    rows = []
    for r in report.results:
        subbasin_area_ha = area_by_subbasin.get(r.subbasin)
        hru_area_ha = r.hru_fr * subbasin_area_ha if r.hru_fr is not None and subbasin_area_ha is not None else None
        rows.append(
            {
                "subbasin": r.subbasin,
                "hru": r.hru,
                "status": r.status,
                "hru_fr": r.hru_fr,
                "hru_area_ha": hru_area_ha,
                "message": r.message,
            }
        )
    df = pd.DataFrame(rows, columns=["subbasin", "hru", "status", "hru_fr", "hru_area_ha", "message"])

    safe_name = _APPLY_REPORT_NAME_RE.sub("_", report.nbs_name).strip("_") or "nbs"
    timestamp = applied_at.strftime("%Y%m%d_%H%M%S")
    csv_path = tool_outputs_dir(project_dir) / f"nbs_apply_report_{safe_name}_{timestamp}.csv"
    df.to_csv(csv_path, index=False)
    return csv_path
