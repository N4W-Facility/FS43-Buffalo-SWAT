"""Parseo de output.hru (balance por HRU) hacia una base SQLite, en streaming.

output.hru puede tener miles de HRU (a diferencia de output.rch, decenas de
reach) y en salida Daily puede pesar más de 1GB. Ese tamaño impone dos
decisiones distintas de las de rch_parser.py:

- Destino: una única base SQLite en tool_outputs/ (hru_timeseries.db) en vez
  de un CSV por HRU -- miles de HRU como miles de archivos chicos degrada en
  Windows, y sqlite3 es librería estándar (cero dependencias nuevas,
  consistente con la decisión de mantener la instalación liviana ya tomada
  para pyshp en vez de geopandas). SQLite además permite consultar una sola
  serie (un HRU, una variable) sin cargar el resto a memoria -- necesario
  para que la pestaña de UI pueda graficar sin releer todo.
- Parseo: todo el módulo es streaming (una línea a la vez, con
  itertools/generadores, nunca ``file.read()`` completo ni un DataFrame con
  todas las filas) -- una corrida Daily de varios años y miles de HRU no
  entra cómodamente en memoria como DataFrame de pandas antes de escribir.

output.hru es texto de ancho fijo con dos capas de columnas:

1. El prefijo identificador (LULC/HRU/GIS/SUB/MGT/MON, primeros 34
   caracteres de cada fila de datos) SÍ tiene espacio de separación
   confiable: verificado que ``line[:34].split()`` da exactamente 6 tokens
   en >5900 filas de muestra de un output.hru real
   (Buffalo_calibrated_annual). HRU (no SUB) es un id global único por HRU
   en toda la cuenca (confirmado contra el archivo real), así que alcanza
   como clave de agrupación para reconstruir fechas.
2. Las 80 variables que siguen (a partir del carácter 34) NO tienen
   separador confiable entre columnas adyacentes cuando un valor llena todo
   el ancho de su campo -- ej. MON=2017 pegado directo a AREA=.33431E-01
   ("2017.33431E-01", sin espacio), o un valor negativo en un campo
   normalmente positivo (ej. mineralización de N) que consume el único
   espacio de margen que separaba dos columnas en el resto de las filas.
   _VARIABLE_COLSPECS fija los límites exactos (offsets de carácter) de
   cada uno de los 80 campos. Una primera pasada de inferencia (espacio
   "siempre en blanco" en una muestra chica) resultó insuficiente -- casos
   de signo negativo poco frecuentes en algunos proyectos rompían límites
   inferidos de una muestra más chica -- así que la versión final se derivó
   y validó contra el contenido COMPLETO de los 31 output.hru reales
   disponibles en el proyecto (~4.95M filas combinadas, incluido el archivo
   Daily de 1.47M filas tres veces), 0 errores de parseo. Los dos casos sin
   ningún espacio de separación en ninguna fila de todo ese dataset
   (AO-LP/L-AP y "WTAB CLI"/"WTAB SOL") se resolvieron probando cada
   posición de corte hasta encontrar la que parsea ambos lados como float
   en las ~4.95M filas. Los campos que desbordan su ancho fijo se imprimen
   como "**********" (relleno de asteriscos, visto en un archivo real) --
   se guardan como NaN en vez de descartar la fila. Igual que output.rch,
   el header no se puede parsear (nombres pegados de la misma forma), así
   que no se usa como fuente de los límites de columna.

Estructura del archivo (verificada contra dos output.hru reales, uno Yearly
y uno Daily): tiempo en el loop externo, HRU en el loop interno (para un
paso de tiempo dado aparecen todos los HRU en orden antes de avanzar al
siguiente paso de tiempo) -- por eso la reconstrucción de fecha rastrea,
por HRU, el último MON visto y detecta wraparound (mon <= último mon del
mismo HRU implica año siguiente), igual que build_rch_timeseries pero en
streaming (dict por HRU en vez de groupby de un DataFrame ya completo).
Yearly trae además una fila de resumen "average annual" al final por HRU
(MON = años promediados en vez de año calendario, ej. "3.0" para una
corrida de 3 años de output -- verificado contra el archivo real), igual
que output.rch: se descarta con el mismo criterio de umbral. Monthly no se
pudo verificar contra un output.hru real (no hay ningún proyecto con
IPRINT=0 en los modelos disponibles) -- reutiliza el mismo criterio que
build_rch_timeseries (13ª fila con MON = año en vez de mes 1-12), ya
confirmado por el usuario para output.rch, pero sin verificación
independiente para output.hru.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import pandas as pd

from .cio_parser import PRINT_FREQUENCY_DAILY, PRINT_FREQUENCY_MONTHLY, PRINT_FREQUENCY_YEARLY, RunSettings
from .common.encoding import detect_encoding
from .tool_outputs import tool_outputs_dir

HRU_OUTPUT_VARIABLE_COLUMNS: list[str] = [
    "AREA", "PRECIP", "SNOFALL", "SNOMELT", "IRR", "PET", "ET", "SW_INIT", "SW_END", "PERC",
    "GW_RCHG", "DA_RCHG", "REVAP", "SA_IRR", "DA_IRR", "SA_ST", "DA_ST", "SURQ_GEN", "SURQ_CNT",
    "TLOSS", "LATQGEN", "GW_Q", "WYLD", "DAILYCN", "TMP_AV", "TMP_MX", "TMP_MN", "SOL_TMP",
    "SOLAR", "SYLD", "USLE", "N_APP", "P_APP", "NAUTO", "PAUTO", "NGRZ", "PGRZ", "NCFRT",
    "PCFRT", "NRAIN", "NFIX", "F_MN", "A_MN", "A_SN", "F_MP", "AO_LP", "L_AP", "A_SP", "DNIT",
    "NUP", "PUP", "ORGN", "ORGP", "SEDP", "NSURQ", "NLATQ", "NO3L", "NO3GW", "SOLP", "P_GW",
    "W_STRS", "TMP_STRS", "N_STRS", "P_STRS", "BIOM", "LAI", "YLD", "BACTP", "BACTLP",
    "WTAB_CLI", "WTAB_SOL", "SNO", "CMUP", "CMTOT", "QTILE", "TNO3", "LNO3", "GW_Q_D",
    "LATQCNT", "TVAP",
]

# Offsets de carácter (línea completa, 0-indexed) de cada una de las 80
# variables de arriba, en el mismo orden. Ver docstring del módulo --
# derivados y validados contra un output.hru real, no adivinados desde el
# header roto.
_IDENTIFIER_PREFIX_LEN = 34
_VARIABLE_BOUNDS = [
    34, 46, 56, 67, 77, 86, 96, 105, 115, 126, 136, 146, 157, 168, 179, 186, 196, 206, 216, 228,
    236, 246, 256, 268, 277, 287, 297, 307, 318, 327, 337, 347, 357, 367, 379, 388, 399, 409,
    419, 428, 437, 447, 457, 466, 477, 487, 494, 507, 516, 527, 537, 547, 558, 567, 578, 587,
    596, 607, 618, 628, 637, 647, 657, 667, 678, 688, 695, 705, 716, 727, 736, 747, 757, 767,
    777, 787, 797, 808, 818, 831, 836,
]
_VARIABLE_COLSPECS: list[tuple[int, int]] = list(zip(_VARIABLE_BOUNDS[:-1], _VARIABLE_BOUNDS[1:]))
assert len(_VARIABLE_COLSPECS) == len(HRU_OUTPUT_VARIABLE_COLUMNS)

_HEADER_ROW_PREFIX = "LULC"
_HRU_DB_FILENAME = "hru_timeseries.db"
_TABLE = "hru_timeseries"
_INSERT_BATCH_SIZE = 20_000
_PROGRESS_EVERY_ROWS = 100_000
# Igual que rch_parser._YEARLY_SUMMARY_MON_THRESHOLD: un MON menor a esto en
# salida Yearly es la fila de resumen "average annual" (años promediados),
# no un año calendario real.
_YEARLY_SUMMARY_MON_THRESHOLD = 1000


class HruOutputParseError(ValueError):
    """output.hru no tiene el formato esperado en alguna línea de datos."""


def hru_output_db_path(project_dir: Path | str) -> Path:
    """tool_outputs/hru_timeseries.db del proyecto (no crea la carpeta si no existe)."""
    return tool_outputs_dir(project_dir) / _HRU_DB_FILENAME


def _iter_data_lines(path: Path | str) -> Iterator[tuple[int, str]]:
    """Itera (número de línea, línea sin salto) de las filas de datos de
    output.hru -- todo lo anterior a la línea de encabezado (la que empieza
    con "LULC") y las líneas en blanco se descartan. Nunca carga el archivo
    completo: abre con la codificación detectada de una muestra chica y lee
    línea a línea."""
    encoding = detect_encoding(path)
    started = False
    with Path(path).open("r", encoding=encoding, errors="replace") as fh:
        for line_number, raw_line in enumerate(fh, start=1):
            line = raw_line.rstrip("\r\n")
            stripped = line.strip()
            if not stripped:
                continue
            if not started:
                if stripped.startswith(_HEADER_ROW_PREFIX):
                    started = True
                continue
            yield line_number, line


def _parse_data_line(path_name: str, line_number: int, line: str) -> tuple[int, int, float, list[float]]:
    """Parsea una fila de datos: devuelve (sub, hru, mon, valores[80])."""
    prefix_tokens = line[:_IDENTIFIER_PREFIX_LEN].split()
    if len(prefix_tokens) != 6:
        raise HruOutputParseError(
            f"{path_name}:{line_number}: expected 6 values in the LULC/HRU/GIS/SUB/MGT/MON prefix, "
            f"found {len(prefix_tokens)}"
        )
    _lulc, hru_token, _gis, sub_token, _mgt, mon_token = prefix_tokens
    try:
        hru = int(hru_token)
        sub = int(sub_token)
        mon = float(mon_token)
    except ValueError as exc:
        raise HruOutputParseError(f"{path_name}:{line_number}: HRU/SUB/MON not numeric ({exc})") from exc

    values: list[float] = []
    for start, end in _VARIABLE_COLSPECS:
        token = line[start:end].strip() if len(line) >= end else line[start:].strip()
        if token and set(token) == {"*"}:
            # SWAT llena el campo entero con "*" cuando el valor desborda el
            # ancho fijo (visto en un output.hru real) -- se guarda como NaN
            # en vez de descartar toda la fila.
            values.append(float("nan"))
            continue
        try:
            values.append(float(token))
        except ValueError as exc:
            raise HruOutputParseError(f"{path_name}:{line_number}: non-numeric value ({exc})") from exc

    return sub, hru, mon, values


@dataclass
class _HruDateState:
    last_mon: float = 0.0
    year: int = 0


def _iter_hru_output_timeseries(
    path: Path | str, run_settings: RunSettings
) -> Iterator[tuple[str, int, int, list[float]]]:
    """Generador streaming: (fecha ISO, sub, hru, valores[80]) por cada fila
    real de output.hru (descarta filas de resumen no-calendario). Misma
    lógica de reconstrucción de fecha que build_rch_timeseries, pero por HRU
    y sin materializar un DataFrame completo -- ver docstring del módulo."""
    path = Path(path)
    start_year = run_settings.start_year + run_settings.years_to_skip
    frequency = run_settings.print_frequency

    if frequency not in (PRINT_FREQUENCY_YEARLY, PRINT_FREQUENCY_MONTHLY, PRINT_FREQUENCY_DAILY):
        raise ValueError(f"Unknown print_frequency: {frequency}")

    states: dict[int, _HruDateState] = {}

    for line_number, line in _iter_data_lines(path):
        sub, hru, mon, values = _parse_data_line(path.name, line_number, line)

        if frequency == PRINT_FREQUENCY_YEARLY:
            if mon < _YEARLY_SUMMARY_MON_THRESHOLD:
                continue
            date_str = f"{int(mon):04d}-01-01"
            yield date_str, sub, hru, values
            continue

        state = states.setdefault(hru, _HruDateState(last_mon=0.0, year=start_year))

        if frequency == PRINT_FREQUENCY_MONTHLY:
            if mon > 12:
                continue
            if mon <= state.last_mon:
                state.year += 1
            date_str = f"{state.year:04d}-{int(mon):02d}-01"
            state.last_mon = mon
            yield date_str, sub, hru, values
            continue

        # Daily
        if mon <= state.last_mon:
            state.year += 1
        day = pd.Timestamp(year=state.year, month=1, day=1) + pd.Timedelta(days=int(mon) - 1)
        state.last_mon = mon
        yield day.date().isoformat(), sub, hru, values


def build_hru_output_database(
    hru_path: Path | str,
    run_settings: RunSettings,
    dest_db_path: Path | str,
    *,
    report_progress: Callable[[str], None] | None = None,
) -> dict:
    """Parsea output.hru entero en streaming y lo escribe en dest_db_path
    (SQLite, tabla hru_timeseries: date, sub, hru, + 80 columnas de
    variable). Recrea la base desde cero si ya existía. Devuelve un resumen
    {"rows": int, "hrus": int, "subbasins": int, "dest_db_path": Path}."""
    dest_db_path = Path(dest_db_path)
    dest_db_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_db_path.exists():
        dest_db_path.unlink()

    quoted_columns = [f'"{name}"' for name in HRU_OUTPUT_VARIABLE_COLUMNS]
    columns_sql = ", ".join(f"{col} REAL" for col in quoted_columns)
    placeholders = ", ".join(["?"] * (3 + len(HRU_OUTPUT_VARIABLE_COLUMNS)))
    insert_sql = (
        f"INSERT INTO {_TABLE} (date, sub, hru, {', '.join(quoted_columns)}) VALUES ({placeholders})"
    )

    conn = sqlite3.connect(dest_db_path)
    try:
        conn.execute(f"CREATE TABLE {_TABLE} (date TEXT NOT NULL, sub INTEGER NOT NULL, hru INTEGER NOT NULL, {columns_sql})")
        conn.execute("BEGIN")

        rows_written = 0
        hrus_seen: set[int] = set()
        subs_seen: set[int] = set()
        batch: list[tuple] = []

        for date_str, sub, hru, values in _iter_hru_output_timeseries(hru_path, run_settings):
            batch.append((date_str, sub, hru, *values))
            hrus_seen.add(hru)
            subs_seen.add(sub)
            rows_written += 1

            if len(batch) >= _INSERT_BATCH_SIZE:
                conn.executemany(insert_sql, batch)
                batch.clear()
                if report_progress is not None and rows_written % _PROGRESS_EVERY_ROWS < _INSERT_BATCH_SIZE:
                    report_progress(f"Organizing output.hru... {rows_written:,} rows")

        if batch:
            conn.executemany(insert_sql, batch)

        conn.commit()
        conn.execute(f"CREATE INDEX idx_{_TABLE}_hru ON {_TABLE} (hru, date)")
        conn.execute(f"CREATE INDEX idx_{_TABLE}_sub ON {_TABLE} (sub, hru, date)")
        conn.commit()
    finally:
        conn.close()

    if rows_written == 0:
        raise HruOutputParseError(f"{Path(hru_path).name}: no data row was found (prefix 'LULC')")

    return {
        "rows": rows_written,
        "hrus": len(hrus_seen),
        "subbasins": len(subs_seen),
        "dest_db_path": dest_db_path,
    }


# -- consultas sobre la base ya organizada ------------------------------------


def list_subbasins(db_path: Path | str) -> list[int]:
    """Subcuencas distintas presentes en la base, ordenadas."""
    if not Path(db_path).is_file():
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(f"SELECT DISTINCT sub FROM {_TABLE} ORDER BY sub").fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def list_hrus_for_subbasin(db_path: Path | str, sub: int) -> list[int]:
    """HRU distintos de una subcuenca, ordenados."""
    if not Path(db_path).is_file():
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT DISTINCT hru FROM {_TABLE} WHERE sub = ? ORDER BY hru", (sub,)
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def read_hru_series(db_path: Path | str, hru: int, variable: str) -> pd.Series:
    """Serie de tiempo (índice = date) de una variable para un único HRU."""
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            f'SELECT date, "{variable}" FROM {_TABLE} WHERE hru = ? ORDER BY date',
            conn,
            params=(hru,),
            parse_dates=["date"],
        )
    finally:
        conn.close()
    return df.set_index("date")[variable]


def read_subbasin_variable_wide(db_path: Path | str, sub: int, variable: str) -> pd.DataFrame:
    """Una variable, todas las HRU de una subcuenca: filas = date, columnas =
    hru_<id>. Usada tanto por el export "toda la subcuenca" como por
    cualquier vista comparativa entre HRU de una misma subcuenca."""
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            f'SELECT date, hru, "{variable}" FROM {_TABLE} WHERE sub = ? ORDER BY hru, date',
            conn,
            params=(sub,),
            parse_dates=["date"],
        )
    finally:
        conn.close()
    wide = df.pivot(index="date", columns="hru", values=variable)
    wide.columns = [f"hru_{int(c)}" for c in wide.columns]
    return wide


def export_single_series_csv(db_path: Path | str, hru: int, variable: str, dest_path: Path | str) -> Path:
    """Exporta la serie de una variable de un único HRU a CSV (date, <variable>)."""
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    series = read_hru_series(db_path, hru, variable)
    series.to_frame(name=variable).to_csv(dest_path, index_label="date")
    return dest_path


def read_hru_variables(db_path: Path | str, hru: int, variables: list[str]) -> pd.DataFrame:
    """Varias variables de un único HRU: filas = date, columnas = variables (en el orden
    pedido). Usada tanto por "Export all variables" (variables=HRU_OUTPUT_VARIABLE_COLUMNS)
    como por "Export selected variables" (subconjunto elegido por el usuario)."""
    if not variables:
        return pd.DataFrame()
    conn = sqlite3.connect(db_path)
    try:
        columns_sql = ", ".join(f'"{name}"' for name in variables)
        df = pd.read_sql_query(
            f'SELECT date, {columns_sql} FROM {_TABLE} WHERE hru = ? ORDER BY date',
            conn,
            params=(hru,),
            parse_dates=["date"],
        )
    finally:
        conn.close()
    return df.set_index("date")


def export_hru_variables_csv(db_path: Path | str, hru: int, variables: list[str], dest_path: Path | str) -> Path:
    """Exporta varias variables de un único HRU a CSV (date + una columna por variable)."""
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    read_hru_variables(db_path, hru, variables).to_csv(dest_path, index_label="date")
    return dest_path


def read_hru_group_rows(db_path: Path | str, hru_ids: list[int], variable: str) -> pd.DataFrame:
    """date, hru, AREA, <variable> para un conjunto de HRU -- usado por la exportación
    comparativa entre escenarios de Batch (scenarios/comparison_export.py) para agregar
    por grupo (cobertura/pendiente/suelo). No incluye "sub": el llamador ya conoce la
    subcuenca de cada HRU por su propia clasificación (HRU es id global único en toda la
    cuenca, ver docstring del módulo)."""
    if not hru_ids:
        return pd.DataFrame(columns=["date", "hru", "AREA", variable])
    conn = sqlite3.connect(db_path)
    try:
        placeholders = ", ".join("?" * len(hru_ids))
        df = pd.read_sql_query(
            f'SELECT date, hru, "AREA", "{variable}" FROM {_TABLE} WHERE hru IN ({placeholders}) ORDER BY date',
            conn,
            params=hru_ids,
            parse_dates=["date"],
        )
    finally:
        conn.close()
    return df


def export_subbasin_variable_csv(db_path: Path | str, sub: int, variable: str, dest_path: Path | str) -> Path:
    """Exporta una variable de todas las HRU de una subcuenca a CSV (date +
    una columna por HRU)."""
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    wide = read_subbasin_variable_wide(db_path, sub, variable)
    wide.to_csv(dest_path, index_label="date")
    return dest_path
