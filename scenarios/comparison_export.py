"""Exportación comparativa entre los escenarios de un batch (pestaña Batch
Scenarios, pedido explícito del usuario 2026-08-04).

Motivación: cada paso de un batch (engine.batch_run.run_land_cover_batch)
ya organiza sus propias salidas (tool_outputs/rch_timeseries/*.csv,
tool_outputs/hru_timeseries.db) dentro de su propia carpeta
scenario_<pct>pct/. Para comparar el mismo reach/HRU/variable entre
escenarios, el usuario tendría que abrir cada carpeta como proyecto en la
app y exportar una por una -- justo el trabajo manual que se quiere
evitar. Este módulo opera directamente sobre la carpeta de un batch
(cualquiera, no solo el recién corrido) y compila, por variable, un solo
archivo con una columna por escenario.

Este módulo es de solo lectura: nunca escribe sobre ningún TxtInOut, solo
lee lo que Organize (.rch / .hru) ya dejó en cada scenario_<pct>pct/ y
escribe los CSV combinados en <batch_dir>/comparison_exports/.

Tres modos de exportación, todos "wide" en escenario (una columna por
escenario, que es el eje que se quiere comparar) y "long" en la dimensión
espacial que no se colapsa a un único punto:

- RCH: siempre incluye todos los reach de la cuenca (un reach ya es su
  propia unidad espacial, sin agregación) -- columnas date, reach,
  <escenario...>.
- HRU puntual: un único HRU -- columnas date, <escenario...>.
- HRU agrupado (cobertura/pendiente/suelo, ej. "todas las HRU de bosque"):
  agrega las HRU del grupo con `sum` o `weighted_mean` (ponderado por la
  columna AREA de output.hru) según config/hru_variable_aggregation.json,
  editable sin tocar código (decisión explícita del usuario: la
  clasificación sum/promedio por variable puede no quedar bien a la
  primera). Con alcance "cuenca completa" da una sola serie por variable;
  con alcance "subcuencas específicas" agrega columnas date, sub,
  <escenario...>.

La identidad de cada HRU (cobertura, pendiente, suelo, subcuenca) es
estable entre todos los escenarios de un mismo batch -- CLAUDE.md /
land_cover_reallocation: el batch solo modifica HRU_FR, nunca agrega ni
quita HRU ni cambia su cobertura/pendiente/suelo. Por eso la clasificación
para el modo agrupado se lee de un único escenario (el primero
encontrado), no de todos.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

from scenarios.land_cover_config import discover_land_cover_options
from swat_io.hru.scanner import parse_hru_directory
from swat_io.hru_output_parser import (
    HRU_OUTPUT_VARIABLE_COLUMNS,
    hru_output_db_path,
    list_hrus_for_subbasin,
    list_subbasins,
    read_hru_group_rows,
    read_hru_series,
)
from swat_io.rch_parser import RCH_VARIABLE_COLUMNS, rch_timeseries_dir, read_rch_timeseries_dir

_COMPARISON_EXPORTS_DIRNAME = "comparison_exports"
_AGGREGATION_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "hru_variable_aggregation.json"
_DEFAULT_AGGREGATION_METHOD = "weighted_mean"
_SCENARIO_DIR_PATTERN = re.compile(r"^scenario_([\d_]+)pct$")

AggregationMethod = Literal["sum", "weighted_mean"]
GroupScope = Literal["basin"] | list[int]


class ComparisonExportError(ValueError):
    """No hay datos suficientes para armar la exportación comparativa pedida."""


@dataclass(frozen=True)
class HRUGroupFilter:
    """Filtro de grupo de HRU: cada campo es AND entre sí; dentro de un
    campo, una lista con más de un valor es OR (ej. land_uses=["FRST",
    "RNGE"] junta ambas coberturas). None o lista vacía en un campo
    significa "cualquiera" para ese campo -- no participa del filtro."""

    land_uses: list[str] | None = None
    slopes: list[str] | None = None
    soils: list[str] | None = None


# -- descubrimiento de la carpeta de batch ------------------------------------


def _scenario_sort_key(path: Path) -> tuple[int, float | str]:
    match = _SCENARIO_DIR_PATTERN.match(path.name)
    if match:
        return (0, float(match.group(1).replace("_", ".")))
    return (1, path.name)


def discover_scenario_dirs(batch_dir: Path | str) -> list[Path]:
    """Subcarpetas de batch_dir con un TxtInOut/ directo, en el mismo orden
    que la serie que las generó cuando siguen el patrón scenario_<pct>pct/
    (orden numérico por pct, no alfabético: "scenario_10pct" no puede ir
    antes que "scenario_5pct")."""
    batch_dir = Path(batch_dir)
    if not batch_dir.is_dir():
        return []
    dirs = [p for p in batch_dir.iterdir() if p.is_dir() and (p / "TxtInOut").is_dir()]
    return sorted(dirs, key=_scenario_sort_key)


def scenario_label(scenario_dir: Path) -> str:
    """Nombre de columna para un escenario -- el propio nombre de carpeta,
    ya es único y descriptivo (ej. "scenario_10pct")."""
    return scenario_dir.name


def comparison_exports_dir(batch_dir: Path | str) -> Path:
    path = Path(batch_dir) / _COMPARISON_EXPORTS_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


# -- descubrimiento de opciones para la UI ------------------------------------


def discover_hru_group_options(batch_dir: Path | str) -> tuple[list[str], list[str], list[str]]:
    """Coberturas/pendientes/suelos reales disponibles para filtrar el modo
    agrupado -- del primer escenario encontrado (misma clasificación en
    todos, ver docstring del módulo)."""
    for scenario_dir in discover_scenario_dirs(batch_dir):
        return discover_land_cover_options(scenario_dir / "TxtInOut")
    return [], [], []


def discover_hru_selection_options(batch_dir: Path | str) -> tuple[list[int], dict[int, list[int]]]:
    """Subcuencas disponibles y sus HRU (subbasin -> [hru...]), leídas de la
    base ya organizada del primer escenario que la tenga -- usado tanto por
    el modo "HRU puntual" (selector subcuenca/HRU) como por el selector de
    subcuencas del modo agrupado con alcance "subcuencas específicas"."""
    for scenario_dir in discover_scenario_dirs(batch_dir):
        db_path = hru_output_db_path(scenario_dir)
        if not db_path.is_file():
            continue
        subbasins = list_subbasins(db_path)
        if not subbasins:
            continue
        return subbasins, {sub: list_hrus_for_subbasin(db_path, sub) for sub in subbasins}
    return [], {}


# -- clasificación de HRU (cobertura/pendiente/suelo) para el modo agrupado --


def _hru_classification(scenario_dirs: list[Path]) -> dict[int, tuple[int, str | None, str | None, str | None]]:
    """hru_id -> (subbasin, land_use, slope_class, soil), del primer
    escenario con .hru parseables. HRU es un id global único en toda la
    cuenca (ver swat_io/hru_output_parser.py), así que alcanza con un único
    escenario para clasificar todos los HRU del batch."""
    for scenario_dir in scenario_dirs:
        txtinout_dir = scenario_dir / "TxtInOut"
        if not txtinout_dir.is_dir():
            continue
        scan = parse_hru_directory(txtinout_dir)
        if not scan.files:
            continue
        classification: dict[int, tuple[int, str | None, str | None, str | None]] = {}
        for hru_file in scan.files:
            metadata = hru_file.metadata
            if metadata.subbasin is None or metadata.hru is None:
                continue
            classification[metadata.hru] = (metadata.subbasin, metadata.land_use, metadata.slope_class, metadata.soil)
        return classification
    return {}


def _matching_hru_ids(
    classification: dict[int, tuple[int, str | None, str | None, str | None]],
    group_filter: HRUGroupFilter,
    scope: GroupScope,
) -> list[int]:
    allowed_subbasins = set(scope) if scope != "basin" else None
    matches: list[int] = []
    for hru_id, (subbasin, land_use, slope_class, soil) in classification.items():
        if allowed_subbasins is not None and subbasin not in allowed_subbasins:
            continue
        if group_filter.land_uses and land_use not in group_filter.land_uses:
            continue
        if group_filter.slopes and slope_class not in group_filter.slopes:
            continue
        if group_filter.soils and soil not in group_filter.soils:
            continue
        matches.append(hru_id)
    return matches


# -- método de agregación por variable (JSON editable) ------------------------


def load_hru_variable_aggregation(path: Path | str | None = None) -> dict[str, AggregationMethod]:
    """Lee config/hru_variable_aggregation.json: método (sum/weighted_mean)
    por variable de output.hru, usado al combinar varias HRU en el modo
    agrupado. Deliberadamente en JSON y no en código (pedido explícito del
    usuario 2026-08-04): la clasificación inicial es una primera pasada y
    puede necesitar corrección variable por variable sin tocar código.
    Cualquier variable de HRU_OUTPUT_VARIABLE_COLUMNS ausente del archivo
    usa _DEFAULT_AGGREGATION_METHOD (weighted_mean, el caso correcto para
    la enorme mayoría de las variables de output.hru -- ver el propio
    archivo de configuración)."""
    config_path = Path(path) if path is not None else _AGGREGATION_CONFIG_PATH
    with config_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    configured = {str(code): str(method) for code, method in data.get("variables", {}).items()}
    return {code: configured.get(code, _DEFAULT_AGGREGATION_METHOD) for code in HRU_OUTPUT_VARIABLE_COLUMNS}


# -- exportación RCH: todos los reach de la cuenca, por variable --------------


def export_rch_comparison(batch_dir: Path | str, variables: list[str], dest_dir: Path | str | None = None) -> list[Path]:
    """Un CSV por variable (date, reach, <escenario...>), combinando todos
    los reach y todos los escenarios del batch. No agrega nada -- cada
    reach ya es su propia unidad espacial (ver docstring del módulo)."""
    scenario_dirs = discover_scenario_dirs(batch_dir)
    if not scenario_dirs:
        raise ComparisonExportError("No se encontró ningún escenario (carpeta con TxtInOut/) en la carpeta de batch.")
    if not variables:
        raise ComparisonExportError("No se eligió ninguna variable para exportar.")

    dest_dir = Path(dest_dir) if dest_dir is not None else comparison_exports_dir(batch_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    frames: dict[str, pd.DataFrame] = {}
    for scenario_dir in scenario_dirs:
        df = read_rch_timeseries_dir(rch_timeseries_dir(scenario_dir))
        if not df.empty:
            frames[scenario_label(scenario_dir)] = df

    if not frames:
        raise ComparisonExportError("Ningún escenario tiene output.rch organizado todavía (botón \"Organize .rch\").")

    written: list[Path] = []
    for variable in variables:
        merged: pd.DataFrame | None = None
        for label, df in frames.items():
            piece = df[["date", "reach", variable]].rename(columns={variable: label})
            merged = piece if merged is None else merged.merge(piece, on=["date", "reach"], how="outer")
        if merged is None or merged.empty:
            continue
        merged = merged.sort_values(["reach", "date"]).reset_index(drop=True)
        path = dest_dir / f"rch_{variable}.csv"
        merged.to_csv(path, index=False)
        written.append(path)

    if not written:
        raise ComparisonExportError("Ninguna de las variables elegidas tiene datos en los escenarios encontrados.")
    return written


# -- exportación HRU puntual: un único sub+HRU, por variable ------------------


def export_hru_point_comparison(
    batch_dir: Path | str, sub: int, hru: int, variables: list[str], dest_dir: Path | str | None = None
) -> list[Path]:
    """Un CSV por variable (date, <escenario...>) para un único HRU puntual."""
    scenario_dirs = discover_scenario_dirs(batch_dir)
    if not scenario_dirs:
        raise ComparisonExportError("No se encontró ningún escenario (carpeta con TxtInOut/) en la carpeta de batch.")
    if not variables:
        raise ComparisonExportError("No se eligió ninguna variable para exportar.")

    dest_dir = Path(dest_dir) if dest_dir is not None else comparison_exports_dir(batch_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for variable in variables:
        merged: pd.DataFrame | None = None
        for scenario_dir in scenario_dirs:
            db_path = hru_output_db_path(scenario_dir)
            if not db_path.is_file():
                continue
            series = read_hru_series(db_path, hru, variable)
            if series.empty:
                continue
            piece = series.rename(scenario_label(scenario_dir)).to_frame()
            merged = piece if merged is None else merged.join(piece, how="outer")
        if merged is None or merged.empty:
            continue
        merged = merged.sort_index()
        path = dest_dir / f"hru_sub{sub}_hru{hru}_{variable}.csv"
        merged.to_csv(path, index_label="date")
        written.append(path)

    if not written:
        raise ComparisonExportError(
            f"Subcuenca {sub} / HRU {hru}: ninguna de las variables elegidas tiene datos en los escenarios "
            "encontrados (¿corriste \"Organize .hru output\" en al menos un escenario?)."
        )
    return written


# -- exportación HRU agrupado: cobertura/pendiente/suelo, por variable -------


def _aggregate_group_rows(df: pd.DataFrame, variable: str, method: AggregationMethod, group_cols: list[str]) -> pd.DataFrame:
    if method == "sum":
        return df.groupby(group_cols, as_index=False)[variable].sum()

    def _weighted_mean(group: pd.DataFrame) -> float:
        weights = group["AREA"]
        total_weight = weights.sum()
        if total_weight == 0:
            return group[variable].mean()
        return (group[variable] * weights).sum() / total_weight

    result = df.groupby(group_cols).apply(_weighted_mean, include_groups=False)
    return result.reset_index(name=variable)


def export_hru_group_comparison(
    batch_dir: Path | str,
    group_filter: HRUGroupFilter,
    variables: list[str],
    *,
    scope: GroupScope,
    dest_dir: Path | str | None = None,
    aggregation: dict[str, AggregationMethod] | None = None,
) -> list[Path]:
    """Un CSV por variable, agregando las HRU que matchean group_filter
    (dentro de scope: "basin" o una lista de subcuencas). Con scope="basin"
    el archivo es (date, <escenario...>) -- una sola serie agregada; con
    una lista de subcuencas es (date, sub, <escenario...>) -- una serie
    agregada por subcuenca."""
    scenario_dirs = discover_scenario_dirs(batch_dir)
    if not scenario_dirs:
        raise ComparisonExportError("No se encontró ningún escenario (carpeta con TxtInOut/) en la carpeta de batch.")
    if not variables:
        raise ComparisonExportError("No se eligió ninguna variable para exportar.")

    classification = _hru_classification(scenario_dirs)
    hru_ids = _matching_hru_ids(classification, group_filter, scope)
    if not hru_ids:
        raise ComparisonExportError("Ninguna HRU coincide con el filtro de cobertura/pendiente/suelo elegido.")

    hru_to_sub = {hru_id: classification[hru_id][0] for hru_id in hru_ids}
    group_cols = ["date"] if scope == "basin" else ["date", "sub"]
    aggregation = aggregation if aggregation is not None else load_hru_variable_aggregation()

    dest_dir = Path(dest_dir) if dest_dir is not None else comparison_exports_dir(batch_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for variable in variables:
        method = aggregation.get(variable, _DEFAULT_AGGREGATION_METHOD)
        merged: pd.DataFrame | None = None
        for scenario_dir in scenario_dirs:
            db_path = hru_output_db_path(scenario_dir)
            if not db_path.is_file():
                continue
            rows = read_hru_group_rows(db_path, hru_ids, variable)
            if rows.empty:
                continue
            if "sub" in group_cols:
                rows = rows.assign(sub=rows["hru"].map(hru_to_sub))
            aggregated = _aggregate_group_rows(rows, variable, method, group_cols)
            piece = aggregated.rename(columns={variable: scenario_label(scenario_dir)})
            merged = piece if merged is None else merged.merge(piece, on=group_cols, how="outer")
        if merged is None or merged.empty:
            continue
        sort_cols = ["date"] if scope == "basin" else ["sub", "date"]
        merged = merged.sort_values(sort_cols).reset_index(drop=True)
        path = dest_dir / f"hru_group_{variable}.csv"
        merged.to_csv(path, index=False)
        written.append(path)

    if not written:
        raise ComparisonExportError(
            "Ninguna de las variables elegidas tiene datos en los escenarios encontrados "
            "(¿corriste \"Organize .hru output\" en al menos un escenario?)."
        )
    return written
