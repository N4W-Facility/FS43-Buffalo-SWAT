from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

WETLAND_ABBREVIATIONS: tuple[str, ...] = ("WET_LS", "WET_MS", "WET_HS")


@dataclass(frozen=True)
class Project:
    watershed: str
    base_model_dir: Path
    base_txtinout_dir: Path
    project_dir: Path


def build_scenario_name(watershed: str, abbreviation: str, timestep: str) -> str:
    """Compone el nombre de escenario {Watershed}_{Abbrev}_{timestep} de CLAUDE.md."""
    if abbreviation not in WETLAND_ABBREVIATIONS:
        raise ValueError(
            f"Abreviación inválida: {abbreviation!r}. Debe ser una de {WETLAND_ABBREVIATIONS}."
        )
    if not timestep or not timestep.strip():
        raise ValueError("El periodo (timestep) no puede estar vacío.")
    return f"{watershed}_{abbreviation}_{timestep.strip()}"
