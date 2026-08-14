"""Lectura del CRS de un shapefile desde su .prj -- pyshp (usado por
viz.shapefile_reader para la geometría) no interpreta proyecciones, así
que esto es un módulo aparte y nuevo, no una extensión de ese lector.
"""
from __future__ import annotations

from pathlib import Path

from rasterio.crs import CRS


class PrjNotFoundError(ValueError):
    """El shapefile no tiene un .prj junto a él -- sin CRS no hay forma de
    saber en qué sistema de coordenadas está construido el modelo, y ese
    es el CRS de destino de todo el cruce (pedido explícito del usuario:
    el shapefile manda, porque es el que usa el modelo)."""


def read_shapefile_crs(shp_path: str | Path) -> CRS:
    prj_path = Path(shp_path).with_suffix(".prj")
    if not prj_path.is_file():
        raise PrjNotFoundError(f"No .prj file found next to '{shp_path}' -- cannot determine its coordinate system.")
    wkt = prj_path.read_text(encoding="utf-8", errors="replace")
    return CRS.from_wkt(wkt)
