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

``plan_area_allocation_by_priority`` (2026-09-28, pedido explícito del
usuario) es un modo alternativo, no un reemplazo: en vez de que el usuario
diga qué % del área viene de cada cobertura, recorre una lista de
prioridad entre coberturas (``coverage_priority``) y drena cada una por
completo antes de pasar a la siguiente.

La dirección depende de ``NbSDefinition.intent`` (revisado 2026-09-30,
pedido explícito del usuario -- la primera versión tenía esto invertido):
- "restoration" (convertir hacia una cobertura de buena calidad, ej.
  humedal) empieza por las coberturas MÁS DEGRADADAS (ej. urbano/pastura)
  -- restaurar significa justamente convertir suelo degradado, no talar
  bosque sano para plantar humedal. Las coberturas de mejor calidad quedan
  como último recurso.
- "degradation" (convertir hacia una cobertura degradada, ej. pastura,
  para simular deforestación/pérdida de humedal) empieza por las
  coberturas de MEJOR CALIDAD (ej. bosque/humedal) -- eso es justamente lo
  que se pierde en una degradación real. Las coberturas ya degradadas
  quedan como último recurso (no tiene sentido "degradar" pastura a
  pastura).

``effective_source_priority`` deriva esa lista para una subcuenca puntual
a partir de un archivo maestro editable sin tocar código
(``load_intervention_priority``, uno independiente por intent --
resources/lulc_intervention_priority/restoration.csv y
resources/lulc_intervention_priority/degradation.csv, pedido explícito del
usuario 2026-09-30: el orden de uno no tiene por qué ser el espejo del
otro) y las coberturas reales del proyecto -- nunca inventa una cobertura
que esa subcuenca no tenga. Devuelve el mismo
``AreaAllocationPlan``/``SourceAllocationResult`` que el modo por %, así
que scenarios.nbs_apply.apply_nbs y el resto de la UI no necesitan ningún
cambio para consumirlo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from swat_io.hru.models import HRUFile

_DEFAULT_TOLERANCE = 1e-6
_DEFAULT_PCT_SUM_TOLERANCE = 0.5
_INTERVENTION_PRIORITY_DIR = Path(__file__).resolve().parent.parent / "resources" / "lulc_intervention_priority"

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


# -- selección por orden de prioridad entre coberturas fuente (2026-09-28) ----


def load_intervention_priority(intent: str) -> list[str]:
    """Orden por defecto del archivo maestro correspondiente a ``intent``
    -- resources/lulc_intervention_priority/restoration.csv (empieza por
    las coberturas más degradadas) o .../degradation.csv (empieza por las
    de mejor calidad), ver docstring del módulo para el porqué de la
    dirección. Dos archivos independientes, no uno invertido en memoria --
    pedido explícito del usuario, 2026-09-30: el orden de uno no tiene por
    qué ser el espejo del otro, cada uno se edita por separado sin tocar
    código (mismo criterio que resources/land_cover_crosswalks/*.csv, ver
    scenarios.nbs_raster_inputs.load_crosswalk_profile). Nunca decide por
    sí solo qué coberturas son válidas en un proyecto puntual: eso siempre
    lo filtra ``effective_source_priority`` contra las coberturas reales."""
    filename = "degradation.csv" if intent == "degradation" else "restoration.csv"
    df = pd.read_csv(_INTERVENTION_PRIORITY_DIR / filename)
    return df["cpnm"].tolist()


def effective_source_priority(master_order: list[str], real_land_uses: set[str], target_lulc: str) -> list[str]:
    """Orden de prioridad de coberturas fuente para una subcuenca puntual:
    ``master_order`` (ya resuelto para el intent correcto por
    ``load_intervention_priority``) filtrado a las coberturas que de
    verdad existen ahí (``real_land_uses``, ver
    scenarios.nbs_area_apply.subbasin_land_uses), excluyendo
    ``target_lulc`` (nunca puede ser su propia fuente, mismo criterio que
    ``_coverages_by_subbasin`` en scenarios.nbs_mass_apply).

    Coberturas reales ausentes del archivo maestro se agregan al final, en
    orden alfabético -- mismo criterio de "no listada = último grupo" que
    ``_priority_index`` ya usa para pendiente/suelo: nunca se excluye una
    cobertura real solo porque el archivo maestro no la mencione."""
    available = {lulc for lulc in real_land_uses if lulc != target_lulc}
    ordered = [lulc for lulc in master_order if lulc in available]
    unlisted = sorted(available - set(ordered))
    return ordered + unlisted


def plan_area_allocation_by_priority(
    subbasin: int,
    hru_files: dict[int, HRUFile],
    subbasin_area_ha: float,
    *,
    total_area_ha: float,
    coverage_priority: list[str],
    slope_priority: list[str] | None = None,
    soil_priority: list[str] | None = None,
    tolerance: float = _DEFAULT_TOLERANCE,
) -> AreaAllocationPlan:
    """Igual que ``plan_area_allocation``, pero en vez de repartir
    ``total_area_ha`` en porcentajes fijos por cobertura, recorre
    ``coverage_priority`` en orden y drena cada cobertura por completo
    (hasta donde alcance su área real) antes de pasar a la siguiente --
    mismo criterio de cascada que ``scenarios.land_cover_reallocation``
    usa para donor_priority, adaptado acá a selección de HRU completas en
    vez de reasignación fraccionaria de HRU_FR.

    Una cobertura de ``coverage_priority`` sin ninguna HRU real en esta
    subcuenca simplemente se salta (no aparece en ``plan.by_source`` --
    a diferencia del modo por %, acá la ausencia de una cobertura es
    normal y esperada, no un error a reportar). El déficit final, si el
    área objetivo no se alcanza ni agotando toda la lista, queda en la
    última cobertura tocada."""
    plan = AreaAllocationPlan(subbasin=subbasin, total_area_ha=total_area_ha, subbasin_area_ha=subbasin_area_ha)
    already_selected: set[int] = set()
    remaining_ha = total_area_ha

    for source_lulc in coverage_priority:
        if remaining_ha <= tolerance:
            break

        candidate_ids = [
            hru_id
            for hru_id, hru_file in hru_files.items()
            if hru_file.metadata.land_use == source_lulc and hru_id not in already_selected
        ]
        if not candidate_ids:
            continue

        groups = _sorted_candidate_groups(
            candidate_ids, hru_files, slope_priority=slope_priority, soil_priority=soil_priority
        )

        selected: list[int] = []
        accumulated = 0.0
        for group in groups:
            if accumulated >= remaining_ha - tolerance:
                break
            group_sorted = sorted(group, key=lambda hid: _hru_area_ha(hru_files[hid], subbasin_area_ha))
            for hru_id in group_sorted:
                if accumulated >= remaining_ha - tolerance:
                    break
                selected.append(hru_id)
                accumulated += _hru_area_ha(hru_files[hru_id], subbasin_area_ha)

        # requested_ha = selected_ha (nunca remaining_ha de antes): una
        # cobertura que se agota por completo y le pasa la posta a la
        # siguiente no es un déficit suyo -- si el resto de la cascada sí
        # cubre lo que faltaba, atribuirle acá un "deficit_ha" propio
        # inflaría plan.total_deficit_ha aunque el resultado final haya
        # cubierto el área pedida entera. El déficit real (si la cascada
        # entera no alcanza) se ajusta después del loop, solo en la última
        # cobertura tocada.
        plan.by_source.append(
            SourceAllocationResult(
                source_lulc=source_lulc,
                requested_ha=accumulated,
                selected_ha=accumulated,
                selected_hru_ids=selected,
                status=STATUS_APPLIED,
            )
        )
        already_selected.update(selected)
        remaining_ha -= accumulated

    if plan.by_source and remaining_ha > tolerance:
        last = plan.by_source[-1]
        last.requested_ha += remaining_ha
        last.notes.append(
            f"Subbasin {subbasin}: the priority order was exhausted with {remaining_ha:.2f} ha still "
            f"short of the {total_area_ha:.2f} ha requested."
        )
    elif not plan.by_source:
        plan.by_source.append(
            SourceAllocationResult(
                source_lulc=coverage_priority[0] if coverage_priority else "",
                requested_ha=total_area_ha,
                selected_ha=0.0,
                status=STATUS_NO_SOURCE_HRU,
                notes=[f"Subbasin {subbasin}: none of the coverages in the priority order have any HRU available."],
            )
        )

    return plan
