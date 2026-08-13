"""Configuración pura de la aplicación de una NbS por área en serie de
porcentajes (ej. 10%, 20%, ..., 100%), pedido explícito del usuario
(2026-08-12): extensión de "Apply an NbS by area (all subbasins)"
(scenarios/nbs_mass_apply.py) con el mismo patrón de serie incremental que
ya usa Batch Scenarios para cambio de cobertura simple
(scenarios/land_cover_config.py + engine/batch_run.py), pero aplicando una
NbS completa (plant.dat/.hru/.mgt vía scenarios.nbs_apply.apply_nbs) en vez
de solo reasignar HRU_FR -- ver engine/nbs_area_batch_run.py para la
orquestación (copiar proyecto, correr SWAT, organizar salidas).

El usuario configura el área NbS "al 100%" con el mismo CSV matriz que ya
usa Apply by area (all subbasins) -- subbasin, area_ha, <coberturas>...
(scenarios.nbs_mass_apply.parse_mass_allocation_csv) -- y una serie de
porcentajes de ESA área (ej. "10,20,30,...,100"), no una columna nueva del
CSV: la matriz ya tiene una forma fija (subcuenca x cobertura) sin lugar
natural para una lista de porcentajes, así que la serie vive en un campo de
texto aparte de la UI (parse_pct_series_text), mismo separador "," que
target_pct_series de Batch.

Cada porcentaje de la serie escala area_ha de cada subcuenca
(scale_allocations) y se calcula siempre desde el proyecto de referencia,
nunca encadenado -- mismo criterio que Batch.

A diferencia de "Apply by area (all subbasins)" (que bloquea el botón
Apply si hay algún déficit, pedido explícito del usuario para forzar
corrección antes de escribir nada -- ver ui.tab_nbs._block_mass_apply_if_skipped),
acá el usuario pidió lo contrario: cada paso de la serie debe aplicar lo
que sí se pueda con las coberturas asignadas y dejarlo bien documentado en
el log y en un reporte por paso (write_area_batch_step_report_csv) -- nunca
bloquear la corrida de SWAT de ese paso por un déficit puntual. Por eso
engine.nbs_area_batch_run llama a
scenarios.nbs_mass_apply.plan_mass_area_allocation con ``strict=False``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .nbs_mass_apply import MassAreaAllocationResult, SubbasinAreaAllocation

_PCT_SEPARATOR = ","
_STEP_REPORT_FILENAME = "nbs_area_batch_report.csv"


def parse_pct_series_text(raw: str) -> list[float]:
    """Convierte "10,20,30" en [10.0, 20.0, 30.0] -- mismo criterio de rango
    (0, 100] que scenarios.land_cover_config._parse_pct_series, pero
    tomando un string de la UI en vez de una celda de CSV (acá no hay CSV
    para la serie, ver docstring del módulo). Levanta ValueError (todos los
    problemas juntos) si no hay ningún valor válido o alguno está fuera de
    rango."""
    if raw is None or not raw.strip():
        raise ValueError("The percentage series is empty.")

    tokens = [token.strip() for token in raw.split(_PCT_SEPARATOR) if token.strip() != ""]
    values: list[float] = []
    errors: list[str] = []
    for token in tokens:
        try:
            value = float(token)
        except ValueError:
            errors.append(f"'{token}' is not a number.")
            continue
        if not (0 < value <= 100):
            errors.append(f"{value} is out of range (0, 100].")
            continue
        values.append(value)

    if errors:
        raise ValueError("; ".join(errors))
    if not values:
        raise ValueError("The percentage series has no value.")
    return values


def scale_allocations(allocations: dict[int, SubbasinAreaAllocation], pct: float) -> dict[int, SubbasinAreaAllocation]:
    """Escala ``area_ha`` de cada subcuenca al ``pct``% del área NbS "al
    100%" configurada -- las coberturas fuente y sus % relativos entre sí
    no cambian, porque siguen siendo % de esa misma área ya escalada (mismo
    principio que la escritura al 100%, ver nbs_area_apply.plan_area_allocation:
    requested_ha = total_area_ha * pct_fuente/100)."""
    factor = pct / 100
    return {
        subbasin: SubbasinAreaAllocation(area_ha=allocation.area_ha * factor, sources=list(allocation.sources))
        for subbasin, allocation in allocations.items()
    }


@dataclass
class OutputOrganizeOptions:
    """Qué salidas organizar después de cada corrida de SWAT de la serie --
    pedido explícito del usuario, 2026-08-12: a diferencia de Batch
    (que siempre organiza .rch/.hru si existen, sin preguntar), acá el
    usuario quiere elegir, porque organizar output.hru puede tardar minutos
    por paso y multiplicarse por cada % de la serie. Los tres en True por
    default -- mismo comportamiento "organizar todo lo que exista" que ya
    tenía Batch, el usuario desmarca lo que no necesita."""
    rch: bool = True
    sub: bool = True
    hru: bool = True


def write_area_batch_step_report_csv(scenario_dir: str | Path, pct: float, result: MassAreaAllocationResult) -> Path:
    """Reporte de área por paso de la serie, en ``tool_outputs/`` de esa
    copia de escenario -- pedido explícito del usuario, 2026-08-12: "los
    logs y los reportes son importantes", quiere saber exactamente cuánta
    área se aplicó de verdad en cada subcuenca de cada paso, no solo si el
    paso corrió o no. Una fila por (subcuenca, cobertura fuente) con área
    pedida/aplicada/déficit -- misma granularidad que
    AreaAllocationPlan.by_source -- más una fila por subcuenca omitida (sin
    .sub localizable o sin ninguna HRU, ver
    scenarios.nbs_mass_apply.plan_mass_area_allocation) con el motivo en
    vez de un desglose de coberturas. Se llama con el resultado de
    ``plan_mass_area_allocation(..., strict=False)``, así que un déficit
    puntual queda documentado acá en vez de convertir la subcuenca en
    "omitida"."""
    rows: list[dict] = []
    for plan in result.plans:
        for source in plan.by_source:
            rows.append(
                {
                    "target_pct": pct,
                    "subbasin": plan.subbasin,
                    "source_lulc": source.source_lulc,
                    "requested_ha": round(source.requested_ha, 4),
                    "applied_ha": round(source.selected_ha, 4),
                    "deficit_ha": round(source.deficit_ha, 4),
                    "hru_count": len(source.selected_hru_ids),
                    "status": source.status,
                    "notes": "; ".join(source.notes),
                }
            )
    for subbasin_id, reason in result.skipped.items():
        rows.append(
            {
                "target_pct": pct,
                "subbasin": subbasin_id,
                "source_lulc": "",
                "requested_ha": None,
                "applied_ha": 0.0,
                "deficit_ha": None,
                "hru_count": 0,
                "status": "skipped",
                "notes": reason,
            }
        )

    columns = [
        "target_pct", "subbasin", "source_lulc", "requested_ha", "applied_ha", "deficit_ha",
        "hru_count", "status", "notes",
    ]
    df = pd.DataFrame(rows, columns=columns)
    dest = Path(scenario_dir) / "tool_outputs" / _STEP_REPORT_FILENAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest, index=False)
    return dest
