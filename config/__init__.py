"""Configuración de la app: rutas persistidas por el usuario, tema/strings/layout y mapeo cuenca->outlet."""
from .settings import ConfigManager
from .watersheds import WATERSHED_OUTLETS

__all__ = ["ConfigManager", "WATERSHED_OUTLETS"]
