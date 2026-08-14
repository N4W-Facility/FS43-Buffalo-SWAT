"""Motor central: cruza cobertura x restauración x subcuenca, bloque por
bloque, sobre la grilla destino ya acotada (ver raster_io.grid). Nunca lee
un raster completo ni escribe nada a disco -- devuelve solo la tabla de
conteos (chica: como mucho unos cientos de combinaciones distintas de
subcuenca/clase/cobertura, nunca del tamaño del raster).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window, transform as window_transform

from .grid import TargetGrid

DEFAULT_BLOCK_SIZE = 1024
# GRIDCODE real de una subcuenca SWAT siempre es >= 1 en los proyectos de
# este repo, así que 0 sirve como valor de relleno "fuera de cualquier
# subcuenca" sin ambigüedad.
_SUBBASIN_FILL = 0
_BACKGROUND_RESTORATION_CLASS = 0

ProgressCallback = Callable[[int, int], None]

# (subbasin_id, restoration_class, land_cover_code) -> cantidad de píxeles
CrosstabCounts = dict[tuple[int, int, int], int]


@dataclass(frozen=True)
class CrosstabResult:
    counts: CrosstabCounts
    pixel_area_ha: float


def _iter_blocks(width: int, height: int, block_size: int) -> Iterator[Window]:
    for row_off in range(0, height, block_size):
        h = min(block_size, height - row_off)
        for col_off in range(0, width, block_size):
            w = min(block_size, width - col_off)
            yield Window(col_off, row_off, w, h)


def compute_crosstab(
    land_cover_path: str | Path,
    restoration_path: str | Path,
    subbasin_geometries: list[tuple[dict, int]],
    grid: TargetGrid,
    *,
    block_size: int = DEFAULT_BLOCK_SIZE,
    on_progress: ProgressCallback | None = None,
) -> CrosstabResult:
    """``land_cover_path`` puede ser un raster gigante (ej. todo un
    continente): WarpedVRT reproyecta/remuestrea al vuelo, ventana por
    ventana, así que cada bloque solo dispara una lectura acotada del
    raster fuente -- nunca se toca el archivo completo, y nunca se
    construye una versión reproyectada completa en memoria ni en disco.

    Remuestreo nearest-neighbor obligatorio en ambos rasters de entrada:
    son categóricos (códigos de clase), promediarlos no tiene sentido.
    """
    counts: Counter[tuple[int, int, int]] = Counter()
    blocks = list(_iter_blocks(grid.width, grid.height, block_size))
    total = len(blocks)

    with (
        rasterio.open(land_cover_path) as land_cover_src,
        rasterio.open(restoration_path) as restoration_src,
        WarpedVRT(
            land_cover_src, crs=grid.crs, transform=grid.transform, width=grid.width, height=grid.height,
            resampling=Resampling.nearest,
        ) as land_cover_vrt,
        WarpedVRT(
            restoration_src, crs=grid.crs, transform=grid.transform, width=grid.width, height=grid.height,
            resampling=Resampling.nearest,
        ) as restoration_vrt,
    ):
        for index, window in enumerate(blocks):
            block_transform = window_transform(window, grid.transform)

            subbasin_block = rasterize(
                subbasin_geometries,
                out_shape=(window.height, window.width),
                transform=block_transform,
                fill=_SUBBASIN_FILL,
                dtype="int32",
            )
            # Bloque fuera de toda subcuenca (frecuente en los bordes del
            # rectángulo de trabajo, que es la intersección de bounding
            # boxes, no la forma real de la cuenca): nada que cruzar acá,
            # se salta sin tocar los rasters de entrada para este bloque.
            if subbasin_block.any():
                restoration_block = restoration_vrt.read(1, window=window)
                mask = (subbasin_block != _SUBBASIN_FILL) & (restoration_block != _BACKGROUND_RESTORATION_CLASS)
                if mask.any():
                    land_cover_block = land_cover_vrt.read(1, window=window)
                    keys = np.stack(
                        [
                            subbasin_block[mask].astype(np.int64),
                            restoration_block[mask].astype(np.int64),
                            land_cover_block[mask].astype(np.int64),
                        ],
                        axis=1,
                    )
                    uniques, block_counts = np.unique(keys, axis=0, return_counts=True)
                    for (sub, restoration_class, land_cover_code), count in zip(
                        uniques.tolist(), block_counts.tolist()
                    ):
                        counts[(sub, restoration_class, land_cover_code)] += count

            if on_progress is not None:
                on_progress(index + 1, total)

    pixel_area_ha = (grid.pixel_size**2) / 10000
    return CrosstabResult(counts=dict(counts), pixel_area_ha=pixel_area_ha)
