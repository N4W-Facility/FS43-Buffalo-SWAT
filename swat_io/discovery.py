"""Descubrimiento de subcuencas reales dentro de una carpeta TxtInOut."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SUB_FILENAME = re.compile(r"^(\d{9})\.sub$", re.IGNORECASE)


@dataclass(frozen=True)
class SubbasinFiles:
    subbasin_id: int
    sub_file: Path
    pnd_file: Path


def discover_subbasins(txtinout_dir: Path) -> list[SubbasinFiles]:
    """Lista las subcuencas reales de un TxtInOut, a partir de sus .sub.

    La fuente de verdad es el conjunto de archivos .sub (nombrados
    NNNNN0000.sub, donde NNNNN es el id de subcuenca). El archivo
    000000000.pnd, si existe, es una plantilla de ArcSWAT sin subcuenca
    real asociada y se ignora deliberadamente al no tener un .sub
    correspondiente.
    """
    subbasins: list[SubbasinFiles] = []
    for sub_file in txtinout_dir.iterdir():
        match = _SUB_FILENAME.match(sub_file.name)
        if not match:
            continue
        subbasin_id = int(match.group(1)) // 10000
        pnd_file = txtinout_dir / f"{subbasin_id:05d}0000.pnd"
        if not pnd_file.exists():
            raise FileNotFoundError(
                f"Subcuenca {subbasin_id}: no se encontró {pnd_file.name} "
                f"junto a {sub_file.name}"
            )
        subbasins.append(SubbasinFiles(subbasin_id, sub_file, pnd_file))
    return sorted(subbasins, key=lambda s: s.subbasin_id)
