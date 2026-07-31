"""Script sencillo: genera el CSV de coberturas por subcuenca de un escenario.

Recibe la ruta de un escenario (la carpeta que contiene TxtInOut/, no
TxtInOut en sí) y escribe land_use_by_subbasin.csv en su carpeta
tool_outputs/ (misma convención que swat_io.tool_outputs.save_wetland_summary).

Uso:
    python generar_resumen_coberturas.py "D:\\SWAT\\Proyecto\\Escenario1"
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from swat_io.discovery import discover_subbasins
from swat_io.hru import (
    add_land_use_area,
    build_hru_summary,
    export_land_use_summary_csv,
    parse_hru_directory,
    summarize_land_use_by_subbasin,
)
from swat_io.sub_parser import parse_sub_file
from swat_io.tool_outputs import tool_outputs_dir


def _areas_por_subcuenca(txtinout_dir: Path) -> pd.DataFrame:
    """Área real (sub_km2) de cada subcuenca, leída de los .sub."""
    filas = [
        {"subbasin": archivos.subbasin_id, "sub_km2": parse_sub_file(archivos.sub_file, archivos.subbasin_id).area_km2}
        for archivos in discover_subbasins(txtinout_dir)
    ]
    return pd.DataFrame(filas, columns=["subbasin", "sub_km2"])


def build_land_use_summary(escenario_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Escanea TxtInOut una sola vez y devuelve (resumen_hru, resumen_coberturas).

    resumen_hru es la salida cruda de build_hru_summary (una fila por HRU),
    útil para estadísticas agregadas (conteo de HRU, coberturas distintas)
    sin tener que volver a escanear los .hru. resumen_coberturas es la tabla
    que generar_resumen_coberturas() exporta a CSV.
    """
    txtinout_dir = escenario_dir / "TxtInOut"

    resultado = parse_hru_directory(txtinout_dir)
    for error in resultado.errors:
        print(f"Aviso: no se pudo leer {error.path.name}: {error.message}")

    resumen_hru = build_hru_summary(resultado.files)
    resumen_coberturas = summarize_land_use_by_subbasin(resumen_hru)

    areas = _areas_por_subcuenca(txtinout_dir)
    resumen_coberturas = add_land_use_area(resumen_coberturas, areas)

    return resumen_hru, resumen_coberturas


def generar_resumen_coberturas(escenario_dir: Path) -> Path:
    _, resumen_coberturas = build_land_use_summary(escenario_dir)
    destino = tool_outputs_dir(escenario_dir) / "land_use_by_subbasin.csv"
    return export_land_use_summary_csv(resumen_coberturas, destino)


if __name__ == "__main__":
    if len(sys.argv) == 2:
        escenario_dir = Path(sys.argv[1])
    else:
        # Ruta de prueba por defecto cuando se ejecuta sin argumentos (p. ej. desde el editor).
        escenario_dir = Path(r"Y:\Server-UserFolder\Escritorio\N4W-Bufallo\03-Models\Buffalo\Buffalo_calibrated_annual")

    csv_path = generar_resumen_coberturas(escenario_dir)
    print(f"Listo: {csv_path}")
