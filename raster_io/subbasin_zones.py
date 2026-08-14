"""Puente entre viz.shapefile_reader (lectura pyshp ya existente, geometría
cruda) y lo que rasterio.features.rasterize necesita (mappings estilo
GeoJSON) -- sin agregar una segunda forma de leer el .shp."""
from __future__ import annotations

from pathlib import Path

import shapefile

from viz.shapefile_reader import SUBBASIN_ID_FIELD, ShapeRecord, read_subbasin_shapes

from .grid import BBox


def shapefile_bbox(shp_path: str | Path) -> BBox:
    reader = shapefile.Reader(str(shp_path))
    minx, miny, maxx, maxy = reader.bbox
    return (minx, miny, maxx, maxy)


def subbasin_geometries(shp_path: str | Path) -> list[tuple[dict, int]]:
    """[(geometria_geojson, GRIDCODE), ...] -- una entrada por anillo, no
    por registro: mismo criterio que viz.shapefile_map (dibuja cada anillo
    de ShapeRecord.rings como un polígono independiente) en vez de asumir
    que el primer anillo es el exterior y el resto son huecos -- pyshp no
    distingue eso de forma confiable, y las subcuencas reales de SWAT no
    suelen traer huecos, así que quemar cada anillo por separado con el
    mismo GRIDCODE da el mismo resultado sin tener que resolver esa
    ambigüedad."""
    records: list[ShapeRecord] = read_subbasin_shapes(shp_path)
    geometries: list[tuple[dict, int]] = []
    for record in records:
        for ring in record.rings:
            geometry = {"type": "Polygon", "coordinates": [[list(point) for point in ring]]}
            geometries.append((geometry, record.id_value))
    return geometries


__all__ = ["SUBBASIN_ID_FIELD", "shapefile_bbox", "subbasin_geometries"]
