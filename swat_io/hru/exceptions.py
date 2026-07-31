"""Excepciones específicas del módulo de archivos .hru."""
from __future__ import annotations


class HRUError(Exception):
    """Error base de todo el módulo .hru."""


class HRUReadError(HRUError):
    """No se pudo leer o decodificar un archivo .hru."""


class HRUParseError(HRUError):
    """El contenido de un archivo .hru no pudo interpretarse."""


class HRUWriteError(HRUError):
    """No se pudo escribir un archivo .hru en la ruta destino."""


class HRUValidationError(HRUError):
    """Error irrecuperable durante la validación de un archivo .hru."""


class HRUModificationError(HRUError):
    """Error al aplicar o escribir una modificación de parámetros .hru."""
