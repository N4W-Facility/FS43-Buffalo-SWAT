"""Borrador editable de parámetros de HRU (.hru) para la pestaña HRUs,
una subcuenca a la vez.

A diferencia de wetland_draft.py (una subcuenca = un .pnd = una fila), aquí
una subcuenca tiene N archivos .hru (uno por HRU); por eso este módulo
trabaja siempre acotado a una subcuenca (list_subbasin_hru_files /
load_subbasin_hru_files), nunca escanea el TxtInOut completo -- con miles
de HRU en una cuenca, parsear todo de una sola vez violaría la regla de
operaciones largas de CLAUDE.md. No hay CSV de respaldo tipo
wetland_params_draft.csv (una copia que se reescribe en cada guardado):
swat_io.hru ya expone su propio inventario completo
(generar_resumen_coberturas.py) y un segundo respaldo aquí sería una
tercera fuente de verdad redundante.

Distinto es export_hru_table_csv: no es un respaldo de lo ya guardado,
es una plantilla de referencia bajo demanda (botón "Export CSV" de la
pestaña) para que el usuario sepa qué subcuenca/HRU/columnas son válidas
al armar un CSV de import masivo -- sin lista curada de parámetros (a
diferencia de Wetlands), no hay otra forma de conocer esa estructura de
antemano.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from swat_io.common.atomic_write import atomic_write_bytes
from swat_io.hru.models import HRUFile, ParamValue
from swat_io.hru.parser import parse_hru_file

_HRU_GLOB_TEMPLATE = "{subbasin_id:05d}????.hru"


def list_subbasin_hru_files(txtinout_dir: Path, subbasin_id: int) -> list[Path]:
    """Rutas .hru de una subcuenca (convención NNNNNMMMM.hru), ordenadas."""
    return sorted(txtinout_dir.glob(_HRU_GLOB_TEMPLATE.format(subbasin_id=subbasin_id)))


def list_subbasin_hru_ids(txtinout_dir: Path, subbasin_id: int) -> set[int]:
    """IDs de HRU de una subcuenca leídos solo del nombre de archivo (sin
    parsear contenido). Pensado para validar existencia durante el import
    CSV masivo sin pagar el costo de parsear cada .hru -- eso se hace
    recién en Materialize, y solo para las HRU realmente afectadas."""
    ids: set[int] = set()
    for path in list_subbasin_hru_files(txtinout_dir, subbasin_id):
        try:
            ids.add(int(path.stem[5:]))
        except ValueError:
            continue
    return ids


def load_subbasin_hru_files(txtinout_dir: Path, subbasin_id: int) -> dict[int, HRUFile]:
    """{hru_id: HRUFile} de todas las HRU de una subcuenca.

    Archivos sin un id de HRU reconocible (metadata.hru is None, ni en el
    contenido ni en el nombre) se omiten -- no hay una fila de tabla
    coherente en la que ubicarlos.
    """
    result: dict[int, HRUFile] = {}
    for path in list_subbasin_hru_files(txtinout_dir, subbasin_id):
        hru_file = parse_hru_file(path)
        if hru_file.metadata.hru is not None:
            result[hru_file.metadata.hru] = hru_file
    return result


def build_hru_table(hru_files: dict[int, HRUFile]) -> pd.DataFrame:
    """Fila por HRU (índice=hru_id), columna por parámetro visto en
    cualquiera de los archivos (orden de primera aparición). NaN donde una
    HRU puntual no tiene ese parámetro -- no todas las .hru de una
    subcuenca tienen exactamente el mismo set (p. ej. POT_FR es opcional).
    """
    columns: list[str] = []
    rows: dict[int, dict[str, ParamValue]] = {}
    for hru_id, hru_file in sorted(hru_files.items()):
        row = hru_file.to_parameter_dict()
        for name in row:
            if name not in columns:
                columns.append(name)
        rows[hru_id] = row
    return pd.DataFrame.from_dict(rows, orient="index", columns=columns)


def write_hru_values(hru_file: HRUFile, values: dict[str, ParamValue]) -> None:
    """Aplica ``values`` sobre ``hru_file`` y escribe directo en su
    ``source_path`` real (in-place).

    Deliberadamente no usa swat_io.hru.writer.write_hru_file: esa función
    exige un destino distinto al origen (piensa en una copia de escenario
    aislada) y rechaza escribir sobre source_path por diseño. Esta pestaña
    sigue, para .hru, la misma convención ya aceptada para Wetlands (ver
    CLAUDE.md, aviso de deuda técnica bajo "Aislamiento por escenario"):
    escribe directo sobre el archivo real de la carpeta TxtInOut abierta,
    sea o no una copia de escenario.
    """
    for name, value in values.items():
        hru_file.set_value(name, value)
    data = hru_file.render().encode(hru_file.encoding)
    atomic_write_bytes(hru_file.source_path, data)


def export_hru_table_csv(subbasin_id: int, table: pd.DataFrame, destination: Path) -> Path:
    """Exporta la tabla de una subcuenca (build_hru_table) a un CSV con
    las columnas subbasin/hru al frente -- exactamente el formato que
    espera scenarios.hru_import.parse_hru_import_csv, para que el usuario
    pueda editar valores ahí y volver a importarlo tal cual."""
    export_df = table.copy()
    export_df.index.name = "hru"
    export_df = export_df.reset_index()
    export_df.insert(0, "subbasin", subbasin_id)
    export_df.to_csv(destination, index=False)
    return destination
