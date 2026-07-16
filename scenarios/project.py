from __future__ import annotations

from pathlib import Path

from .models import Project


def open_or_create_project(
    workspace_root: Path, watershed: str, base_model_dir: Path, base_txtinout_dir: Path
) -> Project:
    """Abre (o crea si no existe) la carpeta de proyecto de una cuenca."""
    project_dir = Path(workspace_root) / watershed
    project_dir.mkdir(parents=True, exist_ok=True)
    return Project(
        watershed=watershed,
        base_model_dir=Path(base_model_dir),
        base_txtinout_dir=Path(base_txtinout_dir),
        project_dir=project_dir,
    )
