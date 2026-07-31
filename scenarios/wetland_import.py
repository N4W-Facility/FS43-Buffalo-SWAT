"""Import masivo de parámetros de humedal desde un CSV externo.

El CSV esperado sigue la misma estructura que genera
swat_io.tool_outputs.save_wetland_summary (índice subbasin_id, columnas de
swat_io.summary.summarize_project): se permite un subconjunto de
subcuencas/parámetros -- lo que no está presente en el CSV no se toca.

Esta función solo lee y valida; nunca escribe sobre los .pnd. El llamador
decide qué hacer con el resultado (staging en memoria en la UI).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from scenarios.validation import validate_field_value
from swat_io.pnd_parser import _FIELD_TO_ATTR

_NON_FIELD_COLUMNS = {"area_km2"}
_COLUMN_TO_FIELD_ID = {attr: field_id for field_id, attr in _FIELD_TO_ATTR.items()}


def parse_wetland_import_csv(
    csv_path: Path, known_subbasin_ids: list[int], layout: dict
) -> dict[int, dict[str, float]]:
    """Lee y valida un CSV de importación masiva de parámetros de humedal.

    Devuelve {subbasin_id: {field_id: value}} solo con las celdas presentes
    en el CSV.

    Levanta ValueError (mensaje con un problema por línea) si el CSV no se
    puede leer, trae columnas desconocidas, subcuencas fuera del proyecto,
    valores no numéricos, o valores fuera de rango -- en ese caso no
    devuelve ningún resultado parcial.
    """
    try:
        df = pd.read_csv(csv_path, index_col=0)
    except Exception as error:
        raise ValueError(f"No se pudo leer el archivo: {error}") from None

    errors: list[str] = []
    if df.index.name not in (None, "subbasin_id"):
        errors.append(f"Columna índice inesperada: '{df.index.name}' (se esperaba 'subbasin_id').")

    field_columns = []
    for column in df.columns:
        if column in _NON_FIELD_COLUMNS:
            continue
        if column not in _COLUMN_TO_FIELD_ID:
            errors.append(f"Columna desconocida: '{column}'.")
            continue
        field_columns.append(column)

    known_subbasin_set = set(known_subbasin_ids)
    staged: dict[int, dict[str, float]] = {}

    for raw_subbasin_id, row in df.iterrows():
        try:
            subbasin_id = int(raw_subbasin_id)
        except (TypeError, ValueError):
            errors.append(f"subbasin_id inválido: '{raw_subbasin_id}'.")
            continue
        if subbasin_id not in known_subbasin_set:
            errors.append(f"Subcuenca {subbasin_id}: no existe en este proyecto.")
            continue

        for column in field_columns:
            raw_value = row[column]
            if pd.isna(raw_value):
                continue
            field_id = _COLUMN_TO_FIELD_ID[column]
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                errors.append(f"Subcuenca {subbasin_id}, {column}: '{raw_value}' no es un número.")
                continue
            try:
                validate_field_value(field_id, value, layout)
            except ValueError as error:
                errors.append(f"Subcuenca {subbasin_id}: {error}")
                continue
            staged.setdefault(subbasin_id, {})[field_id] = value

    if errors:
        raise ValueError("\n".join(errors))

    return staged
