"""Aplicación de una NbS por área sobre TODAS las subcuencas del proyecto a
la vez -- scenarios/nbs_area_apply.py resuelve lo mismo para una única
subcuenca; este módulo es la versión masiva, pedido explícito del usuario
(2026-08-12) para no repetir "Apply by area" subcuenca por subcuenca.

Entrada: una matriz CSV (fila = subcuenca, columnas = área NbS objetivo +
una por cobertura fuente, celda = % de esa área objetivo -- NO del área
total de la subcuenca -- que se quiere convertir desde esa cobertura).
Celda de cobertura vacía = esa cobertura no participa en esa subcuenca;
``area_ha`` vacía = esa subcuenca no participa del batch (se omite sin
error).

Decisión de diseño, revisada 2026-08-12 (pedido explícito del usuario tras
usar la v1, que solo tenía columnas de % del área total de la subcuenca):
la primera versión evitaba una columna de área separada calculando cada %
directo sobre el área total de la subcuenca -- pero eso obliga a razonar
al revés ("¿qué % de mi subcuenca es esta NbS de 50 ha que quiero
plantar?") en vez de decir el área que se quiere de una. Ahora cada fila
trae su propia columna ``area_ha`` (el área NbS objetivo de esa subcuenca,
en hectáreas) y las columnas de cobertura vuelven a ser % de ESA área
--igual que ``total_area_ha`` + ``source_allocations`` en la sección manual
de Apply by area (nbs_area_apply.plan_area_allocation) -- por eso ahora SÍ
tienen que sumar 100 (mismo criterio de validate_source_allocations, con
la misma tolerancia), a diferencia de la v1 donde alcanzaba con "≤100".
``plan_mass_area_allocation`` valida además que el área pedida se pueda
cubrir de verdad con las coberturas fuente que el usuario asignó en esa
fila -- no contra el área total de la subcuenca (que sería un límite
demasiado optimista si el usuario no asignó todas las coberturas
disponibles), sino contra ``AreaAllocationPlan.total_deficit_ha`` que ya
calcula ``plan_area_allocation`` recorriendo las HRU reales de esas
coberturas puntuales (pedido explícito del usuario, 2026-08-12, tras ver
que el mensaje de skip original solo comparaba contra el área total de la
subcuenca sin decirle qué área SÍ era alcanzable con lo que había
asignado). Si hay déficit, la subcuenca se omite (``result.skipped``) con
un mensaje que da el área máxima alcanzable, desglosada por cobertura
fuente, para que el usuario sepa exactamente a qué bajar ``area_ha`` (o
qué cobertura agregar) en vez de tener que adivinar.

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
_AREA_COLUMN = "area_ha"
_ROW_PCT_SUM_TOLERANCE = 0.5  # mismo valor que nbs_area_apply._DEFAULT_PCT_SUM_TOLERANCE
_AREA_DEFICIT_TOLERANCE = 1e-6  # mismo valor que nbs_area_apply._DEFAULT_TOLERANCE
# Valor puesto en cada celda "aplicable" del template (ver
# write_mass_allocation_template_csv) -- 0 en vez de un valor de ejemplo
# inventado, para no arriesgar que la fila sume más de 100% con varias
# coberturas fuente disponibles en la misma subcuenca; el usuario ajusta
# los valores (y el área objetivo, que queda en blanco) antes de cargarlo.
_TEMPLATE_APPLICABLE_VALUE = 0


def _is_blank(raw_value) -> bool:
    return pd.isna(raw_value) or str(raw_value).strip() == ""


@dataclass
class SubbasinAreaAllocation:
    area_ha: float
    sources: list[tuple[str, float]]


def parse_mass_allocation_csv(csv_path: str | Path) -> tuple[dict[int, SubbasinAreaAllocation], list[str]]:
    """Lee la matriz subcuenca x (área + cobertura). Devuelve (asignaciones
    válidas, errores) -- una fila con un problema puntual (área/valor no
    numérico, suma de % distinta de 100, subcuenca repetida) se reporta en
    ``errores`` y se omite del resultado, sin abortar el resto del CSV
    (mismo criterio que Batch: un fallo puntual no tumba el lote). Levanta
    ValueError solo si el CSV en sí no se puede leer o le falta la
    estructura mínima (columnas 'subbasin'/'area_ha', o ninguna columna de
    cobertura)."""
    try:
        df = pd.read_csv(csv_path, dtype=str)
    except Exception as error:
        raise ValueError(f"Could not read the file: {error}") from None

    if _SUBBASIN_COLUMN not in df.columns:
        raise ValueError(f"Missing required column '{_SUBBASIN_COLUMN}'.")
    if _AREA_COLUMN not in df.columns:
        raise ValueError(f"Missing required column '{_AREA_COLUMN}'.")
    coverage_columns = [c for c in df.columns if c not in (_SUBBASIN_COLUMN, _AREA_COLUMN)]
    if not coverage_columns:
        raise ValueError("The CSV has no coverage column besides 'subbasin'/'area_ha'.")

    allocations: dict[int, SubbasinAreaAllocation] = {}
    errors: list[str] = []
    seen: set[int] = set()

    for _, row in df.iterrows():
        raw_subbasin = row[_SUBBASIN_COLUMN]
        if _is_blank(raw_subbasin):
            continue
        try:
            subbasin = int(float(str(raw_subbasin).strip()))
        except ValueError:
            errors.append(f"'{raw_subbasin}' is not a valid subbasin number.")
            continue
        if subbasin in seen:
            errors.append(f"Subbasin {subbasin}: appears more than once in the CSV; the repeated row was ignored.")
            continue
        seen.add(subbasin)

        raw_area = row[_AREA_COLUMN]
        if _is_blank(raw_area):
            continue
        try:
            area_ha = float(raw_area)
        except ValueError:
            errors.append(f"Subbasin {subbasin}: area '{raw_area}' is not a valid number.")
            continue
        if area_ha <= 0:
            errors.append(f"Subbasin {subbasin}: the area ({_AREA_COLUMN}) must be greater than 0.")
            continue

        row_allocations: list[tuple[str, float]] = []
        row_errors: list[str] = []
        for coverage in coverage_columns:
            raw_value = row[coverage]
            if _is_blank(raw_value):
                continue
            try:
                pct = float(raw_value)
            except ValueError:
                row_errors.append(f"coverage '{coverage}': '{raw_value}' is not a number.")
                continue
            if pct <= 0:
                continue
            row_allocations.append((coverage, pct))

        if row_errors:
            errors.append(f"Subbasin {subbasin}: " + "; ".join(row_errors))
            continue

        if not row_allocations:
            errors.append(
                f"Subbasin {subbasin}: has {_AREA_COLUMN} but no source coverage with a % assigned."
            )
            continue

        total = sum(pct for _, pct in row_allocations)
        if abs(total - 100) > _ROW_PCT_SUM_TOLERANCE:
            errors.append(
                f"Subbasin {subbasin}: coverage cells add up to {total:.2f}%, they must add up to 100% of the "
                f"stated NbS area ({area_ha:.2f} ha)."
            )
            continue

        allocations[subbasin] = SubbasinAreaAllocation(area_ha=area_ha, sources=row_allocations)

    return allocations, errors


@dataclass
class MassAreaAllocationResult:
    plans: list[AreaAllocationPlan] = field(default_factory=list)
    # subcuenca -> motivo por el que se omitió (sin .sub localizable, sin
    # ninguna HRU, o un plan calculado cuyas coberturas fuente asignadas no
    # alcanzan para cubrir el area_ha pedido -- AreaAllocationPlan.total_deficit_ha
    # > 0). A diferencia de la sección manual de "Apply by area", acá un
    # déficit NO deja el plan a medio aplicar en ``plans``: la subcuenca
    # entera pasa a ``skipped`` (pedido explícito del usuario, 2026-08-12 --
    # ver docstring de plan_mass_area_allocation).
    skipped: dict[int, str] = field(default_factory=dict)

    @property
    def targets(self) -> list[tuple[int, int]]:
        return [target for plan in self.plans for target in plan.targets]


def plan_mass_area_allocation(
    project_dir: str | Path,
    allocations: dict[int, SubbasinAreaAllocation],
    *,
    slope_priority: list[str] | None = None,
    soil_priority: list[str] | None = None,
    strict: bool = True,
) -> MassAreaAllocationResult:
    """Corre plan_area_allocation por cada subcuenca de ``allocations``, sin
    ningún cambio al algoritmo de selección de HRU -- ver docstring del
    módulo. Una subcuenca sin .sub localizable o sin ninguna HRU siempre se
    omite (``result.skipped``) en vez de abortar el resto del batch.

    ``strict`` (default True, el comportamiento de siempre para "Apply by
    area (all subbasins)") además omite la subcuenca entera cuando sus
    coberturas fuente asignadas no alcanzan para cubrir el ``area_ha``
    pedido -- usa el déficit que ya calcula plan_area_allocation por
    cobertura, no una comparación contra el área total de la subcuenca,
    para poder decirle al usuario exactamente cuánta área SÍ es alcanzable
    con lo que asignó.

    ``strict=False`` (pedido explícito del usuario, 2026-08-12, para la
    serie de % de engine.nbs_area_batch_run) mantiene el plan en
    ``result.plans`` aunque tenga déficit -- aplica lo alcanzable en vez de
    omitir la subcuenca entera, porque en un batch automático el usuario
    prefiere que cada paso corra con lo que se pueda en vez de bloquearse;
    el llamador es responsable de revisar ``AreaAllocationPlan.total_deficit_ha``
    de cada plan y dejarlo documentado (log/reporte)."""
    txtinout_dir = Path(project_dir) / "TxtInOut"
    sub_by_id = {s.subbasin_id: s for s in discover_subbasins(txtinout_dir)}

    result = MassAreaAllocationResult()
    for subbasin_id, allocation in allocations.items():
        entry = sub_by_id.get(subbasin_id)
        if entry is None:
            result.skipped[subbasin_id] = "That subbasin was not found in the project (.sub/.pnd not located)."
            continue

        hru_files = load_subbasin_hru_files(txtinout_dir, subbasin_id)
        if not hru_files:
            result.skipped[subbasin_id] = "The subbasin has no HRUs."
            continue

        subbasin_area_ha = parse_sub_file(entry.sub_file, subbasin_id).area_km2 * 100
        plan = plan_area_allocation(
            subbasin_id, hru_files, subbasin_area_ha,
            total_area_ha=allocation.area_ha,
            source_allocations=allocation.sources,
            slope_priority=slope_priority,
            soil_priority=soil_priority,
        )

        if strict and plan.total_deficit_ha > _AREA_DEFICIT_TOLERANCE:
            achievable_ha = sum(source.selected_ha for source in plan.by_source)
            breakdown = "; ".join(
                f"{source.source_lulc}: {source.selected_ha:.2f} ha available" for source in plan.by_source
            )
            result.skipped[subbasin_id] = (
                f"The requested NbS area ({allocation.area_ha:.2f} ha) exceeds the area available among the "
                f"source coverages assigned for this subbasin ({achievable_ha:.2f} ha total -- "
                f"{breakdown}). Lower 'area_ha' to {achievable_ha:.2f} ha or less, or add another source "
                f"coverage with available area."
            )
            continue

        result.plans.append(plan)

    return result


def write_mass_allocation_template_csv(
    txtinout_dir: str | Path, destination: str | Path, target_lulc: str
) -> Path:
    """Escribe un CSV de ejemplo con una fila por subcuenca real del
    proyecto, una columna ``area_ha`` (en blanco -- el área NbS objetivo de
    cada subcuenca, a completar por el usuario) y una columna por cobertura
    real (metadata.land_use de sus HRU) -- mismo criterio que
    write_land_cover_batch_template_csv de Batch y "Export CSV" de HRUs:
    sin lista curada de coberturas/subcuencas, el usuario no tiene forma de
    saber de antemano qué escribir.

    ``target_lulc`` es la cobertura objetivo de la NbS que se va a aplicar
    (pedido explícito del usuario, 2026-08-11): esa cobertura nunca puede
    ser su propia fuente, así que ni siquiera aparece como columna. Cada
    celda de cobertura que sí es una fuente válida en esa subcuenca se
    puebla con un número (0, no un valor de ejemplo inventado) -- una celda
    en blanco pasa a significar únicamente "esa cobertura no existe en esa
    subcuenca", nunca "no se puede usar como fuente". Como ``area_ha``
    siempre queda en blanco en el template, ninguna fila del template
    participa hasta que el usuario complete un área -- por eso los ceros de
    cobertura no necesitan sumar 100 de entrada."""
    txtinout_dir = Path(txtinout_dir)
    scan = parse_hru_directory(txtinout_dir)

    coverages_by_subbasin: dict[int, set[str]] = {}
    all_coverages: set[str] = set()
    for hru_file in scan.files:
        metadata = hru_file.metadata
        if metadata.subbasin is None or metadata.land_use is None:
            continue
        if metadata.land_use == target_lulc:
            continue
        coverages_by_subbasin.setdefault(metadata.subbasin, set()).add(metadata.land_use)
        all_coverages.add(metadata.land_use)

    subbasins = sorted(s.subbasin_id for s in discover_subbasins(txtinout_dir))
    coverage_columns = sorted(all_coverages)

    rows = []
    for subbasin_id in subbasins:
        row = {_SUBBASIN_COLUMN: subbasin_id, _AREA_COLUMN: ""}
        available = coverages_by_subbasin.get(subbasin_id, set())
        for coverage in coverage_columns:
            row[coverage] = _TEMPLATE_APPLICABLE_VALUE if coverage in available else ""
        rows.append(row)

    df = pd.DataFrame(rows, columns=[_SUBBASIN_COLUMN, _AREA_COLUMN] + coverage_columns)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(destination, index=False)
    return destination
