"""Parseo y validación del CSV de configuración de un batch de cambio de
cobertura (ver CLAUDE.md / discusión con el usuario, 2026-08-03).

Una fila = una corrida completa de batch (v1: un solo ``target_lulc`` por
configuración; no se combinan varias coberturas objetivo en el mismo
batch). Columnas esperadas:

- ``target_lulc``: código de cobertura SWAT (LULC) a aumentar, tal como
  aparece en la metadata ``land_use`` de los .hru (ej. "FRST").
- ``target_pct_series``: lista de porcentajes objetivo (0-100] del área
  total de cada subcuenca, separados por coma (ej. "10,20,30"). Cada
  valor genera un escenario independiente del batch, calculado siempre
  desde el proyecto base (nunca encadenado -- ver
  scenarios.land_cover_reallocation).
- ``donor_priority``: orden de prioridad de coberturas donantes, separadas
  por ">" (ej. "PAST>RNGB>AGRR"). Obligatoria y no vacía: sin donantes no
  hay de dónde sacar el área nueva.
- ``slope_priority`` / ``soil_priority``: opcionales, mismo separador ">".
  Vacías (celda en blanco) o columna ausente si ese nivel de la cascada no
  aplica.

Este módulo solo lee y valida -- nunca toca ningún .hru ni corre nada. El
llamador (orquestación del batch) decide qué hacer con el resultado.

También expone ``write_land_cover_batch_template_csv``: sin una lista
curada de coberturas/pendientes/suelos válidos (a diferencia de Wetlands,
con sus 20 campos fijos), el usuario no tiene forma de saber de antemano
qué escribir en ``target_lulc``/``donor_priority``/``slope_priority``/
``soil_priority`` -- por eso el botón "Download template" de la pestaña
Batch genera un CSV de ejemplo con los valores que realmente existen en el
proyecto abierto (mismo criterio que "Export CSV" en la pestaña HRUs).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from swat_io.hru.scanner import parse_hru_directory

_REQUIRED_COLUMNS = ("target_lulc", "target_pct_series", "donor_priority")
_OPTIONAL_LIST_COLUMNS = ("slope_priority", "soil_priority")
_LIST_SEPARATOR = ">"


@dataclass
class LandCoverBatchConfig:
    target_lulc: str
    target_pct_series: list[float]
    donor_priority: list[str]
    slope_priority: list[str] | None
    soil_priority: list[str] | None


def _is_blank(raw_value) -> bool:
    return pd.isna(raw_value) or str(raw_value).strip() == ""


def _split_priority_list(raw_value, *, column: str, errors: list[str]) -> list[str] | None:
    if _is_blank(raw_value):
        return None
    tokens = [token.strip() for token in str(raw_value).split(_LIST_SEPARATOR) if token.strip() != ""]
    if not tokens:
        errors.append(f"'{column}': no tiene ningún valor válido después de separar por '{_LIST_SEPARATOR}'.")
        return None
    duplicates = sorted({token for token in tokens if tokens.count(token) > 1})
    if duplicates:
        errors.append(f"'{column}': valores repetidos {duplicates}; el orden de prioridad quedaría ambiguo.")
    return tokens


def _parse_pct_series(raw_value, errors: list[str]) -> list[float]:
    if _is_blank(raw_value):
        errors.append("'target_pct_series' está vacío.")
        return []
    tokens = [token.strip() for token in str(raw_value).split(",") if token.strip() != ""]
    values: list[float] = []
    for token in tokens:
        try:
            value = float(token)
        except ValueError:
            errors.append(f"'target_pct_series': '{token}' no es un número.")
            continue
        if not (0 < value <= 100):
            errors.append(f"'target_pct_series': {value} está fuera de rango (0, 100].")
            continue
        values.append(value)
    if not values and not errors:
        errors.append("'target_pct_series' no tiene ningún valor.")
    return values


def parse_land_cover_batch_csv(csv_path: str | Path) -> LandCoverBatchConfig:
    """Lee y valida el CSV de configuración de un batch de cambio de
    cobertura. Levanta ValueError (un problema por línea) si el CSV no se
    puede leer, faltan columnas requeridas, no hay exactamente una fila de
    datos, o algún valor es inválido -- en ese caso no devuelve ningún
    resultado parcial."""
    try:
        df = pd.read_csv(csv_path, dtype=str)
    except Exception as error:
        raise ValueError(f"No se pudo leer el archivo: {error}") from None

    missing_columns = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing_columns:
        raise ValueError(f"Faltan columnas requeridas: {', '.join(missing_columns)}.")

    if len(df) != 1:
        raise ValueError(
            f"El CSV debe tener exactamente una fila de configuración (tiene {len(df)}); "
            "no se soporta más de una cobertura objetivo por batch."
        )

    row = df.iloc[0]
    errors: list[str] = []

    target_lulc = "" if _is_blank(row["target_lulc"]) else str(row["target_lulc"]).strip()
    if not target_lulc:
        errors.append("'target_lulc' está vacío.")

    target_pct_series = _parse_pct_series(row["target_pct_series"], errors)

    donor_priority = _split_priority_list(row["donor_priority"], column="donor_priority", errors=errors)
    if not donor_priority:
        errors.append("'donor_priority' está vacío: se necesita al menos una cobertura donante.")

    slope_priority = (
        _split_priority_list(row["slope_priority"], column="slope_priority", errors=errors)
        if "slope_priority" in df.columns
        else None
    )
    soil_priority = (
        _split_priority_list(row["soil_priority"], column="soil_priority", errors=errors)
        if "soil_priority" in df.columns
        else None
    )

    if errors:
        raise ValueError("\n".join(errors))

    return LandCoverBatchConfig(
        target_lulc=target_lulc,
        target_pct_series=target_pct_series,
        donor_priority=donor_priority or [],
        slope_priority=slope_priority,
        soil_priority=soil_priority,
    )


_TEMPLATE_PCT_SERIES = "10,20,30"
_TEMPLATE_FALLBACK_LULC = "FRST"
_TEMPLATE_FALLBACK_DONOR = "PAST"


def discover_land_cover_options(txtinout_dir: str | Path) -> tuple[list[str], list[str], list[str]]:
    """Coberturas, pendientes y suelos que realmente existen en las HRU de
    ``txtinout_dir`` (valores distintos de metadata.land_use/slope_class/
    soil, ya ordenados). Sin esto el usuario no tiene forma de saber qué
    códigos son válidos para ``target_lulc``/``donor_priority``/
    ``slope_priority``/``soil_priority`` antes de armar el CSV."""
    scan = parse_hru_directory(txtinout_dir)
    land_uses: set[str] = set()
    slopes: set[str] = set()
    soils: set[str] = set()
    for hru_file in scan.files:
        metadata = hru_file.metadata
        if metadata.land_use is not None:
            land_uses.add(metadata.land_use)
        if metadata.slope_class is not None:
            slopes.add(metadata.slope_class)
        if metadata.soil is not None:
            soils.add(metadata.soil)
    return sorted(land_uses), sorted(slopes), sorted(soils)


def write_land_cover_batch_template_csv(txtinout_dir: str | Path, destination: str | Path) -> Path:
    """Escribe un CSV de ejemplo con la estructura exacta que espera
    ``parse_land_cover_batch_csv``, usando coberturas/pendientes/suelos
    reales de ``txtinout_dir`` en vez de un blanco genérico -- mismo
    criterio que "Export CSV" en la pestaña HRUs. El resultado es un CSV
    ya válido (cargable tal cual), pensado como punto de partida para
    editar, no como configuración final."""
    land_uses, slopes, soils = discover_land_cover_options(txtinout_dir)

    target_lulc = land_uses[0] if land_uses else _TEMPLATE_FALLBACK_LULC
    remaining_land_uses = [lulc for lulc in land_uses if lulc != target_lulc]
    donor_priority = ">".join(remaining_land_uses) if remaining_land_uses else _TEMPLATE_FALLBACK_DONOR

    df = pd.DataFrame(
        [
            {
                "target_lulc": target_lulc,
                "target_pct_series": _TEMPLATE_PCT_SERIES,
                "donor_priority": donor_priority,
                "slope_priority": ">".join(slopes),
                "soil_priority": ">".join(soils),
            }
        ]
    )
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(destination, index=False)
    return destination
