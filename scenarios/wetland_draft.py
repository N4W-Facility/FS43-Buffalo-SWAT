"""Borrador editable de parámetros de humedal para la ventana de edición.

Un CSV con una fila por subcuenca y los 20 campos de WetlandParams, en
tool_outputs/. Se reconstruye desde los .pnd reales cada vez que se abre
la ventana (nunca hay una copia vieja compitiendo con el archivo real);
sirve como respaldo/auditoría de lo último guardado, no como fuente de
verdad para mostrar valores.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from swat_io.discovery import discover_subbasins
from swat_io.pnd_parser import parse_pnd_file, wetland_params_to_field_values
from swat_io.tool_outputs import tool_outputs_dir

_DRAFT_FILENAME = "wetland_params_draft.csv"


def wetland_draft_path(project_dir: Path) -> Path:
    return tool_outputs_dir(project_dir) / _DRAFT_FILENAME


def build_wetland_draft(txtinout_dir: Path) -> pd.DataFrame:
    """Lee todos los .pnd reales de txtinout_dir y arma una fila por subcuenca."""
    rows = []
    for files in discover_subbasins(txtinout_dir):
        params = parse_pnd_file(files.pnd_file, files.subbasin_id)
        row = {"subbasin_id": files.subbasin_id}
        row.update(wetland_params_to_field_values(params))
        rows.append(row)
    return pd.DataFrame(rows).set_index("subbasin_id")


def save_wetland_draft(project_dir: Path, draft: pd.DataFrame) -> Path:
    path = wetland_draft_path(project_dir)
    draft.to_csv(path)
    return path
