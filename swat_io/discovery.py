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


_CALIBRATED_DIRNAME = re.compile(r"^[A-Za-z0-9]+_calibrated_.+$")


@dataclass(frozen=True)
class BaseModelInfo:
    watershed: str
    model_dir: Path
    txtinout_dir: Path


def discover_base_models(base_models_root: Path) -> list["BaseModelInfo"]:
    """Lista los modelos calibrados bajo base_models_root, uno por cuenca.

    Para cada subcarpeta de primer nivel (una por cuenca), busca una
    carpeta hija que siga la convención "{Watershed}_calibrated_*" y
    contenga TxtInOut/. Cuencas sin modelo calibrado detectable se omiten.
    """
    base_models_root = Path(base_models_root)
    models: list[BaseModelInfo] = []
    if not base_models_root.is_dir():
        return models
    for watershed_dir in sorted(base_models_root.iterdir()):
        if not watershed_dir.is_dir():
            continue
        for candidate in sorted(watershed_dir.iterdir()):
            if not candidate.is_dir() or not _CALIBRATED_DIRNAME.match(candidate.name):
                continue
            txtinout_dir = candidate / "TxtInOut"
            if txtinout_dir.is_dir():
                models.append(BaseModelInfo(watershed_dir.name, candidate, txtinout_dir))
                break
    return models


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
