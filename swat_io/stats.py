"""Estadísticas agregadas de un TxtInOut, para el panel de la pestaña Summary.

Agregadores puros sobre lo que ya producen swat_io.summary y swat_io.hru:
ninguna función de este módulo parsea archivos por su cuenta ni depende de
la UI, para poder testearlo sin tocar ningún widget.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .cio_parser import CioParseError, SimulationPeriod, parse_file_cio
from .hru.scanner import parse_hru_directory
from .hru.summary import build_hru_summary
from .summary import summarize_project

_WETLAND_FRACTION_THRESHOLD = 0.0
_KM2_TO_HA = 100.0


@dataclass(frozen=True)
class WetlandStats:
    subbasin_count: int
    total_area_km2: float
    wetland_area_ha: float
    wetland_coverage_pct: float
    subbasins_with_wetland: int


@dataclass(frozen=True)
class HruStats:
    hru_count: int
    land_use_count: int
    simulation_period: SimulationPeriod | None


def wetland_stats_from_summary(df: pd.DataFrame) -> WetlandStats:
    """Agrega un DataFrame ya calculado por summarize_project().

    Separado de compute_wetland_stats() para que un caller que ya parseó
    el proyecto por otro motivo (p. ej. para escribir el CSV de resumen)
    pueda reusar ese mismo DataFrame en vez de volver a parsear TxtInOut
    desde cero solo para las estadísticas.

    Área de humedal = suma de WET_NSA (área a nivel normal). "Subcuenca
    con humedal" = WET_FR > 0: WET_FR es la fracción que efectivamente
    drena al humedal, así que en 0 el humedal es inerte para el modelo
    aunque tenga área definida (decisión de producto confirmada).
    """
    subbasin_count = len(df)
    total_area_km2 = float(df["area_km2"].sum())
    wetland_area_ha = float(df["wet_nsa_ha"].sum())
    subbasins_with_wetland = int((df["wet_fr"] > _WETLAND_FRACTION_THRESHOLD).sum())

    total_area_ha = total_area_km2 * _KM2_TO_HA
    wetland_coverage_pct = (wetland_area_ha / total_area_ha * 100) if total_area_ha > 0 else 0.0

    return WetlandStats(
        subbasin_count=subbasin_count,
        total_area_km2=total_area_km2,
        wetland_area_ha=wetland_area_ha,
        wetland_coverage_pct=wetland_coverage_pct,
        subbasins_with_wetland=subbasins_with_wetland,
    )


def compute_wetland_stats(txtinout_dir: Path | str) -> WetlandStats:
    """Parsea txtinout_dir y agrega. Para el caso de uso standalone (sin
    reusar ningún parseo previo); ver wetland_stats_from_summary() si ya
    se tiene el DataFrame de summarize_project()."""
    return wetland_stats_from_summary(summarize_project(txtinout_dir))


def hru_stats_from_summary(hru_summary_df: pd.DataFrame, simulation_period: SimulationPeriod | None) -> HruStats:
    """Agrega un DataFrame ya calculado por build_hru_summary().

    Separado de compute_hru_stats() por la misma razón que
    wetland_stats_from_summary(): evitar volver a escanear los .hru cuando
    el caller ya los escaneó para otro propósito (p. ej. el CSV de
    coberturas). El periodo simulado se recibe ya resuelto, no se
    reparsea file.cio aquí.
    """
    return HruStats(
        hru_count=len(hru_summary_df),
        land_use_count=int(hru_summary_df["land_use"].nunique()),
        simulation_period=simulation_period,
    )


def compute_hru_stats(txtinout_dir: Path | str) -> HruStats:
    """Agrega build_hru_summary() más el periodo simulado de file.cio.

    El periodo queda en None si file.cio falta o está mal formado, en vez
    de tumbar todo el resumen de HRU por un archivo de control accesorio.
    Para el caso de uso standalone; ver hru_stats_from_summary() si ya se
    tiene el DataFrame de build_hru_summary().
    """
    txtinout_dir = Path(txtinout_dir)
    scan_result = parse_hru_directory(txtinout_dir)
    df = build_hru_summary(scan_result.files)

    try:
        simulation_period = parse_file_cio(txtinout_dir / "file.cio")
    except (CioParseError, FileNotFoundError):
        simulation_period = None

    return hru_stats_from_summary(df, simulation_period)
