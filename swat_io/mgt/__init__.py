"""Parser y escritor de archivos .mgt de SWAT2012 rev. 670.

Ver docs/mgt_module.md para el detalle de las columnas de "Operation
Schedule" (verificadas contra la documentación oficial de SWAT2012 I/O y
contra archivos .mgt reales del proyecto, ver CLAUDE.md).
"""
from __future__ import annotations

from .exceptions import MGTError, MGTModificationError, MGTParseError, MGTReadError, MGTWriteError
from .models import MGTFile, MGTHeaderLine, MGTOperation, MGTRawLine
from .operation_specs import MGT_OPERATION_NAMES, OPERATION_FIELD_SPECS
from .parser import parse_mgt_file, parse_mgt_text
from .writer import write_mgt_file

__all__ = [
    "MGTError",
    "MGTModificationError",
    "MGTParseError",
    "MGTReadError",
    "MGTWriteError",
    "MGTFile",
    "MGTHeaderLine",
    "MGTOperation",
    "MGTRawLine",
    "MGT_OPERATION_NAMES",
    "OPERATION_FIELD_SPECS",
    "parse_mgt_file",
    "parse_mgt_text",
    "write_mgt_file",
]
