"""Escritura atómica de archivos de texto SWAT, con respaldo opcional.

Se escribe primero en un archivo temporal en la misma carpeta destino y
solo se reemplaza el destino final (``os.replace``, atómico en el mismo
sistema de archivos) cuando la escritura del temporal terminó sin errores.
Si algo falla, el temporal se limpia y el destino original queda intacto.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


def atomic_write_bytes(
    destination: str | Path,
    data: bytes,
    *,
    create_backup: bool = False,
) -> Path:
    """Escribe ``data`` en ``destination`` de forma atómica.

    Crea la carpeta destino si no existe. Si ``create_backup`` es True y
    ``destination`` ya existe, se copia primero a ``destination`` + ``.bak``
    antes de reemplazarlo.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    if create_backup and destination.exists():
        backup_path = destination.with_name(destination.name + ".bak")
        shutil.copy2(destination, backup_path)

    fd, tmp_name = tempfile.mkstemp(
        dir=str(destination.parent),
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as tmp_file:
            tmp_file.write(data)
        os.replace(tmp_path, destination)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return destination
