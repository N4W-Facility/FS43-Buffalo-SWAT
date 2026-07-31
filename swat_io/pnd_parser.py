"""Parseo de archivos .pnd, sección "Wetland inputs"."""
from __future__ import annotations

from pathlib import Path

from .models import WetlandParams
from .text_format import parse_value_code_file, write_value_code_file


def parse_pnd_file(path: Path, subbasin_id: int) -> WetlandParams:
    """Lee un archivo .pnd y devuelve los parámetros de humedal de la subcuenca."""
    raw = parse_value_code_file(path)
    return WetlandParams.from_raw(subbasin_id, raw, path)


# Los 20 campos de la sección "Wetland inputs" de un .pnd. Cada field id
# (clave de formulario, sin sufijo de unidad) mapea a su CODIGO SWAT crudo
# (para escritura) y a su atributo en WetlandParams (para lectura). Ambos
# diccionarios deben tener exactamente las mismas claves — lo cubre un test.
_FIELD_TO_CODE = {
    "wet_fr": "WET_FR",
    "wet_nsa": "WET_NSA",
    "wet_nvol": "WET_NVOL",
    "wet_mxsa": "WET_MXSA",
    "wet_mxvol": "WET_MXVOL",
    "wet_vol": "WET_VOL",
    "wet_sed": "WET_SED",
    "wet_nsed": "WET_NSED",
    "wet_k": "WET_K",
    "psetlw1": "PSETLW1",
    "psetlw2": "PSETLW2",
    "nsetlw1": "NSETLW1",
    "nsetlw2": "NSETLW2",
    "chlaw": "CHLAW",
    "secciw": "SECCIW",
    "wet_no3": "WET_NO3",
    "wet_solp": "WET_SOLP",
    "wet_orgn": "WET_ORGN",
    "wet_orgp": "WET_ORGP",
    "wetevcoeff": "WETEVCOEFF",
}

_FIELD_TO_ATTR = {
    "wet_fr": "wet_fr",
    "wet_nsa": "wet_nsa_ha",
    "wet_nvol": "wet_nvol_104m3",
    "wet_mxsa": "wet_mxsa_ha",
    "wet_mxvol": "wet_mxvol_104m3",
    "wet_vol": "wet_vol_104m3",
    "wet_sed": "wet_sed_mgl",
    "wet_nsed": "wet_nsed_mgl",
    "wet_k": "wet_k_mmhr",
    "psetlw1": "psetlw1",
    "psetlw2": "psetlw2",
    "nsetlw1": "nsetlw1",
    "nsetlw2": "nsetlw2",
    "chlaw": "chlaw",
    "secciw": "secciw",
    "wet_no3": "wet_no3_mgl",
    "wet_solp": "wet_solp_mgl",
    "wet_orgn": "wet_orgn_mgl",
    "wet_orgp": "wet_orgp_mgl",
    "wetevcoeff": "wetevcoeff",
}


def write_wetland_params(path: Path, values: dict[str, float]) -> None:
    """Escribe parámetros de humedal en un .pnd.

    values usa las claves del formulario declarativo (wet_fr, wet_nsa,
    ...), no los códigos SWAT crudos.
    """
    updates = {_FIELD_TO_CODE[field_id]: value for field_id, value in values.items()}
    write_value_code_file(path, updates)


def wetland_params_to_field_values(params: WetlandParams) -> dict[str, float]:
    """Los 20 parámetros de un WetlandParams, indexados por field id de
    formulario (la misma clave que espera write_wetland_params)."""
    return {field_id: getattr(params, attr) for field_id, attr in _FIELD_TO_ATTR.items()}
