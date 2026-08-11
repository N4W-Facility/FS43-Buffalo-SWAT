"""Escritura controlada de archivos .mgt.

La ruta destino es siempre explícita (nunca se infiere de
``MGTFile.source_path``) y nunca se permite escribir sobre el archivo de
origen, para no sobrescribir accidentalmente la carpeta base del modelo --
mismo contrato que swat_io.hru.writer.write_hru_file. La escritura in-place
sobre el proyecto abierto (mismo patrón ya aceptado para Wetlands/HRUs,
ver CLAUDE.md) vive en scenarios/nbs_apply.py, no aquí.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ..common.atomic_write import atomic_write_bytes
from .exceptions import MGTWriteError
from .models import MGTFile


def write_mgt_file(
    mgt_file: MGTFile,
    destination: str | Path,
    *,
    atomic: bool = True,
    create_backup: bool = False,
    allow_overwrite: bool = False,
) -> Path:
    destination = Path(destination)

    if mgt_file.source_path is not None and destination.resolve() == Path(mgt_file.source_path).resolve():
        raise MGTWriteError(
            f"La ruta destino no puede ser igual al archivo de origen ({mgt_file.source_path}); "
            "especifique una ruta destino distinta (p. ej. la copia de trabajo del escenario)."
        )

    if destination.exists() and not allow_overwrite:
        raise MGTWriteError(
            f"{destination} ya existe; pase allow_overwrite=True para sobrescribirlo explícitamente."
        )

    try:
        data = mgt_file.render().encode(mgt_file.encoding)
    except (LookupError, UnicodeEncodeError) as exc:
        raise MGTWriteError(
            f"No se pudo codificar el contenido de {destination} con '{mgt_file.encoding}': {exc}"
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
        raise MGTWriteError(f"No se pudo escribir {destination}: {exc}") from exc

    return destination
