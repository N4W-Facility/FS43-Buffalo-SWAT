"""Modificación masiva controlada de parámetros .hru (API de biblioteca).

No es una interfaz gráfica: expone selección declarativa de HRUs +
reglas de modificación, con una fase de preview que nunca escribe ni
muta los objetos originales, separada de la fase de escritura real.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from .exceptions import HRUModificationError
from .models import HRUFile, HRUParameterLine, ParamValue
from .writer import write_hru_file


@dataclass(frozen=True)
class HRUSelection:
    subbasins: frozenset[int] | None = None
    hrus: frozenset[int] | None = None
    land_uses: frozenset[str] | None = None
    soils: frozenset[str] | None = None
    file_glob: str | None = None

    def matches(self, hru_file: HRUFile) -> bool:
        metadata = hru_file.metadata

        if self.subbasins is not None and metadata.subbasin not in self.subbasins:
            return False
        if self.hrus is not None and metadata.hru not in self.hrus:
            return False
        if self.land_uses is not None:
            if metadata.land_use is None:
                return False
            allowed = {lu.upper() for lu in self.land_uses}
            if metadata.land_use.upper() not in allowed:
                return False
        if self.soils is not None:
            if metadata.soil is None:
                return False
            allowed = {s.upper() for s in self.soils}
            if metadata.soil.upper() not in allowed:
                return False
        if self.file_glob is not None:
            if hru_file.source_path is None:
                return False
            if not fnmatch.fnmatch(hru_file.source_path.name, self.file_glob):
                return False
        return True


@dataclass(frozen=True)
class HRUModificationRule:
    parameter: str
    new_value: ParamValue
    selection: HRUSelection


@dataclass
class HRUChange:
    source_path: Path | None
    destination_path: Path | None
    subbasin: int | None
    hru: int | None
    land_use: str | None
    parameter: str
    old_value: ParamValue | None
    new_value: ParamValue | None
    status: str
    message: str | None = None


def _apply_rule_to_file(hru_file: HRUFile, rule: HRUModificationRule) -> HRUChange:
    metadata = hru_file.metadata
    param = hru_file.get_parameter(rule.parameter)

    if param is None:
        return HRUChange(
            source_path=hru_file.source_path,
            destination_path=None,
            subbasin=metadata.subbasin,
            hru=metadata.hru,
            land_use=metadata.land_use,
            parameter=rule.parameter,
            old_value=None,
            new_value=rule.new_value,
            status="PARAMETER_NOT_FOUND",
            message=f"El parámetro '{rule.parameter}' no existe en {hru_file.source_path}.",
        )

    old_value = param.parsed_value
    hru_file.set_value(rule.parameter, rule.new_value)
    return HRUChange(
        source_path=hru_file.source_path,
        destination_path=None,
        subbasin=metadata.subbasin,
        hru=metadata.hru,
        land_use=metadata.land_use,
        parameter=rule.parameter,
        old_value=old_value,
        new_value=rule.new_value,
        status="MODIFIED",
        message=None,
    )


def preview_modifications(
    hru_files: list[HRUFile],
    rules: list[HRUModificationRule],
) -> list[HRUChange]:
    """Simula la aplicación de ``rules`` sin escribir nada ni mutar los
    ``hru_files`` originales (opera sobre copias profundas)."""
    changes: list[HRUChange] = []
    for hru_file in hru_files:
        working_copy = hru_file.copy()
        for rule in rules:
            if not rule.selection.matches(working_copy):
                continue
            changes.append(_apply_rule_to_file(working_copy, rule))
    return changes


def apply_modifications(
    hru_files: list[HRUFile],
    rules: list[HRUModificationRule],
) -> list[HRUChange]:
    """Aplica ``rules`` mutando ``hru_files`` en memoria (no escribe a
    disco; usar write_modified_hru_files para persistir)."""
    changes: list[HRUChange] = []
    for hru_file in hru_files:
        for rule in rules:
            if not rule.selection.matches(hru_file):
                continue
            changes.append(_apply_rule_to_file(hru_file, rule))
    return changes


def write_modified_hru_files(
    hru_files: list[HRUFile],
    destination_root: str | Path,
    *,
    source_root: str | Path,
    create_backup: bool = False,
    protected_roots: list[Path] | None = None,
) -> list[HRUChange]:
    """Escribe, bajo ``destination_root``, los archivos de ``hru_files``
    que tengan parámetros modificados (``HRUParameterLine.modified``),
    conservando la estructura relativa de carpetas respecto a
    ``source_root``.

    Toda la validación de rutas ocurre antes de escribir el primer
    archivo, para no dejar un lote escrito parcialmente si algo no
    cumple las reglas de seguridad (rutas iguales, archivo fuera de
    source_root, destino dentro de una carpeta protegida).
    """
    source_root = Path(source_root).resolve()
    destination_root = Path(destination_root).resolve()

    if source_root == destination_root:
        raise HRUModificationError("source_root y destination_root no pueden ser la misma carpeta.")

    for protected_root in protected_roots or []:
        protected_root = Path(protected_root).resolve()
        if destination_root == protected_root or protected_root in destination_root.parents:
            raise HRUModificationError(
                f"destination_root ({destination_root}) está dentro de la carpeta protegida {protected_root}."
            )

    planned: list[tuple[HRUFile, Path]] = []
    for hru_file in hru_files:
        if hru_file.source_path is None:
            raise HRUModificationError("No se puede escribir un HRUFile sin source_path conocido.")
        source_path = Path(hru_file.source_path).resolve()
        try:
            relative = source_path.relative_to(source_root)
        except ValueError as exc:
            raise HRUModificationError(
                f"{source_path} no está dentro de source_root ({source_root})."
            ) from exc
        planned.append((hru_file, destination_root / relative))

    changes: list[HRUChange] = []
    for hru_file, destination_path in planned:
        modified_lines = [
            line for line in hru_file.lines if isinstance(line, HRUParameterLine) and line.modified
        ]
        file_changes = [
            HRUChange(
                source_path=hru_file.source_path,
                destination_path=destination_path,
                subbasin=hru_file.metadata.subbasin,
                hru=hru_file.metadata.hru,
                land_use=hru_file.metadata.land_use,
                parameter=line.parameter_name,
                old_value=line.original_parsed_value,
                new_value=line.parsed_value,
                status="PENDING",
                message=None,
            )
            for line in modified_lines
        ]

        write_hru_file(hru_file, destination_path, atomic=True, create_backup=create_backup, allow_overwrite=True)

        for change in file_changes:
            change.status = "WRITTEN"
        changes.extend(file_changes)

    return changes
