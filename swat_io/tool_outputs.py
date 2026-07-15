"""Persistencia de resultados generados por la app (no por SWAT).

Cada modelo SWAT (carpeta que contiene TxtInOut) tiene una carpeta hermana
tool_outputs/ donde la app guarda sus propios resultados derivados (ej. el
resumen de humedales), para poder reutilizarlos luego desde la interfaz sin
volver a parsear los archivos de entrada.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_TOOL_OUTPUTS_DIRNAME = "tool_outputs"
_WETLAND_SUMMARY_FILENAME = "wetland_summary.csv"


def tool_outputs_dir(model_dir: Path | str) -> Path:
    """Devuelve la carpeta tool_outputs/ del modelo, creándola si no existe.

    model_dir es la carpeta del modelo (la que contiene TxtInOut/), no
    TxtInOut en sí.
    """
    path = Path(model_dir) / _TOOL_OUTPUTS_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_wetland_summary(model_dir: Path | str, df: pd.DataFrame) -> Path:
    """Guarda el resumen de humedales como CSV en tool_outputs/ y devuelve la ruta."""
    csv_path = tool_outputs_dir(model_dir) / _WETLAND_SUMMARY_FILENAME
    df.to_csv(csv_path)
    return csv_path
