"""Resúmenes tabulares (pandas) de un conjunto de archivos .hru ya parseados.

Nota importante de dominio: ``HRU_FR`` (fracción de la subcuenca que
corresponde a una HRU, definido en .hru) y ``WET_FR`` (fracción de la
subcuenca que drena al humedal, definido en .pnd) son variables
independientes y este módulo nunca las combina.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..common.atomic_write import atomic_write_bytes
from .models import HRUFile

_BASE_COLUMNS = [
    "file_path",
    "file_name",
    "subbasin",
    "hru",
    "gis_id",
    "land_use",
    "soil",
    "slope_class",
    "HRU_FR",
    "parse_status",
    "validation_status",
]


def build_hru_summary(
    hru_files: list[HRUFile],
    *,
    parameters: list[str] | None = None,
) -> pd.DataFrame:
    """Una fila por archivo .hru, con las columnas base más los
    ``parameters`` solicitados (NaN cuando el parámetro no existe en un
    archivo dado; nunca detiene el proceso por eso)."""
    extra_parameters = [p for p in (parameters or []) if p.upper() != "HRU_FR"]
    extra_columns = [p.upper() for p in extra_parameters]

    rows: list[dict] = []
    for hru_file in hru_files:
        issues = hru_file.validate()
        has_error = any(issue.severity == "ERROR" for issue in issues)
        has_warning = any(issue.severity == "WARNING" for issue in issues)

        row = {
            "file_path": str(hru_file.source_path) if hru_file.source_path else None,
            "file_name": hru_file.source_path.name if hru_file.source_path else None,
            "subbasin": hru_file.metadata.subbasin,
            "hru": hru_file.metadata.hru,
            "gis_id": hru_file.metadata.gis_id,
            "land_use": hru_file.metadata.land_use,
            "soil": hru_file.metadata.soil,
            "slope_class": hru_file.metadata.slope_class,
            "HRU_FR": hru_file.get_value("HRU_FR", default=float("nan")),
            "parse_status": "OK" if hru_file.lines else "EMPTY",
            "validation_status": "ERROR" if has_error else ("WARNING" if has_warning else "OK"),
        }
        for parameter, column in zip(extra_parameters, extra_columns):
            row[column] = hru_file.get_value(parameter, default=float("nan"))
        rows.append(row)

    columns = _BASE_COLUMNS + extra_columns
    return pd.DataFrame(rows, columns=columns)


def summarize_land_use_by_subbasin(
    summary_df: pd.DataFrame,
    *,
    tolerance: float = 1e-4,
) -> pd.DataFrame:
    """Agrupa por subbasin + land_use: hru_count, fraction_sum (suma de
    HRU_FR) y percentage_of_subbasin (fraction_sum * 100)."""
    grouped = (
        summary_df.groupby(["subbasin", "land_use"], dropna=False)["HRU_FR"]
        .agg(hru_count="size", fraction_sum="sum")
        .reset_index()
    )
    grouped["percentage_of_subbasin"] = grouped["fraction_sum"] * 100
    grouped = grouped.sort_values(["subbasin", "land_use"], kind="stable").reset_index(drop=True)
    return grouped[["subbasin", "land_use", "hru_count", "fraction_sum", "percentage_of_subbasin"]]


def find_subbasins_with_invalid_fraction_sum(
    land_use_summary: pd.DataFrame,
    *,
    tolerance: float = 1e-4,
) -> pd.DataFrame:
    """Subcuencas cuya suma total de HRU_FR (todas las coberturas) se
    desvía de 1 más allá de ``tolerance``."""
    totals = land_use_summary.groupby("subbasin", dropna=False)["fraction_sum"].sum().reset_index()
    totals["deviation"] = (totals["fraction_sum"] - 1.0).abs()
    return totals[totals["deviation"] > tolerance].reset_index(drop=True)


def add_land_use_area(
    land_use_summary: pd.DataFrame,
    subbasin_areas: pd.DataFrame,
) -> pd.DataFrame:
    """Añade land_use_area_km2/ha a partir de un área de subcuenca externa
    (subbasin, sub_km2) obtenida de .sub. Este módulo nunca inventa el
    área de la subcuenca a partir de solo los .hru.

    Interfaz esperada para un futuro ``swat_io/sub``: un DataFrame con
    columnas exactamente ``subbasin`` (int) y ``sub_km2`` (float), una
    fila por subcuenca.
    """
    merged = land_use_summary.merge(subbasin_areas[["subbasin", "sub_km2"]], on="subbasin", how="left")
    merged["land_use_area_km2"] = merged["fraction_sum"] * merged["sub_km2"]
    merged["land_use_area_ha"] = merged["land_use_area_km2"] * 100
    return merged


def land_use_percentages(
    land_use_summary: pd.DataFrame,
    subbasin: int | None = None,
    *,
    categories: list[str] | None = None,
) -> pd.Series:
    """land_use -> % of area, para una subcuenca o para toda la cuenca.

    Con subbasin=None, el total de cuenca pondera por land_use_area_km2 (no
    promedia el percentage_of_subbasin de cada subcuenca), para que las
    subcuencas más grandes pesen más. categories, si se pasa, reindexa el
    resultado (rellenando con 0) para que el mismo eje de coberturas se
    pueda reusar entre selecciones, como una tabla dinámica.

    Excluye filas con land_use NaN (Luse no parseable en el .hru de origen,
    caso real en datasets grandes): no son una cobertura graficable y
    romperían el ordenamiento de categorías (float NaN vs. str).
    """
    land_use_summary = land_use_summary[land_use_summary["land_use"].notna()]

    if subbasin is not None:
        rows = land_use_summary[land_use_summary["subbasin"] == subbasin]
        series = rows.set_index("land_use")["percentage_of_subbasin"]
    else:
        area_by_land_use = land_use_summary.groupby("land_use")["land_use_area_km2"].sum()
        series = area_by_land_use / subbasin_area_km2(land_use_summary) * 100

    series = series.sort_index()
    if categories is not None:
        series = series.reindex(categories, fill_value=0.0)
    return series


def read_land_use_summary_csv(path: str | Path, *, separator: str = ",") -> pd.DataFrame:
    return pd.read_csv(path, sep=separator)


def subbasin_area_km2(land_use_summary: pd.DataFrame, subbasin: int | None = None) -> float:
    """Área (km²) de una subcuenca (columna sub_km2), o de toda la cuenca
    (suma de sub_km2, una vez por subcuenca) cuando subbasin es None."""
    if subbasin is not None:
        rows = land_use_summary[land_use_summary["subbasin"] == subbasin]
        return float(rows["sub_km2"].iloc[0]) if not rows.empty else 0.0
    return float(land_use_summary.drop_duplicates("subbasin")["sub_km2"].sum())


def _export_csv(df: pd.DataFrame, destination: str | Path, separator: str) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    csv_text = df.to_csv(index=False, sep=separator)
    atomic_write_bytes(destination, csv_text.encode("utf-8"))
    return destination


def export_hru_summary_csv(
    summary_df: pd.DataFrame,
    destination: str | Path,
    *,
    separator: str = ",",
) -> Path:
    return _export_csv(summary_df, destination, separator)


def export_land_use_summary_csv(
    summary_df: pd.DataFrame,
    destination: str | Path,
    *,
    separator: str = ",",
) -> Path:
    return _export_csv(summary_df, destination, separator)
