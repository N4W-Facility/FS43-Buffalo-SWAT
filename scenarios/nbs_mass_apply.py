"""Aplicación de una NbS por área sobre TODAS las subcuencas del proyecto a
la vez -- scenarios/nbs_area_apply.py resuelve lo mismo para una única
subcuenca; este módulo es la versión masiva, pedido explícito del usuario
(2026-08-12) para no repetir "Apply by area" subcuenca por subcuenca.

Entrada: una matriz CSV (fila = subcuenca, columna = cobertura fuente,
celda = % del área de esa subcuenca que se quiere convertir desde esa
cobertura). Celda vacía = esa cobertura no participa en esa subcuenca; fila
sin ninguna celda no vacía = esa subcuenca no participa del batch (se omite
sin error).

Decisión de diseño clave, distinta de la sección manual de Apply by area:
acá no hay un campo "área total a convertir" separado -- cada celda ya es,
directamente, el % del área TOTAL de esa subcuenca (no de un subtotal
arbitrario elegido a mano) que se toma de esa cobertura. Por eso las celdas
de una fila NO tienen que sumar exactamente 100 (validate_source_allocations
de nbs_area_apply, que exige ==100, no aplica acá): pueden sumar menos (el
resto de la subcuenca queda sin tocar) pero nunca más de 100 (no se puede
tomar más área de la que tiene la subcuenca). Esto deja reutilizar
scenarios.nbs_area_apply.plan_area_allocation sin ningún cambio, pasando
``total_area_ha=subbasin_area_ha`` (el área real de esa subcuenca, de su
.sub) y las celdas de la fila tal cual como ``source_allocations``.

Prioridad de pendiente/suelo: una sola configuración global para todo el
batch (mismo criterio que ``donor_priority`` en scenarios.land_cover_config
para Batch Scenarios), no una columna por subcuenca -- evita una matriz
todavía más ancha sin un caso de uso real detrás. Se arma en la UI con
``scenarios.nbs_area_apply.parse_priority_text``, igual que la sección
manual.

Una sola NbS objetivo para todo el batch (elegida en la UI, no en el CSV):
los planes de todas las subcuencas se calculan por separado pero se aplican
en un único llamado a ``scenarios.nbs_apply.apply_nbs`` con los targets de
todas juntas -- esa función ya soporta targets de más de una subcuenca (ver
su docstring de write_apply_report_csv) y ya es todo-o-nada por HRU, así que
no hace falta ninguna orquestación nueva del lado de escritura.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from swat_io.discovery import discover_subbasins
from swat_io.hru.scanner import parse_hru_directory
from swat_io.sub_parser import parse_sub_file

from .hru_draft import load_subbasin_hru_files
from .nbs_area_apply import AreaAllocationPlan, plan_area_allocation

_SUBBASIN_COLUMN = "subbasin"
_ROW_PCT_SUM_TOLERANCE = 0.5  # mismo valor que nbs_area_apply._DEFAULT_PCT_SUM_TOLERANCE
_TEMPLATE_SAMPLE_PCT = 10.0


def _is_blank(raw_value) -> bool:
    return pd.isna(raw_value) or str(raw_value).strip() == ""


def parse_mass_allocation_csv(csv_path: str | Path) -> tuple[dict[int, list[tuple[str, float]]], list[str]]:
    """Lee la matriz subcuenca x cobertura. Devuelve (asignaciones válidas,
    errores) -- una fila con un problema puntual (valor no numérico, suma
    > 100, subcuenca repetida) se reporta en ``errores`` y se omite del
    resultado, sin abortar el resto del CSV (mismo criterio que Batch: un
    fallo puntual no tumba el lote). Levanta ValueError solo si el CSV en sí
    no se puede leer o le falta la estructura mínima (columna 'subbasin' o
    ninguna columna de cobertura)."""
    try:
        df = pd.read_csv(csv_path, dtype=str)
    except Exception as error:
        raise ValueError(f"No se pudo leer el archivo: {error}") from None

    if _SUBBASIN_COLUMN not in df.columns:
        raise ValueError(f"Falta la columna requerida '{_SUBBASIN_COLUMN}'.")
    coverage_columns = [c for c in df.columns if c != _SUBBASIN_COLUMN]
    if not coverage_columns:
        raise ValueError("El CSV no tiene ninguna columna de cobertura además de 'subbasin'.")

    allocations: dict[int, list[tuple[str, float]]] = {}
    errors: list[str] = []
    seen: set[int] = set()

    for _, row in df.iterrows():
        raw_subbasin = row[_SUBBASIN_COLUMN]
        if _is_blank(raw_subbasin):
            continue
        try:
            subbasin = int(float(str(raw_subbasin).strip()))
        except ValueError:
            errors.append(f"'{raw_subbasin}' no es un número de subcuenca válido.")
            continue
        if subbasin in seen:
            errors.append(f"Subcuenca {subbasin}: aparece más de una vez en el CSV; se ignoró la fila repetida.")
            continue
        seen.add(subbasin)

        row_allocations: list[tuple[str, float]] = []
        row_errors: list[str] = []
        for coverage in coverage_columns:
            raw_value = row[coverage]
            if _is_blank(raw_value):
                continue
            try:
                pct = float(raw_value)
            except ValueError:
                row_errors.append(f"cobertura '{coverage}': '{raw_value}' no es un número.")
                continue
            if pct <= 0:
                continue
            row_allocations.append((coverage, pct))

        if row_errors:
            errors.append(f"Subcuenca {subbasin}: " + "; ".join(row_errors))
            continue

        if not row_allocations:
            continue

        total = sum(pct for _, pct in row_allocations)
        if total - 100 > _ROW_PCT_SUM_TOLERANCE:
            errors.append(
                f"Subcuenca {subbasin}: las celdas suman {total:.2f}%, más del 100% del área de la subcuenca."
            )
            continue

        allocations[subbasin] = row_allocations

    return allocations, errors


@dataclass
class MassAreaAllocationResult:
    plans: list[AreaAllocationPlan] = field(default_factory=list)
    # subcuenca -> motivo por el que no se pudo calcular ningún plan (sin
    # .sub localizable, o sin ninguna HRU) -- distinto de un déficit dentro
    # de un plan ya calculado (ver AreaAllocationPlan.total_deficit_ha).
    skipped: dict[int, str] = field(default_factory=dict)

    @property
    def targets(self) -> list[tuple[int, int]]:
        return [target for plan in self.plans for target in plan.targets]


def plan_mass_area_allocation(
    project_dir: str | Path,
    allocations: dict[int, list[tuple[str, float]]],
    *,
    slope_priority: list[str] | None = None,
    soil_priority: list[str] | None = None,
) -> MassAreaAllocationResult:
    """Corre plan_area_allocation por cada subcuenca de ``allocations``, sin
    ningún cambio al algoritmo de selección de HRU -- ver docstring del
    módulo. Una subcuenca sin .sub localizable o sin ninguna HRU se omite
    (``result.skipped``) en vez de abortar el resto del batch."""
    txtinout_dir = Path(project_dir) / "TxtInOut"
    sub_by_id = {s.subbasin_id: s for s in discover_subbasins(txtinout_dir)}

    result = MassAreaAllocationResult()
    for subbasin_id, source_allocations in allocations.items():
        entry = sub_by_id.get(subbasin_id)
        if entry is None:
            result.skipped[subbasin_id] = "No se encontró esa subcuenca en el proyecto (.sub/.pnd no localizado)."
            continue

        hru_files = load_subbasin_hru_files(txtinout_dir, subbasin_id)
        if not hru_files:
            result.skipped[subbasin_id] = "La subcuenca no tiene ninguna HRU."
            continue

        subbasin_area_ha = parse_sub_file(entry.sub_file, subbasin_id).area_km2 * 100
        plan = plan_area_allocation(
            subbasin_id, hru_files, subbasin_area_ha,
            total_area_ha=subbasin_area_ha,
            source_allocations=source_allocations,
            slope_priority=slope_priority,
            soil_priority=soil_priority,
        )
        result.plans.append(plan)

    return result


def write_mass_allocation_template_csv(txtinout_dir: str | Path, destination: str | Path) -> Path:
    """Escribe un CSV de ejemplo con una fila por subcuenca real del
    proyecto y una columna por cobertura real (metadata.land_use de sus
    HRU) -- mismo criterio que write_land_cover_batch_template_csv de Batch
    y "Export CSV" de HRUs: sin lista curada de coberturas/subcuencas, el
    usuario no tiene forma de saber de antemano qué escribir. Puebla, a modo
    de ejemplo, la primera cobertura de cada subcuenca con
    _TEMPLATE_SAMPLE_PCT -- el resto de las celdas queda en blanco, listo
    para completar."""
    txtinout_dir = Path(txtinout_dir)
    scan = parse_hru_directory(txtinout_dir)

    coverages_by_subbasin: dict[int, set[str]] = {}
    all_coverages: set[str] = set()
    for hru_file in scan.files:
        metadata = hru_file.metadata
        if metadata.subbasin is None or metadata.land_use is None:
            continue
        coverages_by_subbasin.setdefault(metadata.subbasin, set()).add(metadata.land_use)
        all_coverages.add(metadata.land_use)

    subbasins = sorted(s.subbasin_id for s in discover_subbasins(txtinout_dir))
    coverage_columns = sorted(all_coverages)

    rows = []
    for subbasin_id in subbasins:
        row = {_SUBBASIN_COLUMN: subbasin_id}
        available = sorted(coverages_by_subbasin.get(subbasin_id, set()))
        for coverage in coverage_columns:
            row[coverage] = _TEMPLATE_SAMPLE_PCT if available and coverage == available[0] else ""
        rows.append(row)

    df = pd.DataFrame(rows, columns=[_SUBBASIN_COLUMN] + coverage_columns)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(destination, index=False)
    return destination
