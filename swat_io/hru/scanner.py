"""Descubrimiento e inventario masivo de archivos .hru bajo un TxtInOut."""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from .exceptions import HRUError
from .models import HRUFile
from .parser import parse_hru_file

_DEFAULT_EXCLUDE_PATTERNS: tuple[str, ...] = ("*.bak", "*.tmp", "~*")


def _is_temp_or_backup(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered.endswith(".bak")
        or lowered.endswith(".tmp")
        or lowered.startswith("~$")
        or lowered.startswith(".")
    )


def _is_inside_hidden_folder(path: Path, root: Path) -> bool:
    try:
        relative_parts = path.relative_to(root).parts
    except ValueError:
        relative_parts = path.parts
    # Excluye carpetas ocultas (empiezan con '.'), sin contar el propio
    # archivo (último elemento de la ruta relativa).
    return any(part.startswith(".") for part in relative_parts[:-1])


def find_hru_files(
    root_directory: str | Path,
    *,
    recursive: bool = True,
    exclude_patterns: tuple[str, ...] | None = None,
) -> list[Path]:
    """Encuentra archivos .hru (y .HRU) bajo ``root_directory``.

    Ignora archivos temporales/backup y carpetas ocultas, y devuelve las
    rutas ordenadas de forma determinista. ``exclude_patterns`` acepta
    patrones estilo glob adicionales sobre el nombre de archivo.
    """
    root = Path(root_directory)
    if not root.is_dir():
        return []

    patterns = tuple(exclude_patterns) if exclude_patterns is not None else ()
    candidates = root.rglob("*.hru") if recursive else root.glob("*.hru")
    candidates_upper = root.rglob("*.HRU") if recursive else root.glob("*.HRU")

    found: set[Path] = set()
    for path in (*candidates, *candidates_upper):
        if not path.is_file():
            continue
        if _is_temp_or_backup(path.name):
            continue
        if _is_inside_hidden_folder(path, root):
            continue
        if any(fnmatch.fnmatch(path.name, pattern) for pattern in patterns):
            continue
        found.add(path)

    return sorted(found)


@dataclass
class HRUScanError:
    path: Path
    error_type: str
    message: str


@dataclass
class HRUScanResult:
    files: list[HRUFile]
    errors: list[HRUScanError]


def parse_hru_directory(
    root_directory: str | Path,
    *,
    recursive: bool = True,
    continue_on_error: bool = True,
) -> HRUScanResult:
    """Recorre ``root_directory`` y parsea todos los .hru encontrados.

    Con ``continue_on_error=True`` (por defecto), un archivo dañado se
    registra en ``HRUScanResult.errors`` y no impide procesar el resto.
    Con ``continue_on_error=False``, la primera excepción se propaga.
    """
    files: list[HRUFile] = []
    errors: list[HRUScanError] = []

    for path in find_hru_files(root_directory, recursive=recursive):
        try:
            files.append(parse_hru_file(path))
        except HRUError as exc:
            if not continue_on_error:
                raise
            errors.append(HRUScanError(path=path, error_type=type(exc).__name__, message=str(exc)))
        except Exception as exc:  # noqa: BLE001 - se reporta y se sigue, por diseño
            if not continue_on_error:
                raise
            errors.append(HRUScanError(path=path, error_type=type(exc).__name__, message=str(exc)))

    return HRUScanResult(files=files, errors=errors)
