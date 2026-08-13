"""Algoritmo puro de selección de HRU por área objetivo, para la sección
"Apply by area" de la pestaña NbS (pedido explícito del usuario,
2026-08-11): en vez de elegir HRU una por una a mano (ver
scenarios/nbs_apply.py), el usuario da un área total (ha) a convertir en
una subcuenca y cómo repartirla entre las coberturas fuente que hoy tienen
esa área (ej. 40% desde bosque, 60% desde pastos). Este módulo decide
*cuáles* HRU entran en esa conversión; escribir los cambios de verdad sigue
siendo trabajo de scenarios.nbs_apply.apply_nbs sobre la lista de
(subbasin, hru) resultante.

Reglas acordadas con el usuario:

- Alcance: una subcuenca a la vez (igual que la sección manual de Apply).
- Por cada cobertura fuente, el área objetivo (ha) = área total * su
  porcentaje. Las HRU candidatas son las de esa cobertura en la subcuenca,
  nunca de otra -- no se crea ninguna HRU nueva y no se reparte entre
  coberturas no listadas.
- Selección de HRU completas únicamente: nunca se parte una HRU en dos
  coberturas para calzar el área exacta (mismo criterio ya aceptado en
  scenarios.land_cover_reallocation -- crear/partir una HRU equivaldría a
  recalibrar). Dentro de cada grupo de prioridad se toman las HRU de menor
  a mayor área (heurística simple para minimizar el sobrante cuando el
  área objetivo no calza exacto con la suma de HRU completas) hasta
  igualar o superar el objetivo.
- Prioridad en cascada configurable de pendiente (opcional) > suelo
  (opcional) -- sin nivel de cobertura porque cada cobertura fuente ya se
  procesa aislada. Mismo criterio de "no listado = último grupo, empatan
  entre sí" que land_cover_reallocation.
- Si una cobertura fuente no tiene HRU disponibles en la subcuenca, se
  omite (no hay de dónde sacar el área). Si tiene menos área de la
  pedida, se aplica toda la disponible y se reporta el déficit -- no se
  aborta el resto de la aplicación (mismo criterio que Batch).
- Una HRU ya seleccionada para una cobertura fuente no puede volver a
  seleccionarse para otra (no hay superposición posible entre coberturas
  distintas de todos modos, ya que la pertenencia a una cobertura es
  mutuamente excluyente por HRU).

Este módulo no toca disco ni muta los HRUFile recibidos: solo lee
HRU_FR/metadata y devuelve un plan (lista de HRU seleccionadas por
cobertura fuente + estadísticas de área). Aplicarlo de verdad es
responsabilidad del llamador, vía scenarios.nbs_apply.apply_nbs sobre
AreaAllocationPlan.targets.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from swat_io.hru.models import HRUFile

_DEFAULT_TOLERANCE = 1e-6
_DEFAULT_PCT_SUM_TOLERANCE = 0.5

STATUS_APPLIED = "applied"
STATUS_NO_SOURCE_HRU = "no_source_hru"


@dataclass
class SourceAllocationResult:
    source_lulc: str
    requested_ha: float
    selected_ha: float
    selected_hru_ids: list[int] = field(default_factory=list)
    status: str = STATUS_APPLIED
    notes: list[str] = field(default_factory=list)

    @property
    def deficit_ha(self) -> float:
        return max(0.0, self.requested_ha - self.selected_ha)


@dataclass
class AreaAllocationPlan:
    subbasin: int
    total_area_ha: float
    subbasin_area_ha: float
    by_source: list[SourceAllocationResult] = field(default_factory=list)

    @property
    def targets(self) -> list[tuple[int, int]]:
        return [(self.subbasin, hid) for result in self.by_source for hid in result.selected_hru_ids]

    @property
    def total_deficit_ha(self) -> float:
        return sum(result.deficit_ha for result in self.by_source)


def validate_source_allocations(
    source_allocations: list[tuple[str, float]],
    *,
    tolerance: float = _DEFAULT_PCT_SUM_TOLERANCE,
) -> list[str]:
    """Errores de la lista (cobertura, %) antes de calcular ningún plan --
    lista vacía si está bien formada. No valida que las coberturas existan
    de verdad en la subcuenca (eso se resuelve solo al no encontrar HRU
    candidatas, ver STATUS_NO_SOURCE_HRU)."""
    errors: list[str] = []
    if not source_allocations:
        errors.append("You must add at least one source coverage.")
        return errors

    names = [name for name, _ in source_allocations]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        errors.append(f"Repeated coverages in the list: {', '.join(duplicates)}.")

    for name, pct in source_allocations:
        if pct <= 0:
            errors.append(f"'{name}': the percentage must be greater than 0.")

    total = sum(pct for _, pct in source_allocations)
    if abs(total - 100) > tolerance:
        errors.append(f"Percentages must add up to 100 (they add up to {total:.2f}).")

    return errors


def parse_priority_text(raw: str | None) -> list[str] | None:
    """Convierte un campo de texto ">"-separado (ej. "0-9999>9999-9999") en
    una lista de prioridad, o None si está vacío -- mismo separador que
    scenarios.land_cover_config para donor/slope/soil_priority."""
    if raw is None or not raw.strip():
        return None
    tokens = [token.strip() for token in raw.split(">") if token.strip() != ""]
    return tokens or None


def subbasin_land_uses(hru_files: dict[int, HRUFile]) -> list[str]:
    """Coberturas distintas presentes en las HRU dadas (metadata.land_use),
    ordenadas -- para poblar el selector de cobertura fuente sin que el
    usuario tenga que adivinar qué códigos existen en esa subcuenca."""
    return sorted({f.metadata.land_use for f in hru_files.values() if f.metadata.land_use})


def _hru_fr(hru_file: HRUFile) -> float:
    return float(hru_file.get_value("HRU_FR", default=0.0) or 0.0)


def _hru_area_ha(hru_file: HRUFile, subbasin_area_ha: float) -> float:
    return _hru_fr(hru_file) * subbasin_area_ha


def _priority_index(value: str | None, priority: list[str] | None) -> int:
    if priority is None:
        return 0
    if value in priority:
        return priority.index(value)
    return len(priority)


def _sorted_candidate_groups(
    hru_ids: list[int],
    hru_files: dict[int, HRUFile],
    *,
    slope_priority: list[str] | None,
    soil_priority: list[str] | None,
) -> list[list[int]]:
    keyed: dict[tuple[int, int], list[int]] = {}
    for hru_id in hru_ids:
        metadata = hru_files[hru_id].metadata
        key = (
            _priority_index(metadata.slope_class, slope_priority),
            _priority_index(metadata.soil, soil_priority),
        )
        keyed.setdefault(key, []).append(hru_id)
    return [keyed[key] for key in sorted(keyed)]


def plan_area_allocation(
    subbasin: int,
    hru_files: dict[int, HRUFile],
    subbasin_area_ha: float,
    *,
    total_area_ha: float,
    source_allocations: list[tuple[str, float]],
    slope_priority: list[str] | None = None,
    soil_priority: list[str] | None = None,
    tolerance: float = _DEFAULT_TOLERANCE,
) -> AreaAllocationPlan:
    """Calcula, por cada (cobertura fuente, % del área total), qué HRU
    completas de esa subcuenca hay que convertir para cubrir el área
    pedida. Nunca escribe ni muta hru_files."""
    plan = AreaAllocationPlan(subbasin=subbasin, total_area_ha=total_area_ha, subbasin_area_ha=subbasin_area_ha)
    already_selected: set[int] = set()

    for source_lulc, pct in source_allocations:
        requested_ha = total_area_ha * (pct / 100)
        candidate_ids = [
            hru_id
            for hru_id, hru_file in hru_files.items()
            if hru_file.metadata.land_use == source_lulc and hru_id not in already_selected
        ]

        if not candidate_ids:
            plan.by_source.append(
                SourceAllocationResult(
                    source_lulc=source_lulc,
                    requested_ha=requested_ha,
                    selected_ha=0.0,
                    status=STATUS_NO_SOURCE_HRU,
                    notes=[f"Subbasin {subbasin}: has no HRU with coverage '{source_lulc}' available."],
                )
            )
            continue

        groups = _sorted_candidate_groups(
            candidate_ids, hru_files, slope_priority=slope_priority, soil_priority=soil_priority
        )

        selected: list[int] = []
        accumulated = 0.0
        for group in groups:
            if accumulated >= requested_ha - tolerance:
                break
            group_sorted = sorted(group, key=lambda hid: _hru_area_ha(hru_files[hid], subbasin_area_ha))
            for hru_id in group_sorted:
                if accumulated >= requested_ha - tolerance:
                    break
                selected.append(hru_id)
                accumulated += _hru_area_ha(hru_files[hru_id], subbasin_area_ha)

        notes: list[str] = []
        if accumulated < requested_ha - tolerance:
            notes.append(
                f"Subbasin {subbasin}: coverage '{source_lulc}' only has {accumulated:.2f} ha available "
                f"out of the {requested_ha:.2f} ha requested; all available area was selected."
            )

        plan.by_source.append(
            SourceAllocationResult(
                source_lulc=source_lulc,
                requested_ha=requested_ha,
                selected_ha=accumulated,
                selected_hru_ids=selected,
                status=STATUS_APPLIED,
                notes=notes,
            )
        )
        already_selected.update(selected)

    return plan
