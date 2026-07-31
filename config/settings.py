"""Punto único de acceso a configuración: tema, strings, layout de formularios y rutas persistidas por el usuario.

Ningún widget de ui/ debe leer resources/ o el archivo de configuración
directamente: todo pasa por ConfigManager.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"
DEFAULT_CONFIG_FILE = Path.home() / ".swat_wetlands" / "config.json"


@dataclass
class AppPaths:
    """Rutas sensibles a la máquina del usuario. Ningún valor por defecto aquí: se piden y validan en la UI."""

    swat_executable: Path | None = None
    base_models_root: Path | None = None
    workspace_root: Path | None = None
    target_executable_name: str = "swatUser.exe"

    def is_complete(self) -> bool:
        return all([self.swat_executable, self.base_models_root, self.workspace_root])


_PATH_FIELDS = ("swat_executable", "base_models_root", "workspace_root")


class ConfigManager:
    def __init__(
        self,
        resources_dir: Path = RESOURCES_DIR,
        config_file: Path | None = None,
    ) -> None:
        self._resources_dir = resources_dir
        self._config_file = config_file if config_file is not None else DEFAULT_CONFIG_FILE
        self.theme: dict = {}
        self.strings: dict = {}
        self.paths: AppPaths = AppPaths()

    def load_all(self) -> None:
        self.theme = self._load_json(self._resources_dir / "theme" / "swat_light.json")
        self.strings = self._load_json(self._resources_dir / "strings" / "en.json")
        self.paths = self._load_paths()

    def theme_path(self) -> Path:
        return self._resources_dir / "theme" / "swat_light.json"

    def load_layout(self, form_name: str) -> dict:
        import yaml

        layout_file = self._resources_dir / "layout" / f"{form_name}.yaml"
        with layout_file.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def text(self, key: str) -> str:
        return self.strings.get(key, key)

    def save_paths(self, paths: AppPaths) -> None:
        self._config_file.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(paths)
        for field in _PATH_FIELDS:
            data[field] = str(data[field]) if data[field] is not None else None
        with self._config_file.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self.paths = paths

    def _load_paths(self) -> AppPaths:
        if not self._config_file.exists():
            return AppPaths()
        data = self._load_json(self._config_file)
        kwargs: dict = {}
        for field in _PATH_FIELDS:
            value = data.get(field)
            kwargs[field] = Path(value) if value else None
        if data.get("target_executable_name"):
            kwargs["target_executable_name"] = data["target_executable_name"]
        return AppPaths(**kwargs)

    @staticmethod
    def _load_json(path: Path) -> dict:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)


def validate_app_paths(swat_executable: Path, base_models_root: Path, workspace_root: Path) -> str | None:
    """Devuelve una clave de error de es.json si alguna ruta es inválida, o None si todas lo son."""
    if not Path(swat_executable).is_file():
        return "config.error.invalid_executable"
    if not Path(base_models_root).is_dir() or not Path(workspace_root).is_dir():
        return "config.error.invalid_directory"
    return None
