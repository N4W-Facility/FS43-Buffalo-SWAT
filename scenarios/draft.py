from __future__ import annotations

from pathlib import Path

import pandas as pd

from swat_io.summary import summarize_project

from .models import Project
from .validation import validate_field_value

_DRAFT_DIRNAME = "_borradores"

_SUMMARY_TO_FIELD = {
    "wet_fr": "wet_fr",
    "wet_nsa_ha": "wet_nsa",
    "wet_nvol_104m3": "wet_nvol",
    "wet_mxsa_ha": "wet_mxsa",
    "wet_mxvol_104m3": "wet_mxvol",
    "wet_vol_104m3": "wet_vol",
    "wet_k_mmhr": "wet_k",
}


def draft_csv_path(project: Project, scenario_name: str) -> Path:
    return project.project_dir / _DRAFT_DIRNAME / f"{scenario_name}.csv"


def init_draft(project: Project, scenario_name: str) -> Path:
    """Crea el borrador de un escenario, sembrado con los valores actuales del modelo base."""
    summary = summarize_project(project.base_txtinout_dir)
    draft = summary[list(_SUMMARY_TO_FIELD.keys())].rename(columns=_SUMMARY_TO_FIELD)
    path = draft_csv_path(project, scenario_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    draft.to_csv(path)
    return path


def read_draft(csv_path: Path) -> pd.DataFrame:
    return pd.read_csv(csv_path, index_col="subbasin_id")


def update_draft_value(
    csv_path: Path, subbasin_id: int, field_id: str, value: float, layout: dict
) -> pd.DataFrame:
    """Valida value y, si es válido, lo escribe en el borrador (memoria + disco)."""
    validate_field_value(field_id, value, layout)
    draft = read_draft(csv_path)
    if subbasin_id not in draft.index:
        raise KeyError(f"Subcuenca {subbasin_id} no está en el borrador.")
    draft.loc[subbasin_id, field_id] = value
    draft.to_csv(csv_path)
    return draft


def import_draft_csv(csv_path: Path, import_path: Path, layout: dict) -> pd.DataFrame:
    """Valida el CSV importado por completo antes de aplicar nada (all-or-nothing)."""
    field_ids = [f["id"] for f in layout["fields"]]
    incoming = pd.read_csv(import_path)

    if "subbasin_id" not in incoming.columns:
        raise ValueError("El CSV importado no tiene la columna 'subbasin_id'.")
    missing = [f for f in field_ids if f not in incoming.columns]
    if missing:
        raise ValueError(f"El CSV importado no tiene las columnas: {', '.join(missing)}.")

    draft = read_draft(csv_path)
    for _, row in incoming.iterrows():
        subbasin_id = int(row["subbasin_id"])
        if subbasin_id not in draft.index:
            raise ValueError(f"Fila con subbasin_id={subbasin_id}: no existe en este escenario.")
        for field_id in field_ids:
            validate_field_value(field_id, float(row[field_id]), layout)

    for _, row in incoming.iterrows():
        subbasin_id = int(row["subbasin_id"])
        for field_id in field_ids:
            draft.loc[subbasin_id, field_id] = float(row[field_id])

    draft.to_csv(csv_path)
    return draft
