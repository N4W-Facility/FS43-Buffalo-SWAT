"""Escritura controlada de plant.dat/crop.dat.

Mismo contrato que swat_io.hru.writer / swat_io.mgt.writer: ruta destino
siempre explícita, nunca igual al archivo de origen. plant.dat es un
archivo compartido por toda la cuenca (no por HRU/subcuenca) -- ver
CLAUDE.md, aviso propio de radio de impacto para NbS con cobertura nueva.
La escritura in-place sobre el proyecto abierto vive en scenarios/nbs_apply.py.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ..common.atomic_write import atomic_write_bytes
from .exceptions import PlantDatWriteError
from .models import PlantDatFile


def write_plant_dat_file(
    plant_file: PlantDatFile,
    destination: str | Path,
    *,
    atomic: bool = True,
    create_backup: bool = False,
    allow_overwrite: bool = False,
) -> Path:
    destination = Path(destination)

    if plant_file.source_path is not None and destination.resolve() == Path(plant_file.source_path).resolve():
        raise PlantDatWriteError(
            f"La ruta destino no puede ser igual al archivo de origen ({plant_file.source_path}); "
            "especifique una ruta destino distinta (p. ej. la copia de trabajo del escenario)."
        )

    if destination.exists() and not allow_overwrite:
        raise PlantDatWriteError(
            f"{destination} ya existe; pase allow_overwrite=True para sobrescribirlo explícitamente."
        )

    try:
        data = plant_file.render().encode(plant_file.encoding)
    except (LookupError, UnicodeEncodeError) as exc:
        raise PlantDatWriteError(
            f"No se pudo codificar el contenido de {destination} con '{plant_file.encoding}': {exc}"
        ) from exc

    try:
        if atomic:
            atomic_write_bytes(destination, data, create_backup=create_backup)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if create_backup and destination.exists():
                shutil.copy2(destination, destination.with_name(destination.name + ".bak"))
            destination.write_bytes(data)
    except OSError as exc:
        raise PlantDatWriteError(f"No se pudo escribir {destination}: {exc}") from exc

    return destination
