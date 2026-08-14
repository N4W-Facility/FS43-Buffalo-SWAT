"""Descubrimiento rápido de qué códigos existen en un raster dentro de la
grilla de trabajo -- para poblar la tabla de cruce CDL->CPNM en la UI
*antes* de correr el cruce completo. Deliberadamente aproximado: lee la
ventana de trabajo decimada (menos píxeles que la grilla real) en vez de
recorrerla bloque por bloque a resolución completa -- alcanza para saber
qué códigos aparecen, no hace falta el conteo exacto acá (eso lo da
compute_crosstab)."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT

from .grid import TargetGrid

# Techo de píxeles a leer para el escaneo -- una grilla de trabajo real
# (acotada a cuenca ∩ raster de restauración) rara vez supera esto, pero
# si lo hace, se decima para que el escaneo siga siendo rápido.
_MAX_SCAN_PIXELS = 4_000_000


def scan_unique_values(raster_path: str | Path, grid: TargetGrid) -> dict[int, int]:
    """{código: cantidad de píxeles decimados} -- las cantidades son
    aproximadas (para orientar, no para el CSV final)."""
    scale = min(1.0, math.sqrt(_MAX_SCAN_PIXELS / max(1, grid.width * grid.height)))
    out_width = max(1, round(grid.width * scale))
    out_height = max(1, round(grid.height * scale))

    with rasterio.open(raster_path) as src, WarpedVRT(
        src, crs=grid.crs, transform=grid.transform, width=grid.width, height=grid.height,
        resampling=Resampling.nearest,
    ) as vrt:
        data = vrt.read(1, out_shape=(out_height, out_width), resampling=Resampling.nearest)

    values, counts = np.unique(data, return_counts=True)
    return dict(zip(values.tolist(), counts.tolist()))
