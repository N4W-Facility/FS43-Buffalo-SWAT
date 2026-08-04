"""Algoritmo puro de reasignación de área entre HRU de una subcuenca, para
escenarios de cambio de cobertura (batch) del tipo "aumentar bosque a X%".

Acordado con el usuario (2026-08-03): el porcentaje objetivo es relativo al
área total de la subcuenca (no al área de la propia HRU), y se evalúa
subcuenca por subcuenca de forma independiente. Reglas:

- Único parámetro que se toca: ``HRU_FR``. Nunca se modifica ningún otro
  parámetro de la HRU, para no afectar la calibración.
- Si una subcuenca no tiene ninguna HRU con la cobertura objetivo, se
  omite: crear una HRU nueva implicaría definir manejo/vegetación desde
  cero (fuera de alcance, equivalente a recalibrar).
- Si el % actual de la cobertura objetivo ya es >= el % pedido, también se
  omite: forzar una reducción sería deforestar, no reforestar, y no tiene
  sentido para este caso de uso.
- El área que se quita a las coberturas donantes sigue una prioridad en
  cascada configurable: cobertura (obligatoria) > pendiente (opcional) >
  suelo (opcional). Sin un nivel de prioridad dado, ese nivel no
  desempata (todo empata ahí) y el reparto en ese nivel es proporcional al
  peso actual. Coberturas/pendientes/suelos que no aparecen en la lista de
  prioridad de su nivel quedan en el último grupo de ese nivel (empatan
  entre sí, después de todos los nombrados).
- El área que se agrega a la cobertura objetivo sigue la misma cascada de
  pendiente/suelo (no hay nivel de cobertura, ya está fija en el target).
  A diferencia de los donantes, el crecimiento no tiene un tope natural
  por grupo (no hay "hasta agotar"), así que toda el área nueva va al
  primer grupo no vacío en orden de prioridad, repartida proporcional al
  peso actual dentro de ese grupo. Sin prioridad, el único grupo es "todas
  las HRU de la cobertura objetivo" y el reparto es proporcional entre
  todas.

Este módulo no toca disco ni muta los ``HRUFile`` recibidos: solo lee
``HRU_FR`` y metadata, y devuelve un plan de valores nuevos. Aplicarlo de
verdad (escribir los .hru reales de la copia de escenario) es
responsabilidad de la orquestación del batch, vía
``scenarios.hru_draft.write_hru_values``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from swat_io.hru.models import HRUFile

_DEFAULT_TOLERANCE = 1e-6

STATUS_APPLIED = "applied"
STATUS_SKIPPED_NO_TARGET_HRU = "skipped_no_target_hru"
STATUS_SKIPPED_TARGET_ALREADY_MET = "skipped_target_already_met"


@dataclass
class SubbasinReallocationResult:
    subbasin: int
    status: str
    current_target_pct: float
    new_hru_fr: dict[int, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _hru_fr(hru_files: dict[int, HRUFile], hru_id: int) -> float:
    return float(hru_files[hru_id].get_value("HRU_FR", default=0.0) or 0.0)


def _priority_index(value: str | None, priority: list[str] | None) -> int:
    """Índice de orden de ``value`` dentro de ``priority``.

    ``priority`` en None significa que ese nivel no se usa (todo empata en
    0). Un valor que no aparece en una lista sí dada queda al final
    (empata con los demás no listados, después de todos los nombrados)."""
    if priority is None:
        return 0
    if value in priority:
        return priority.index(value)
    return len(priority)


def _sorted_groups(
    hru_ids: list[int],
    hru_files: dict[int, HRUFile],
    *,
    land_use_priority: list[str] | None,
    slope_priority: list[str] | None,
    soil_priority: list[str] | None,
) -> list[list[int]]:
    """Agrupa ``hru_ids`` por (índice cobertura, índice pendiente, índice
    suelo) y devuelve los grupos ordenados de mayor a menor prioridad. Las
    HRU con la misma clave completa quedan en el mismo grupo (empatan,
    se reparten proporcionalmente entre sí)."""
    keyed: dict[tuple[int, int, int], list[int]] = {}
    for hru_id in hru_ids:
        metadata = hru_files[hru_id].metadata
        key = (
            _priority_index(metadata.land_use, land_use_priority),
            _priority_index(metadata.slope_class, slope_priority),
            _priority_index(metadata.soil, soil_priority),
        )
        keyed.setdefault(key, []).append(hru_id)
    return [keyed[key] for key in sorted(keyed)]


def plan_subbasin_reallocation(
    subbasin: int,
    hru_files: dict[int, HRUFile],
    *,
    target_lulc: str,
    target_pct: float,
    donor_priority: list[str],
    slope_priority: list[str] | None = None,
    soil_priority: list[str] | None = None,
    tolerance: float = _DEFAULT_TOLERANCE,
) -> SubbasinReallocationResult:
    """Calcula el plan de reasignación de ``HRU_FR`` para una subcuenca.

    ``target_pct`` es un porcentaje (0-100) del área total de la
    subcuenca. Devuelve un plan ``{hru_id: nuevo_HRU_FR}`` con solo las HRU
    cuyo valor cambia; nunca escribe ni muta ``hru_files``.
    """
    target_ids = [hid for hid, f in hru_files.items() if f.metadata.land_use == target_lulc]
    current_target_fraction = sum(_hru_fr(hru_files, hid) for hid in target_ids)
    current_target_pct = current_target_fraction * 100

    if not target_ids:
        return SubbasinReallocationResult(
            subbasin=subbasin,
            status=STATUS_SKIPPED_NO_TARGET_HRU,
            current_target_pct=current_target_pct,
            notes=[f"Subcuenca {subbasin}: no tiene ninguna HRU con cobertura '{target_lulc}'."],
        )

    target_fraction = target_pct / 100
    if current_target_fraction >= target_fraction - tolerance:
        return SubbasinReallocationResult(
            subbasin=subbasin,
            status=STATUS_SKIPPED_TARGET_ALREADY_MET,
            current_target_pct=current_target_pct,
            notes=[
                f"Subcuenca {subbasin}: '{target_lulc}' ya ocupa {current_target_pct:.2f}% "
                f"(>= {target_pct:.2f}% pedido); no se fuerza una reducción."
            ],
        )

    needed = target_fraction - current_target_fraction
    new_hru_fr: dict[int, float] = {}
    notes: list[str] = []

    donor_ids = [hid for hid, f in hru_files.items() if f.metadata.land_use != target_lulc]
    donor_groups = _sorted_groups(
        donor_ids,
        hru_files,
        land_use_priority=donor_priority,
        slope_priority=slope_priority,
        soil_priority=soil_priority,
    )

    remaining = needed
    for group in donor_groups:
        if remaining <= tolerance:
            break
        group_total = sum(_hru_fr(hru_files, hid) for hid in group)
        if group_total <= tolerance:
            continue
        take = min(remaining, group_total)
        for hid in group:
            hru_fraction = _hru_fr(hru_files, hid)
            if hru_fraction <= 0:
                continue
            share = hru_fraction * (take / group_total)
            new_hru_fr[hid] = hru_fraction - share
        remaining -= take

    if remaining > tolerance:
        notes.append(
            f"Subcuenca {subbasin}: faltó {remaining * 100:.4f} puntos porcentuales de área "
            "donante disponible (posible desviación de redondeo en HRU_FR); se aplicó lo "
            "máximo posible."
        )

    growth_amount = needed - remaining
    if growth_amount > tolerance:
        target_groups = _sorted_groups(
            target_ids,
            hru_files,
            land_use_priority=None,
            slope_priority=slope_priority,
            soil_priority=soil_priority,
        )
        growth_group = next((group for group in target_groups if group), [])
        group_total = sum(_hru_fr(hru_files, hid) for hid in growth_group)
        if group_total > tolerance:
            for hid in growth_group:
                hru_fraction = _hru_fr(hru_files, hid)
                share = growth_amount * (hru_fraction / group_total)
                new_hru_fr[hid] = hru_fraction + share
        elif growth_group:
            share = growth_amount / len(growth_group)
            for hid in growth_group:
                new_hru_fr[hid] = _hru_fr(hru_files, hid) + share

    return SubbasinReallocationResult(
        subbasin=subbasin,
        status=STATUS_APPLIED,
        current_target_pct=current_target_pct,
        new_hru_fr=new_hru_fr,
        notes=notes,
    )


def plan_batch_reallocation(
    hru_files_by_subbasin: dict[int, dict[int, HRUFile]],
    *,
    target_lulc: str,
    target_pct: float,
    donor_priority: list[str],
    slope_priority: list[str] | None = None,
    soil_priority: list[str] | None = None,
) -> list[SubbasinReallocationResult]:
    """Aplica ``plan_subbasin_reallocation`` a cada subcuenca del proyecto,
    en orden determinista de subcuenca."""
    return [
        plan_subbasin_reallocation(
            subbasin,
            files,
            target_lulc=target_lulc,
            target_pct=target_pct,
            donor_priority=donor_priority,
            slope_priority=slope_priority,
            soil_priority=soil_priority,
        )
        for subbasin, files in sorted(hru_files_by_subbasin.items())
    ]
