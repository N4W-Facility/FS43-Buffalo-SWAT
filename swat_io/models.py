"""Modelos tipados para los datos de subcuenca y humedal leídos de SWAT."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SubbasinInfo:
    subbasin_id: int
    area_km2: float
    source_file: Path

    @classmethod
    def from_raw(
        cls, subbasin_id: int, raw: dict[str, str], source_file: Path
    ) -> "SubbasinInfo":
        return cls(
            subbasin_id=subbasin_id,
            area_km2=float(raw["SUB_KM"]),
            source_file=source_file,
        )


@dataclass(frozen=True)
class WetlandParams:
    """Sección "Wetland inputs" de un archivo .pnd."""

    subbasin_id: int
    wet_fr: float
    wet_nsa_ha: float
    wet_nvol_104m3: float
    wet_mxsa_ha: float
    wet_mxvol_104m3: float
    wet_vol_104m3: float
    wet_sed_mgl: float
    wet_nsed_mgl: float
    wet_k_mmhr: float
    psetlw1: float
    psetlw2: float
    nsetlw1: float
    nsetlw2: float
    chlaw: float
    secciw: float
    wet_no3_mgl: float
    wet_solp_mgl: float
    wet_orgn_mgl: float
    wet_orgp_mgl: float
    wetevcoeff: float
    source_file: Path

    @classmethod
    def from_raw(
        cls, subbasin_id: int, raw: dict[str, str], source_file: Path
    ) -> "WetlandParams":
        def value(code: str) -> float:
            return float(raw[code])

        return cls(
            subbasin_id=subbasin_id,
            wet_fr=value("WET_FR"),
            wet_nsa_ha=value("WET_NSA"),
            wet_nvol_104m3=value("WET_NVOL"),
            wet_mxsa_ha=value("WET_MXSA"),
            wet_mxvol_104m3=value("WET_MXVOL"),
            wet_vol_104m3=value("WET_VOL"),
            wet_sed_mgl=value("WET_SED"),
            wet_nsed_mgl=value("WET_NSED"),
            wet_k_mmhr=value("WET_K"),
            psetlw1=value("PSETLW1"),
            psetlw2=value("PSETLW2"),
            nsetlw1=value("NSETLW1"),
            nsetlw2=value("NSETLW2"),
            chlaw=value("CHLAW"),
            secciw=value("SECCIW"),
            wet_no3_mgl=value("WET_NO3"),
            wet_solp_mgl=value("WET_SOLP"),
            wet_orgn_mgl=value("WET_ORGN"),
            wet_orgp_mgl=value("WET_ORGP"),
            wetevcoeff=value("WETEVCOEFF"),
            source_file=source_file,
        )
