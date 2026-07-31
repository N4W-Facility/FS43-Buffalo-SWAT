"""Escritura controlada de archivos .hru.

La ruta destino es siempre explícita (nunca se infiere de
``HRUFile.source_path``) y nunca se permite escribir sobre el archivo de
origen, para no sobrescribir accidentalmente la carpeta base del modelo.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ..common.atomic_write import atomic_write_bytes
from .exceptions import HRUWriteError
from .models import HRUFile


def write_hru_file(
    hru_file: HRUFile,
    destination: str | Path,
    *,
    atomic: bool = True,
    create_backup: bool = False,
    allow_overwrite: bool = False,
) -> Path:
    """Escribe ``hru_file`` en ``destination``.

    - Rechaza escribir sobre ``hru_file.source_path`` (la ruta destino
      debe ser explícita y distinta del origen).
    - Rechaza sobrescribir un archivo existente salvo ``allow_overwrite``.
    - Con ``atomic=True`` (por defecto), escribe primero en un temporal en
      la misma carpeta y reemplaza el destino solo al terminar sin error;
      si falla, el temporal se limpia y el destino no se toca.
    """
    destination = Path(destination)

    if hru_file.source_path is not None and destination.resolve() == Path(hru_file.source_path).resolve():
        raise HRUWriteError(
            f"La ruta destino no puede ser igual al archivo de origen ({hru_file.source_path}); "
            "especifique una ruta destino distinta (p. ej. la copia de trabajo del escenario)."
        )

    if destination.exists() and not allow_overwrite:
        raise HRUWriteError(
            f"{destination} ya existe; pase allow_overwrite=True para sobrescribirlo explícitamente."
        )

    try:
        data = hru_file.render().encode(hru_file.encoding)
    except (LookupError, UnicodeEncodeError) as exc:
        raise HRUWriteError(
            f"No se pudo codificar el contenido de {destination} con '{hru_file.encoding}': {exc}"
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
        raise HRUWriteError(f"No se pudo escribir {destination}: {exc}") from exc

    return destination
