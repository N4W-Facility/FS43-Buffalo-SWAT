"""Cálculo de la grilla de trabajo destino: el rectángulo (en el CRS del
shapefile de subcuencas, que siempre manda -- ver raster_io.prj) donde
realmente hay algo que cruzar, al tamaño de píxel más fino de los rasters
de entrada.

Acotar la extensión antes de leer nada es lo que evita tener que tocar un
raster de cobertura de continente entero (~15 GB): el rectángulo de
trabajo nunca es más grande que la intersección cuenca ∩ raster de
restauración (que en la práctica es chico), sin importar cuánto raster de
cobertura haya alrededor.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.warp import calculate_default_transform, transform_bounds

BBox = tuple[float, float, float, float]  # (minx, miny, maxx, maxy)


class NoOverlapError(ValueError):
    """La cuenca y los rasters de entrada no se solapan en el CRS destino
    -- no hay nada que cruzar (ej. rutas equivocadas, o proyecto/rasters de
    zonas distintas)."""


@dataclass(frozen=True)
class TargetGrid:
    crs: CRS
    transform: Affine
    width: int
    height: int
    pixel_size: float  # metros, píxel cuadrado

    @property
    def bounds(self) -> BBox:
        minx, maxy = self.transform.c, self.transform.f
        maxx = minx + self.width * self.pixel_size
        miny = maxy - self.height * self.pixel_size
        return (minx, miny, maxx, maxy)


def _bounds_in_target_crs(raster_path: Path, target_crs: CRS) -> tuple[BBox, float]:
    """Bounding box del raster reproyectado al CRS destino, y su tamaño de
    píxel nativo también reproyectado (para poder comparar resoluciones de
    rasters en CRS distintos en las mismas unidades)."""
    with rasterio.open(raster_path) as ds:
        bounds_native = ds.bounds
        transform, width, height = calculate_default_transform(
            ds.crs, target_crs, ds.width, ds.height, *bounds_native
        )
        bounds = transform_bounds(ds.crs, target_crs, *bounds_native)
        pixel_size = min(abs(transform.a), abs(transform.e))
    return bounds, pixel_size


def _intersect(*boxes: BBox) -> BBox:
    minx = max(box[0] for box in boxes)
    miny = max(box[1] for box in boxes)
    maxx = min(box[2] for box in boxes)
    maxy = min(box[3] for box in boxes)
    return minx, miny, maxx, maxy


def compute_target_grid(shapefile_bbox: BBox, target_crs: CRS, raster_paths: list[Path]) -> TargetGrid:
    """``shapefile_bbox`` ya debe estar en ``target_crs`` (el shapefile de
    subcuencas siempre está en su propio CRS, que es justamente
    ``target_crs`` -- no hace falta reproyectarlo)."""
    raster_bounds: list[BBox] = []
    pixel_sizes: list[float] = []
    for path in raster_paths:
        bounds, pixel_size = _bounds_in_target_crs(path, target_crs)
        raster_bounds.append(bounds)
        pixel_sizes.append(pixel_size)

    minx, miny, maxx, maxy = _intersect(shapefile_bbox, *raster_bounds)
    if minx >= maxx or miny >= maxy:
        raise NoOverlapError(
            "The subbasin shapefile and the input rasters do not overlap in the shapefile's coordinate system."
        )

    pixel_size = min(pixel_sizes)
    width = max(1, math.ceil((maxx - minx) / pixel_size))
    height = max(1, math.ceil((maxy - miny) / pixel_size))
    transform = Affine(pixel_size, 0.0, minx, 0.0, -pixel_size, maxy)

    return TargetGrid(crs=target_crs, transform=transform, width=width, height=height, pixel_size=pixel_size)
