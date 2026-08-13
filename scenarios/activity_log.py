"""Log cronológico de actividad de toda la app, para auditoría.

Complementa (no reemplaza) los reportes puntuales que ya escriben algunas
operaciones (``batch_report.json``, ``nbs_area_batch_report.csv``,
``nbs_apply_report_*.csv``, etc.): esos siguen siendo la fuente detallada
tabular de una operación puntual; este log da la vista cronológica de "qué
pasó y cuándo" en un solo lugar, para cualquier acción de la app que abra,
edite o corra algo sobre el proyecto -- pedido explícito del usuario,
2026-08-13.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from swat_io.tool_outputs import tool_outputs_dir

_LOG_FILENAME = "activity_log.txt"


def log_action(project_dir: str | Path, category: str, message: str) -> None:
    """Agrega una línea al log de actividad del proyecto.

    Vive en ``tool_outputs/activity_log.txt``, append-only: nunca se
    sobrescribe ni se rota, se va acumulando durante toda la vida del
    proyecto. Nunca lanza -- un fallo al escribir el log (disco lleno,
    permisos) no debe interrumpir la operación real que está siendo
    registrada, así que cualquier error de E/S se descarta en silencio.
    """
    try:
        log_path = tool_outputs_dir(project_dir) / _LOG_FILENAME
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [{category}] {message}\n")
    except OSError:
        pass
