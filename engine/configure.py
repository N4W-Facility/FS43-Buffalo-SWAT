from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

import pandas as pd

from swat_io.pnd_parser import write_wetland_params

ProgressCallback = Callable[[int, int], None]


def _count_files(directory: Path) -> int:
    return sum(1 for path in directory.rglob("*") if path.is_file())


def create_working_scenario(
    project_dir: Path,
    reference_dir: Path,
    scenario_name: str,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """Copia toda la carpeta de referencia (TablesIn/TablesOut/TxtInOut/...)
    a project_dir/scenario_name. La carpeta de referencia nunca se modifica.

    Es el paso 1 de la secuencia obligatoria de CLAUDE.md, disparado por el
    botón "Cargar" (ver ui/project_window.py). Si se pasa `on_progress`, se
    llama con (archivos_copiados, total_archivos) después de cada archivo,
    para que la UI pueda mostrar avance sin bloquear la corrida en un hilo
    de trabajo.
    """
    scenario_dir = Path(project_dir) / scenario_name
    if scenario_dir.exists():
        raise FileExistsError(f"Ya existe una carpeta de escenario para {scenario_name!r}: {scenario_dir}")

    reference_dir = Path(reference_dir)
    total_files = _count_files(reference_dir)
    copied = 0

    def _copy_with_progress(src: str, dst: str) -> None:
        nonlocal copied
        shutil.copy2(src, dst)
        copied += 1
        if on_progress is not None:
            on_progress(copied, total_files)

    shutil.copytree(reference_dir, scenario_dir, copy_function=_copy_with_progress)
    return scenario_dir


def apply_draft_to_pnd(txtinout_dir: Path, draft: pd.DataFrame) -> None:
    """Escribe cada fila del borrador en el .pnd real de su subcuenca,
    dentro de la copia de trabajo del escenario (nunca en la referencia).

    Es lo que ejecuta el botón "Guardar" de la ventana Wetlands.
    """
    txtinout_dir = Path(txtinout_dir)
    field_ids = list(draft.columns)
    for subbasin_id, row in draft.iterrows():
        pnd_file = txtinout_dir / f"{int(subbasin_id):05d}0000.pnd"
        write_wetland_params(pnd_file, {field_id: float(row[field_id]) for field_id in field_ids})
