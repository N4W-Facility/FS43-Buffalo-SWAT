"""Motor de procesamiento raster para la pestaña Restoration Inputs
(ver ui/tab_restoration_inputs.py + scenarios/nbs_raster_inputs.py).

Cruza un raster de cobertura (grande, puede cubrir todo el continente --
ej. Cropland Data Layer, ~15 GB) con un raster de restauración/NbS (chico,
extensión acotada a la cuenca) y el shapefile de subcuencas del proyecto,
para calcular qué % de cada clase de restauración -- dentro de cada
subcuenca -- corresponde hoy a cada cobertura real.

Sin geopandas/Fiona (misma filosofía liviana que ``viz/shapefile_reader.py``,
ver CLAUDE.md): el shapefile se sigue leyendo con pyshp
(``viz.shapefile_reader.read_subbasin_shapes``); lo único nuevo acá es
``rasterio`` (ya instalado en el env ``swat``, wrapea GDAL) para leer/
reproyectar/remuestrear los rasters.

Principio de diseño no negociable (pedido explícito del usuario): nunca
cargar un raster completo en memoria ni escribir un raster intermedio a
disco. Todo el trabajo se acota primero a la intersección geográfica
cuenca ∩ raster de restauración (nunca al raster de cobertura completo,
por más que cubra todo el continente) y después se procesa en bloques
chicos vía ``rasterio.vrt.WarpedVRT`` (reproyecta/remuestrea al vuelo,
ventana por ventana, sin materializar la salida reproyectada completa).
"""
