"""Especificación de columnas de la sección "Operation Schedule" de .mgt.

Cada línea de operación es texto de ancho fijo (formato Fortran), sin
encabezado de columna en el archivo. Las posiciones (1-indexadas,
inclusive por ambos extremos) se tomaron de la documentación oficial
SWAT2012 Input/Output File Documentation, Version 2012, Chapter 20
(swat.tamu.edu/media/69359/ch20_input_mgt.pdf, sección 20.2) y se
verificaron línea por línea contra archivos .mgt reales de
03-Models/Buffalo/Buffalo_calibrated_annual (operaciones 1, 3, 5, 6, 17)
antes de darlas por buenas -- ver CLAUDE.md.

``FieldSpec`` guarda posiciones 1-indexadas tal como las documenta SWAT
(coherente con la documentación al leerla); ``slice_bounds`` las convierte
a un slice 0-indexado semiabierto para indexar strings de Python.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSpec:
    name: str
    start: int  # 1-indexada, inclusive
    end: int  # 1-indexada, inclusive
    decimals: int | None  # None = entero; int = cantidad de decimales

    def slice_bounds(self) -> tuple[int, int]:
        return self.start - 1, self.end


COMMON_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("MONTH", 2, 3, None),
    FieldSpec("DAY", 5, 6, None),
    FieldSpec("HUSC", 8, 15, 3),
    FieldSpec("MGT_OP", 17, 18, None),
)

OPERATION_FIELD_SPECS: dict[int, tuple[FieldSpec, ...]] = {
    1: (
        FieldSpec("PLANT_ID", 20, 23, None),
        FieldSpec("CURYR_MAT", 29, 30, None),
        FieldSpec("HEAT_UNITS", 32, 43, 5),
        FieldSpec("LAI_INIT", 45, 50, 2),
        FieldSpec("BIO_INIT", 52, 62, 5),
        FieldSpec("HI_TARG", 64, 67, 2),
        FieldSpec("BIO_TARG", 69, 74, 2),
        FieldSpec("CNOP", 76, 80, 2),
    ),
    2: (
        FieldSpec("IRR_SC", 25, 27, None),
        FieldSpec("IRR_NO", 29, 30, None),
        FieldSpec("IRR_AMT", 32, 43, 5),
        FieldSpec("IRR_SALT", 45, 50, 2),
        FieldSpec("IRR_EFM", 52, 62, 5),
        FieldSpec("IRR_SQ", 64, 67, 2),
    ),
    3: (
        FieldSpec("FERT_ID", 20, 23, None),
        FieldSpec("FRT_KG", 32, 43, 5),
        FieldSpec("FRT_SURFACE", 45, 50, 2),
    ),
    4: (
        FieldSpec("PEST_ID", 20, 23, None),
        FieldSpec("PST_KG", 32, 43, 5),
        FieldSpec("PST_DEP", 45, 50, 2),
    ),
    5: (
        FieldSpec("CNOP", 32, 43, 5),
        FieldSpec("HI_OVR", 45, 50, 2),
        FieldSpec("FRAC_HARVK", 52, 62, 5),
    ),
    6: (
        FieldSpec("TILL_ID", 20, 23, None),
        FieldSpec("CNOP", 32, 43, 5),
    ),
    7: (
        FieldSpec("IHV_GBM", 25, 27, None),
        FieldSpec("HARVEFF", 32, 43, 5),
        FieldSpec("HI_OVR", 45, 50, 2),
    ),
    8: (),
    9: (
        FieldSpec("GRZ_DAYS", 20, 23, None),
        FieldSpec("MANURE_ID", 25, 27, None),
        FieldSpec("BIO_EAT", 32, 43, 5),
        FieldSpec("BIO_TRMP", 45, 50, 2),
        FieldSpec("MANURE_KG", 52, 62, 5),
    ),
    10: (
        FieldSpec("WSTRS_ID", 20, 23, None),
        FieldSpec("IRR_SCA", 25, 27, None),
        FieldSpec("IRR_NOA", 29, 30, None),
        FieldSpec("AUTO_WSTRS", 32, 43, 5),
        FieldSpec("IRR_EFF", 45, 50, 2),
        FieldSpec("IRR_MX", 52, 62, 5),
        FieldSpec("IRR_ASQ", 64, 67, 2),
    ),
    11: (
        FieldSpec("AFERT_ID", 20, 23, None),
        FieldSpec("AUTO_NSTRS", 32, 43, 5),
        FieldSpec("AUTO_NAPP", 45, 50, 2),
        FieldSpec("AUTO_NYR", 52, 62, 5),
        FieldSpec("AUTO_EFF", 64, 67, 2),
        FieldSpec("AFRT_SURFACE", 69, 74, 2),
    ),
    12: (
        FieldSpec("SWEEPEFF", 32, 43, 5),
        FieldSpec("FR_CURB", 45, 50, 2),
    ),
    13: (
        FieldSpec("IMP_TRIG", 20, 23, None),
    ),
    14: (
        FieldSpec("FERT_DAYS", 20, 23, None),
        FieldSpec("CFRT_ID", 25, 27, None),
        FieldSpec("IFRT_FREQ", 29, 30, None),
        FieldSpec("CFRT_KG", 32, 43, 5),
    ),
    15: (
        FieldSpec("CPST_ID", 20, 23, None),
        FieldSpec("PEST_DAYS", 25, 27, None),
        FieldSpec("IPEST_FREQ", 29, 30, None),
        FieldSpec("CPST_KG", 32, 43, 5),
    ),
    16: (
        FieldSpec("BURN_FRLB", 32, 43, 5),
    ),
    17: (),
}

# Nombre legible en inglés (idioma de resources/strings/en.json, el resto
# de la UI de la app) para cada MGT_OP -- para que el wizard de NbS
# muestre significado y no el código crudo.
MGT_OPERATION_NAMES: dict[int, str] = {
    1: "Planting / beginning of growing season",
    2: "Irrigation",
    3: "Fertilizer application",
    4: "Pesticide application",
    5: "Harvest and kill",
    6: "Tillage",
    7: "Harvest only",
    8: "Kill / end of growing season",
    9: "Grazing",
    10: "Auto irrigation initialization",
    11: "Auto fertilization initialization",
    12: "Street sweeping",
    13: "Release / impound",
    14: "Continuous fertilization",
    15: "Continuous pesticide",
    16: "Burn",
    17: "Skip a year",
}
