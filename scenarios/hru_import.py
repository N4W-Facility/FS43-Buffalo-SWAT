"""Import masivo de parámetros de HRU desde un CSV externo.

A diferencia de wetland_import.py (una fila = una subcuenca, columnas
fijas tomadas de wetland_summary.csv), aquí una fila = una HRU: el CSV se
indexa por las columnas "subbasin" y "hru", y las columnas de parámetro no
están curadas -- no hay una lista fija como ``_FIELD_TO_CODE`` en
pnd_parser.py, porque la pestaña HRUs expone "todos los campos" de cada
.hru (ver CLAUDE.md). Por eso esta función solo valida que la
subcuenca/HRU exista (por nombre de archivo, sin parsear contenido, vía
``scenarios.hru_draft.list_subbasin_hru_ids``) y que el valor sea
numérico; si una columna nombra un parámetro que esa HRU puntual no
tiene, eso lo rechaza recién ``HRUFile.set_value`` en Materialize
(``HRUModificationError``), no aquí.

Esta función solo lee y valida; nunca escribe sobre ningún .hru. El
llamador decide qué hacer con el resultado (staging en memoria en la UI).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from scenarios.hru_draft import list_subbasin_hru_ids

_INDEX_COLUMNS = ("subbasin", "hru")


def parse_hru_import_csv(
    csv_path: Path, txtinout_dir: Path, known_subbasin_ids: list[int]
) -> dict[tuple[int, int], dict[str, float]]:
    """Lee y valida un CSV de importación masiva de parámetros de HRU.

    Formato esperado: columnas "subbasin", "hru" más una columna por
    parámetro (nombre del código SWAT crudo, p. ej. "CANMX"). Devuelve
    {(subbasin_id, hru_id): {parameter_name: value}} solo con las celdas
    presentes en el CSV.

    Levanta ValueError (mensaje con un problema por línea) si el CSV no se
    puede leer, faltan las columnas requeridas, hay subcuencas/HRU fuera
    del proyecto, o valores no numéricos -- en ese caso no devuelve ningún
    resultado parcial.
    """
    try:
        df = pd.read_csv(csv_path)
    except Exception as error:
        raise ValueError(f"No se pudo leer el archivo: {error}") from None

    missing_columns = [c for c in _INDEX_COLUMNS if c not in df.columns]
    if missing_columns:
        raise ValueError(f"Faltan columnas requeridas: {', '.join(missing_columns)}.")

    parameter_columns = [c for c in df.columns if c not in _INDEX_COLUMNS]
    known_subbasin_set = set(known_subbasin_ids)
    hru_ids_by_subbasin: dict[int, set[int]] = {}

    errors: list[str] = []
    staged: dict[tuple[int, int], dict[str, float]] = {}

    for _, row in df.iterrows():
        try:
            subbasin_id = int(row["subbasin"])
            hru_id = int(row["hru"])
        except (TypeError, ValueError):
            errors.append(f"subbasin/hru inválido: '{row['subbasin']}'/'{row['hru']}'.")
            continue

        if subbasin_id not in known_subbasin_set:
            errors.append(f"Subcuenca {subbasin_id}: no existe en este proyecto.")
            continue

        known_hrus = hru_ids_by_subbasin.setdefault(
            subbasin_id, list_subbasin_hru_ids(txtinout_dir, subbasin_id)
        )
        if hru_id not in known_hrus:
            errors.append(f"Subcuenca {subbasin_id}, HRU {hru_id}: no existe en este proyecto.")
            continue

        for column in parameter_columns:
            raw_value = row[column]
            if pd.isna(raw_value):
                continue
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                errors.append(f"Subcuenca {subbasin_id}, HRU {hru_id}, {column}: '{raw_value}' no es un número.")
                continue
            staged.setdefault((subbasin_id, hru_id), {})[column] = value

    if errors:
        raise ValueError("\n".join(errors))

    return staged
