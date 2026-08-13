"""Lectura de shapefiles (.shp) de subcuencas y reach, sin matplotlib.

Solo lo necesario para el mapa estático de la pestaña Results: geometría
(polígonos para subcuencas, polilíneas para reach) más el campo de id que
hace match con la numeración de output.rch. El nombre de ese campo NO es
el mismo en los dos shapefiles pese a identificar el mismo tramo/subcuenca
(confirmado explícitamente por el usuario, verificado contra shapefiles
reales del proyecto): GRIDCODE en el shp de subcuencas, ARCID en el shp de
reach.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import shapefile

SUBBASIN_ID_FIELD = "GRIDCODE"
REACH_ID_FIELD = "ARCID"


class ShapefileReadError(ValueError):
    """El .shp no existe o no tiene el campo de id esperado."""


@dataclass(frozen=True)
class ShapeRecord:
    id_value: int
    # Una lista de anillos (cada uno, una lista de puntos (x, y)) -- pyshp
    # separa geometrías multi-parte (islas, polígonos con huecos, tramos
    # con múltiples segmentos) en shape.parts; ya vienen separadas acá para
    # que el renderer (viz.shapefile_map) no tenga que conocer pyshp.
    rings: list[list[tuple[float, float]]]


def _read_shapes(path: Path | str, id_field: str) -> list[ShapeRecord]:
    path = Path(path)
    if not path.is_file():
        raise ShapefileReadError(f"Shapefile not found: {path}")

    reader = shapefile.Reader(str(path))
    field_names = [field[0] for field in reader.fields[1:]]  # fields[0] es DeletionFlag, no es un campo real
    if id_field not in field_names:
        raise ShapefileReadError(f"{path.name}: does not have the expected field '{id_field}'")

    records: list[ShapeRecord] = []
    for shape_record in reader.iterShapeRecords():
        id_value = int(shape_record.record[id_field])
        points = shape_record.shape.points
        part_starts = list(shape_record.shape.parts) + [len(points)]
        rings = [points[part_starts[i] : part_starts[i + 1]] for i in range(len(part_starts) - 1)]
        records.append(ShapeRecord(id_value=id_value, rings=rings))
    return records


def read_subbasin_shapes(path: Path | str) -> list[ShapeRecord]:
    """Polígonos de subcuenca, indexados por GRIDCODE."""
    return _read_shapes(path, SUBBASIN_ID_FIELD)


def read_reach_shapes(path: Path | str) -> list[ShapeRecord]:
    """Polilíneas de reach, indexadas por ARCID."""
    return _read_shapes(path, REACH_ID_FIELD)
