"""Ejecución de swat2012.exe como subproceso local sobre una copia de
escenario ya configurada (paso 2 de la secuencia obligatoria de CLAUDE.md).

Sin lectura ni interpretación de output.* -- eso es responsabilidad de la
capa de resúmenes (swat_io.summary, generar_resumen_coberturas) o, a
futuro, de viz/ para la comparación línea base/escenario. Esta función solo
resuelve "SWAT terminó con error" (exit code != 0); "no se pudo parsear la
salida" es un caso de la otra capa, no de esta.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from scenarios.activity_log import log_action

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class RunResult:
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    elapsed_seconds: float


def run_scenario(
    txtinout_dir: Path,
    swat_executable: Path,
    target_executable_name: str,
    on_progress: ProgressCallback | None = None,
) -> RunResult:
    """Copia swat_executable a txtinout_dir/target_executable_name (el nombre
    que file.cio espera dentro de la carpeta de trabajo) y lo ejecuta ahí
    como subproceso, con cwd en txtinout_dir. El ejecutable configurado por
    el usuario nunca se renombra ni se modifica en su ubicación original --
    solo se copia, en cada corrida, para reflejar la ruta configurada.

    Usa Popen (no run) para poder reportar progreso en tiempo real: dos
    hilos leen stdout/stderr línea por línea a medida que el proceso las
    produce (leer un único pipe de forma síncrona mientras el otro se llena
    puede bloquear el proceso hijo, de ahí un hilo por stream) y cada línea
    dispara on_progress con el acumulado hasta ese momento -- mismo patrón
    de report_progress que ui.tasks.run_in_background ya espera, así que la
    UI no necesita ningún cambio en cómo consume el progreso, solo recibe
    mensajes más seguido.
    """
    txtinout_dir = Path(txtinout_dir)
    project_dir = txtinout_dir.parent
    target_path = txtinout_dir / target_executable_name
    shutil.copy2(swat_executable, target_path)
    log_action(project_dir, "RUN", f"Started SWAT run with executable '{swat_executable}'.")

    if on_progress is not None:
        on_progress(f"Running {target_executable_name}...")

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def report_combined_output() -> None:
        if on_progress is None:
            return
        stdout_text = "\n".join(stdout_lines)
        stderr_text = "\n".join(stderr_lines)
        on_progress(stdout_text + (("\n" + stderr_text) if stderr_text else ""))

    def pump(stream, lines: list[str]) -> None:
        for line in stream:
            lines.append(line.rstrip("\n"))
            report_combined_output()
        stream.close()

    start = time.monotonic()
    process = subprocess.Popen(
        [str(target_path)],
        cwd=txtinout_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stdout_thread = threading.Thread(target=pump, args=(process.stdout, stdout_lines), daemon=True)
    stderr_thread = threading.Thread(target=pump, args=(process.stderr, stderr_lines), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    process.wait()
    stdout_thread.join()
    stderr_thread.join()
    elapsed = time.monotonic() - start

    log_action(
        project_dir,
        "RUN",
        f"SWAT run finished: exit_code={process.returncode}, elapsed={elapsed:.1f}s.",
    )

    return RunResult(
        success=process.returncode == 0,
        exit_code=process.returncode,
        stdout="\n".join(stdout_lines),
        stderr="\n".join(stderr_lines),
        elapsed_seconds=elapsed,
    )
