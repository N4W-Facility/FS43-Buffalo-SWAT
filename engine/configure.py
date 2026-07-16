from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from scenarios.draft import draft_csv_path, read_draft
from scenarios.models import Project
from swat_io.pnd_parser import write_wetland_params


@dataclass(frozen=True)
class ConfigureResult:
    scenario_dir: Path
    txtinout_dir: Path
    params_csv: Path


def configure_scenario(
    project: Project, scenario_name: str, swat_executable: Path, target_executable_name: str
) -> ConfigureResult:
    """Materializa un escenario: copia TxtInOut, aplica el borrador a los
    .pnd de la copia, y coloca el ejecutable configurado.

    Implementa los pasos 1-3 de la secuencia obligatoria de CLAUDE.md. No
    invoca el subproceso de SWAT.
    """
    draft_path = draft_csv_path(project, scenario_name)
    if not draft_path.exists():
        raise FileNotFoundError(f"No existe un borrador para el escenario {scenario_name!r}.")
    draft = read_draft(draft_path)

    scenario_dir = project.project_dir / scenario_name
    txtinout_dir = scenario_dir / "TxtInOut"
    if txtinout_dir.exists():
        raise FileExistsError(
            f"Ya existe una carpeta de trabajo para {scenario_name!r}: {txtinout_dir}"
        )
    shutil.copytree(project.base_txtinout_dir, txtinout_dir)

    field_ids = list(draft.columns)
    for subbasin_id, row in draft.iterrows():
        pnd_file = txtinout_dir / f"{int(subbasin_id):05d}0000.pnd"
        write_wetland_params(pnd_file, {field_id: float(row[field_id]) for field_id in field_ids})

    shutil.copy2(swat_executable, txtinout_dir / target_executable_name)

    tool_outputs_dir = scenario_dir / "tool_outputs"
    tool_outputs_dir.mkdir(parents=True, exist_ok=True)
    params_csv = tool_outputs_dir / "scenario_params.csv"
    shutil.move(str(draft_path), str(params_csv))

    return ConfigureResult(scenario_dir=scenario_dir, txtinout_dir=txtinout_dir, params_csv=params_csv)
