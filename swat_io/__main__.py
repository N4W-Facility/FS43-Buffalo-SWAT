"""CLI para generar el resumen de humedales de un modelo SWAT.

Uso:
    python -m swat_io <ruta_al_modelo>

<ruta_al_modelo> es la carpeta que contiene TxtInOut/ (ej. la carpeta
Cattaraugus_calibrated_annual). El resumen se guarda como CSV en
tool_outputs/wetland_summary.csv dentro de esa misma carpeta.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .summary import summarize_project
from .tool_outputs import save_wetland_summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera el resumen de subcuencas y humedales de un modelo SWAT."
    )
    parser.add_argument(
        "model_dir",
        type=Path,
        help="Carpeta del modelo SWAT que contiene TxtInOut/",
    )
    args = parser.parse_args()

    txtinout_dir = args.model_dir / "TxtInOut"
    df = summarize_project(txtinout_dir)
    print(f"Subcuencas: {len(df)}")
    print(df.to_string())

    csv_path = save_wetland_summary(args.model_dir, df)
    print(f"\nCSV guardado en: {csv_path}")


if __name__ == "__main__":
    main()
