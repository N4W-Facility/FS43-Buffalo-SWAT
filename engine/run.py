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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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
    """
    txtinout_dir = Path(txtinout_dir)
    target_path = txtinout_dir / target_executable_name
    shutil.copy2(swat_executable, target_path)

    if on_progress is not None:
        on_progress(f"Running {target_executable_name}...")

    start = time.monotonic()
    process = subprocess.run(
        [str(target_path)],
        cwd=txtinout_dir,
        capture_output=True,
        text=True,
    )
    elapsed = time.monotonic() - start

    return RunResult(
        success=process.returncode == 0,
        exit_code=process.returncode,
        stdout=process.stdout,
        stderr=process.stderr,
        elapsed_seconds=elapsed,
    )
