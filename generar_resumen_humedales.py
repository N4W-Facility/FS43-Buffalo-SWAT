"""Script sencillo: genera el CSV de resumen de humedales (parámetros .pnd) de un escenario.

Recibe la ruta de un escenario (la carpeta que contiene TxtInOut/, no
TxtInOut en sí) y escribe wetland_summary.csv en su carpeta tool_outputs/
(misma convención que swat_io.tool_outputs.save_wetland_summary y que
generar_resumen_coberturas.py).

Uso:
    python generar_resumen_humedales.py "D:\\SWAT\\Proyecto\\Escenario1"
"""
from __future__ import annotations

import sys
from pathlib import Path

from swat_io.summary import summarize_project
from swat_io.tool_outputs import save_wetland_summary


def generar_resumen_humedales(escenario_dir: Path) -> Path:
    txtinout_dir = escenario_dir / "TxtInOut"
    df = summarize_project(txtinout_dir)
    return save_wetland_summary(escenario_dir, df)


if __name__ == "__main__":
    if len(sys.argv) == 2:
        escenario_dir = Path(sys.argv[1])
    else:
        # Ruta de prueba por defecto cuando se ejecuta sin argumentos (p. ej. desde el editor).
        escenario_dir = Path(r"Y:\Server-UserFolder\Escritorio\N4W-Bufallo\03-Models\Buffalo\Buffalo_calibrated_annual")

    csv_path = generar_resumen_humedales(escenario_dir)
    print(f"Listo: {csv_path}")
