"""Módulo swat_io.hru: lectura, representación, modificación, escritura e
inventario de archivos .hru de SWAT2012 rev. 670.

Sin dependencias de UI ni de invocación del subproceso SWAT: solo texto
plano. Ver docs/hru_module.md para la documentación técnica y ejemplos.
"""
from __future__ import annotations

from .exceptions import (
    HRUError,
    HRUModificationError,
    HRUParseError,
    HRUReadError,
    HRUValidationError,
    HRUWriteError,
)
from .models import HRUFile, HRUMetadata, HRUParameterLine, HRURawLine
from .modifiers import (
    HRUChange,
    HRUModificationRule,
    HRUSelection,
    apply_modifications,
    preview_modifications,
    write_modified_hru_files,
)
from .parser import parse_hru_file, parse_hru_text
from .scanner import HRUScanError, HRUScanResult, find_hru_files, parse_hru_directory
from .summary import (
    add_land_use_area,
    build_hru_summary,
    export_hru_summary_csv,
    export_land_use_summary_csv,
    find_subbasins_with_invalid_fraction_sum,
    land_use_percentages,
    read_land_use_summary_csv,
    subbasin_area_km2,
    summarize_land_use_by_subbasin,
)
from .validation import HRUValidationIssue
from .writer import write_hru_file

__all__ = [
    "HRUChange",
    "HRUError",
    "HRUFile",
    "HRUMetadata",
    "HRUModificationError",
    "HRUModificationRule",
    "HRUParameterLine",
    "HRUParseError",
    "HRURawLine",
    "HRUReadError",
    "HRUScanError",
    "HRUScanResult",
    "HRUSelection",
    "HRUValidationError",
    "HRUValidationIssue",
    "HRUWriteError",
    "add_land_use_area",
    "apply_modifications",
    "build_hru_summary",
    "export_hru_summary_csv",
    "export_land_use_summary_csv",
    "find_hru_files",
    "find_subbasins_with_invalid_fraction_sum",
    "land_use_percentages",
    "parse_hru_directory",
    "parse_hru_file",
    "parse_hru_text",
    "preview_modifications",
    "read_land_use_summary_csv",
    "subbasin_area_km2",
    "summarize_land_use_by_subbasin",
    "write_hru_file",
    "write_modified_hru_files",
]
