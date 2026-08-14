"""Orquestación de la pestaña "Restoration Inputs": cruza un raster de
cobertura (ej. Cropland Data Layer) con un raster de restauración/NbS
(clases categóricas -- ver raster_io.rat) sobre el shapefile de subcuencas
ya configurado en Project, y escribe un CSV por clase de restauración en
el mismo formato matriz `subbasin, area_ha, <coberturas>` que ya consume
``scenarios.nbs_mass_apply.parse_mass_allocation_csv`` (Apply an NbS by
area (all subbasins) / NbS area batch) -- pedido explícito del usuario:
que el resultado se pueda cargar directo ahí.

Toda la geometría/CRS/lectura de raster vive en raster_io/ (sin
dependencias de UI); este módulo solo agrega el cruce CDL->CPNM (elegido
por el usuario contra las coberturas reales del proyecto abierto, nunca
adivinado) y el formato de salida.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

from raster_io.crosstab import ProgressCallback, compute_crosstab
from raster_io.grid import BBox, TargetGrid, compute_target_grid
from raster_io.prj import read_shapefile_crs
from raster_io.rat import read_pam_rat_names
from raster_io.scan import scan_unique_values
from raster_io.subbasin_zones import shapefile_bbox, subbasin_geometries
from scenarios.land_cover_config import discover_land_cover_options
from swat_io.tool_outputs import tool_outputs_dir

_BACKGROUND_RESTORATION_CLASS = 0
_OUTPUT_SUBDIR = "restoration_inputs"
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")
# Mismo criterio que scenarios.nbs_mass_apply: 0.5 de tolerancia en la
# suma de % por fila -- el redondeo a 4 decimales de un área real nunca la
# excede.
_PCT_DECIMALS = 4
_AREA_DECIMALS = 3

# CoverageCrosswalk: código de cobertura del raster (ej. NASS CDL) -> CPNM
# real del proyecto, o None para excluirlo a propósito. Pedido explícito
# del usuario, 2026-08-14 (revisado tras la v1, que excluía todo código sin
# mapear y no calculaba nada si el usuario no llegaba a mapear ninguno):
# el cruce nunca debe depender de que el usuario complete esta tabla antes
# de poder ver números. Un código AUSENTE del dict (nunca tocado en la UI)
# usa su propio código como nombre de columna (ver
# _label_for_land_cover_code) -- solo un código con valor explícito
# ``None`` (el usuario eligió "(skip)") se excluye de verdad.
CoverageCrosswalk = dict[int, str | None]


class RestorationInputsError(ValueError):
    """Error de datos de entrada (rutas, sin overlap geográfico, etc.) --
    nunca se llega a escribir ningún CSV."""


@dataclass(frozen=True)
class LandCoverCode:
    code: int
    approx_pixel_count: int


@dataclass(frozen=True)
class RestorationClass:
    value: int
    name: str | None
    approx_pixel_count: int


@dataclass(frozen=True)
class RestorationScanResult:
    grid: TargetGrid
    land_cover_codes: list[LandCoverCode]
    restoration_classes: list[RestorationClass]


def _open_raster_grid(subbasin_shp_path: str | Path, raster_paths: list[Path]) -> TargetGrid:
    crs = read_shapefile_crs(subbasin_shp_path)
    bbox: BBox = shapefile_bbox(subbasin_shp_path)
    return compute_target_grid(bbox, crs, raster_paths)


def scan_restoration_inputs(
    subbasin_shp_path: str | Path, land_cover_raster_path: str | Path, restoration_raster_path: str | Path
) -> RestorationScanResult:
    """Descubre, de forma aproximada y rápida (ver raster_io.scan), qué
    códigos de cobertura y qué clases de restauración existen realmente
    dentro del área de trabajo (cuenca ∩ raster de restauración) -- para
    poblar la tabla de cruce en la UI antes de calcular el CSV final."""
    land_cover_raster_path = Path(land_cover_raster_path)
    restoration_raster_path = Path(restoration_raster_path)
    grid = _open_raster_grid(subbasin_shp_path, [land_cover_raster_path, restoration_raster_path])

    land_cover_counts = scan_unique_values(land_cover_raster_path, grid)
    restoration_counts = scan_unique_values(restoration_raster_path, grid)
    restoration_names = read_pam_rat_names(restoration_raster_path) or {}

    land_cover_codes = [
        LandCoverCode(code=code, approx_pixel_count=count)
        for code, count in sorted(land_cover_counts.items(), key=lambda kv: -kv[1])
    ]
    restoration_classes = [
        RestorationClass(value=value, name=restoration_names.get(value), approx_pixel_count=count)
        for value, count in sorted(restoration_counts.items())
        if value != _BACKGROUND_RESTORATION_CLASS
    ]
    return RestorationScanResult(grid=grid, land_cover_codes=land_cover_codes, restoration_classes=restoration_classes)


def discover_project_coverages(project_dir: str | Path) -> list[str]:
    """Coberturas CPNM reales del proyecto abierto -- opciones que la UI
    ofrece para mapear cada código del raster de cobertura (nunca una
    lista inventada)."""
    land_uses, _slopes, _soils = discover_land_cover_options(Path(project_dir) / "TxtInOut")
    return land_uses


def _restoration_output_name(restoration_class: RestorationClass) -> str:
    label = restoration_class.name or f"class_{restoration_class.value}"
    safe = _SAFE_NAME_RE.sub("_", label).strip("_") or f"class_{restoration_class.value}"
    return f"restoration_inputs_{safe}.csv"


@dataclass(frozen=True)
class RestorationClassOutput:
    restoration_value: int
    restoration_name: str | None
    csv_path: Path
    subbasin_count: int
    # subcuenca -> hectáreas excluidas a propósito (código mapeado a "(skip)")
    excluded_ha_by_subbasin: dict[int, float] = field(default_factory=dict)
    # códigos que aparecen en el CSV con su propio número como columna,
    # porque el usuario nunca les asignó una cobertura real -- no están
    # excluidos, solo sin traducir a CPNM (ver CoverageCrosswalk).
    auto_labeled_codes: frozenset[int] = field(default_factory=frozenset)


@dataclass(frozen=True)
class RestorationComputeResult:
    outputs: list[RestorationClassOutput]
    pixel_area_ha: float


def compute_restoration_area_csvs(
    project_dir: str | Path,
    subbasin_shp_path: str | Path,
    land_cover_raster_path: str | Path,
    restoration_raster_path: str | Path,
    crosswalk: CoverageCrosswalk,
    *,
    on_progress: ProgressCallback | None = None,
) -> RestorationComputeResult:
    """Corre el cruce completo (resolución real, no el muestreo de
    ``scan_restoration_inputs``) y escribe un CSV por clase de
    restauración no-background en ``tool_outputs/restoration_inputs/``.

    ``crosswalk`` es opcional en la práctica: un código de cobertura
    ausente del dict se calcula igual, usando su propio código numérico
    como nombre de columna (``RestorationClassOutput.auto_labeled_codes``
    documenta cuáles) -- solo un código mapeado explícitamente a ``None``
    ("(skip)" en la UI) se excluye de verdad, y esa área sí queda afuera
    (``excluded_ha_by_subbasin``). Nunca hace falta completar el cruce
    para obtener resultados; completar el cruce después solo cambia el
    nombre de columna de "141" a "FRSD", no si esa área se computa."""
    land_cover_raster_path = Path(land_cover_raster_path)
    restoration_raster_path = Path(restoration_raster_path)

    grid = _open_raster_grid(subbasin_shp_path, [land_cover_raster_path, restoration_raster_path])
    geometries = subbasin_geometries(subbasin_shp_path)
    crosstab = compute_crosstab(
        land_cover_raster_path, restoration_raster_path, geometries, grid, on_progress=on_progress
    )
    restoration_names = read_pam_rat_names(restoration_raster_path) or {}

    # (restoration_class, subbasin) -> {etiqueta: ha} -- la etiqueta es el
    # CPNM real si se mapeó, o el código crudo (str) si no.
    mapped_ha: dict[tuple[int, int], dict[str, float]] = defaultdict(dict)
    # (restoration_class, subbasin) -> ha excluida a propósito ("(skip)")
    excluded_ha: dict[tuple[int, int], float] = defaultdict(float)
    # clase de restauración -> códigos que usaron su propio número como etiqueta
    auto_labeled_by_class: dict[int, set[int]] = defaultdict(set)

    for (subbasin, restoration_class, land_cover_code), pixel_count in crosstab.counts.items():
        if restoration_class == _BACKGROUND_RESTORATION_CLASS:
            continue
        ha = pixel_count * crosstab.pixel_area_ha
        key = (restoration_class, subbasin)
        if land_cover_code in crosswalk:
            label = crosswalk[land_cover_code]
            if label is None:
                excluded_ha[key] += ha
                continue
        else:
            label = str(land_cover_code)
            auto_labeled_by_class[restoration_class].add(land_cover_code)
        mapped_ha[key][label] = mapped_ha[key].get(label, 0.0) + ha

    restoration_values = sorted({cls for cls, _sub in mapped_ha} | {cls for cls, _sub in excluded_ha})
    output_dir = tool_outputs_dir(project_dir) / _OUTPUT_SUBDIR
    output_dir.mkdir(parents=True, exist_ok=True)

    outputs: list[RestorationClassOutput] = []
    for restoration_value in restoration_values:
        subbasins_for_class = sorted({sub for cls, sub in mapped_ha if cls == restoration_value})
        coverage_columns = sorted({cpnm for cls, sub in mapped_ha if cls == restoration_value for cpnm in mapped_ha[(cls, sub)]})

        rows = []
        subbasin_excluded: dict[int, float] = {}
        for subbasin in subbasins_for_class:
            coverages = mapped_ha.get((restoration_value, subbasin), {})
            area_ha = sum(coverages.values())
            row = {"subbasin": subbasin, "area_ha": round(area_ha, _AREA_DECIMALS)}
            for coverage in coverage_columns:
                ha = coverages.get(coverage, 0.0)
                row[coverage] = round(100 * ha / area_ha, _PCT_DECIMALS) if area_ha > 0 else 0.0
            rows.append(row)
            excluded = excluded_ha.get((restoration_value, subbasin), 0.0)
            if excluded > 0:
                subbasin_excluded[subbasin] = round(excluded, _AREA_DECIMALS)

        restoration_name = restoration_names.get(restoration_value)
        csv_path = output_dir / _restoration_output_name(
            RestorationClass(value=restoration_value, name=restoration_name, approx_pixel_count=0)
        )
        pd.DataFrame(rows, columns=["subbasin", "area_ha", *coverage_columns]).to_csv(csv_path, index=False)

        outputs.append(
            RestorationClassOutput(
                restoration_value=restoration_value,
                restoration_name=restoration_name,
                csv_path=csv_path,
                subbasin_count=len(subbasins_for_class),
                excluded_ha_by_subbasin=subbasin_excluded,
                auto_labeled_codes=frozenset(auto_labeled_by_class.get(restoration_value, set())),
            )
        )

    return RestorationComputeResult(outputs=outputs, pixel_area_ha=crosstab.pixel_area_ha)
