"""Tabla cuenca -> subbasin de salida (outlet), usada al extraer resultados de output.rch.

Metadata fija de las 9 cuencas del alcance del proyecto (no son datos de modelo:
no se copian archivos, solo se registra qué subbasin_id representa la salida
de cada cuenca). Valores no confirmados quedan en None hasta verificarlos
contra el output.rch real de cada TxtInOut calibrado.
"""
from __future__ import annotations

WATERSHED_OUTLETS: dict[str, int | None] = {
    "BigSister": None,
    "Buffalo": 9,
    "Canadaway": None,
    "Cattaraugus": None,
    "Chautauqua": None,
    "Crooked": None,
    "Eighteenmile": None,
    "SilverWalnut": None,
    "Tonawanda": 37,
}
