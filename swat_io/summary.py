"""Resumen de subcuencas y parámetros de humedal de un proyecto SWAT."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .discovery import discover_subbasins
from .pnd_parser import parse_pnd_file
from .sub_parser import parse_sub_file


def summarize_project(txtinout_dir: Path | str) -> pd.DataFrame:
    """Devuelve un DataFrame con una fila por subcuenca real del TxtInOut.

    Columnas: area_km2 y los parámetros de humedal del .pnd de cada
    subcuenca (wet_fr, wet_nsa_ha, wet_mxsa_ha, etc.), indexadas por
    subbasin_id. El número de subcuencas del modelo es len(df).
    """
    txtinout_dir = Path(txtinout_dir)
    rows = []
    for files in discover_subbasins(txtinout_dir):
        sub_info = parse_sub_file(files.sub_file, files.subbasin_id)
        wetland = parse_pnd_file(files.pnd_file, files.subbasin_id)
        rows.append(
            {
                "subbasin_id": sub_info.subbasin_id,
                "area_km2": sub_info.area_km2,
                "wet_fr": wetland.wet_fr,
                "wet_nsa_ha": wetland.wet_nsa_ha,
                "wet_mxsa_ha": wetland.wet_mxsa_ha,
                "wet_nvol_104m3": wetland.wet_nvol_104m3,
                "wet_mxvol_104m3": wetland.wet_mxvol_104m3,
                "wet_vol_104m3": wetland.wet_vol_104m3,
                "wet_k_mmhr": wetland.wet_k_mmhr,
                "wet_sed_mgl": wetland.wet_sed_mgl,
                "wet_nsed_mgl": wetland.wet_nsed_mgl,
                "psetlw1": wetland.psetlw1,
                "psetlw2": wetland.psetlw2,
                "nsetlw1": wetland.nsetlw1,
                "nsetlw2": wetland.nsetlw2,
                "chlaw": wetland.chlaw,
                "secciw": wetland.secciw,
                "wet_no3_mgl": wetland.wet_no3_mgl,
                "wet_solp_mgl": wetland.wet_solp_mgl,
                "wet_orgn_mgl": wetland.wet_orgn_mgl,
                "wet_orgp_mgl": wetland.wet_orgp_mgl,
                "wetevcoeff": wetland.wetevcoeff,
            }
        )
    return pd.DataFrame(rows).set_index("subbasin_id")
