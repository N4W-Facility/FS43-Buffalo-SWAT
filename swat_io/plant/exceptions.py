"""Excepciones específicas del módulo de archivos plant.dat/crop.dat."""
from __future__ import annotations


class PlantDatError(Exception):
    """Error base de todo el módulo plant.dat."""


class PlantDatReadError(PlantDatError):
    """No se pudo leer o decodificar un archivo plant.dat."""


class PlantDatParseError(PlantDatError):
    """El contenido de un archivo plant.dat no pudo interpretarse."""


class PlantDatWriteError(PlantDatError):
    """No se pudo escribir un archivo plant.dat en la ruta destino."""


class PlantDatModificationError(PlantDatError):
    """Error al aplicar o escribir una modificación de un archivo plant.dat."""
