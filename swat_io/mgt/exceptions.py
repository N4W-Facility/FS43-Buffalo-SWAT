"""Excepciones específicas del módulo de archivos .mgt."""
from __future__ import annotations


class MGTError(Exception):
    """Error base de todo el módulo .mgt."""


class MGTReadError(MGTError):
    """No se pudo leer o decodificar un archivo .mgt."""


class MGTParseError(MGTError):
    """El contenido de un archivo .mgt no pudo interpretarse."""


class MGTWriteError(MGTError):
    """No se pudo escribir un archivo .mgt en la ruta destino."""


class MGTModificationError(MGTError):
    """Error al aplicar o escribir una modificación de un archivo .mgt."""
