"""Lectura opcional de nombres de clase desde la Raster Attribute Table
(RAT) que GDAL persiste en un sidecar ``<raster>.aux.xml`` (formato PAM --
Persistent Auxiliary Metadata), cuando el raster la trae. El raster de
restauración real del proyecto sí trae una (confirmado contra el archivo
real: filas ``Value``/``descriptio`` con nombres como "potential wetland
area only") -- el de cobertura (Cropland Data Layer) no expone nombres por
esta vía, así que el llamador debe tratar la ausencia de RAT como algo
normal, no un error: en ese caso solo se conoce el código numérico.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


def read_pam_rat_names(raster_path: str | Path) -> dict[int, str] | None:
    """Devuelve {valor: nombre} desde el primer campo de texto de la RAT
    del sidecar .aux.xml, o None si no hay .aux.xml, no tiene RAT, o no
    tiene ningún campo de texto (``String``) para usar como nombre."""
    aux_path = Path(str(raster_path) + ".aux.xml")
    if not aux_path.is_file():
        return None

    try:
        root = ET.parse(aux_path).getroot()
    except ET.ParseError:
        return None

    rat = root.find(".//GDALRasterAttributeTable")
    if rat is None:
        return None

    def _type_as_string(field_defn: ET.Element) -> str | None:
        # "String"/"Integer"/"Real" está en el atributo typeAsString del
        # elemento <Type>, no en su texto (que es un código numérico de
        # enum de GDAL, ej. "2") -- confirmado contra el .aux.xml real.
        type_el = field_defn.find("Type")
        return type_el.get("typeAsString") if type_el is not None else None

    field_defs = rat.findall("FieldDefn")
    value_index = next((i for i, f in enumerate(field_defs) if f.findtext("Name") == "Value"), None)
    name_index = next(
        (i for i, f in enumerate(field_defs) if _type_as_string(f) == "String" and f.findtext("Name") != "Value"),
        None,
    )
    if value_index is None or name_index is None:
        return None

    names: dict[int, str] = {}
    for row in rat.findall("Row"):
        fields = row.findall("F")
        if len(fields) <= max(value_index, name_index):
            continue
        try:
            value = int(float(fields[value_index].text))
        except (TypeError, ValueError):
            continue
        name = fields[name_index].text
        if name is not None:
            names[value] = name
    return names or None
