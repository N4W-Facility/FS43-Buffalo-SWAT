"""project.json: metadata persistida junto a un proyecto.

Un "proyecto", en el sentido de este módulo, es una única carpeta que
contiene TxtInOut/ directamente — no un contenedor de varios escenarios
(eso es lo que lista swat_io.discovery.discover_scenario_folders, usado
por el futuro flujo de parametrización, no por este).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from swat_io.common.atomic_write import atomic_write_bytes

PROJECT_FILE = "project.json"


@dataclass
class SummaryEntry:
    """Un resumen (Wetlands o HRU) cacheado en project.json.

    ``stats`` es lo que ya sea JSON-serializable de por sí (los campos de
    swat_io.stats.WetlandStats/HruStats, con SimulationPeriod aplanado a
    dict) — este módulo no interpreta su contenido.
    """

    generated_at: str
    stats: dict = field(default_factory=dict)


@dataclass
class ProjectMetadata:
    name: str = ""
    description: str = ""
    wetlands: SummaryEntry | None = None
    hru: SummaryEntry | None = None


def is_valid_project_dir(path: Path | str) -> bool:
    """Un proyecto válido es cualquier carpeta que contenga TxtInOut/ directamente."""
    return (Path(path) / "TxtInOut").is_dir()


def project_file_path(project_dir: Path | str) -> Path:
    return Path(project_dir) / PROJECT_FILE


def load_project(project_dir: Path | str) -> ProjectMetadata:
    """Carga project.json.

    Si el archivo no existe o está corrupto (JSON inválido o con una forma
    inesperada), devuelve metadata vacía en vez de lanzar: es el caso
    "crear vacío" pedido por el usuario, y un project.json roto no debe
    impedir reabrir el proyecto.
    """
    path = project_file_path(project_dir)
    if not path.exists():
        return ProjectMetadata()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ProjectMetadata()
    return _metadata_from_dict(data)


def save_project(project_dir: Path | str, metadata: ProjectMetadata) -> Path:
    """Persiste metadata en project.json de forma atómica."""
    path = project_file_path(project_dir)
    payload = _metadata_to_dict(metadata)
    atomic_write_bytes(path, json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"))
    return path


def _metadata_to_dict(metadata: ProjectMetadata) -> dict:
    summary: dict = {}
    if metadata.wetlands is not None:
        summary["wetlands"] = asdict(metadata.wetlands)
    if metadata.hru is not None:
        summary["hru"] = asdict(metadata.hru)
    return {
        "name": metadata.name,
        "description": metadata.description,
        "summary": summary,
    }


def _metadata_from_dict(data: object) -> ProjectMetadata:
    if not isinstance(data, dict):
        return ProjectMetadata()
    summary = data.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    return ProjectMetadata(
        name=data.get("name") or "",
        description=data.get("description") or "",
        wetlands=_summary_entry_from_dict(summary.get("wetlands")),
        hru=_summary_entry_from_dict(summary.get("hru")),
    )


def _summary_entry_from_dict(data: object) -> SummaryEntry | None:
    if not isinstance(data, dict) or not isinstance(data.get("generated_at"), str):
        return None
    stats = data.get("stats")
    stats = stats if isinstance(stats, dict) else {}
    return SummaryEntry(generated_at=data["generated_at"], stats=stats)
