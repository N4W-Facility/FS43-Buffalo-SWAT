"""Parser y escritor de plant.dat/crop.dat (base vegetal) de SWAT2012 rev. 670."""
from __future__ import annotations

from .exceptions import PlantDatError, PlantDatModificationError, PlantDatParseError, PlantDatReadError, PlantDatWriteError
from .models import (
    ALL_PHYSIOLOGY_FIELDS,
    LINE2_FIELDS,
    LINE3_FIELDS,
    LINE4_FIELDS,
    LINE5_FIELDS,
    PlantDatFile,
    PlantRecord,
    build_plant_record,
)
from .parser import parse_plant_dat_file, parse_plant_dat_text
from .writer import write_plant_dat_file

__all__ = [
    "PlantDatError",
    "PlantDatModificationError",
    "PlantDatParseError",
    "PlantDatReadError",
    "PlantDatWriteError",
    "ALL_PHYSIOLOGY_FIELDS",
    "LINE2_FIELDS",
    "LINE3_FIELDS",
    "LINE4_FIELDS",
    "LINE5_FIELDS",
    "PlantDatFile",
    "PlantRecord",
    "build_plant_record",
    "parse_plant_dat_file",
    "parse_plant_dat_text",
    "write_plant_dat_file",
]
