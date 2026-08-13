"""Parseo de output.sub: balance por subcuenca de SWAT.

A diferencia de output.rch (separado por espacios de forma confiable),
output.sub tiene el mismo problema estructural que output.hru: es texto de
ancho fijo y el campo MON (día juliano en Daily, mes en Monthly, año en
Yearly) se imprime SIN separador ni relleno frente al campo AREA que le
sigue -- no es un caso de desborde ocasional (como en output.hru), es así
siempre, incluso para MON de un solo dígito (ej. "1.31340E+00" en vez de
"1 0.31340E+00"). Verificado programáticamente contra los 32 output.sub
reales disponibles en el proyecto (~102 mil filas, 0 errores de parseo):
el valor de AREA (últimos 10 caracteres del campo combinado) es idéntico
para todas las filas de una misma subcuenca, mientras que el prefijo
variable de ese mismo campo (los caracteres [20:25) del campo combinado)
coincide exactamente con la secuencia de MON esperada (día/mes/año
incrementando fila a fila). El header ("SUB GIS MON AREAkm2 ...") tampoco
es parseable por el mismo motivo que .rch/.hru (nombres+unidad pegados
entre sí) y no se usa como fuente de los límites de columna.

Los 24 campos de variable restantes (PRECIP..TVAP) SÍ están separados por
al menos un espacio en todas las filas verificadas -- solo MON/AREA
requieren slicing de ancho fijo.

Estructura de cada fila de datos ("BIGSUB" es un literal constante que
imprime SWAT, no el nombre real de la subcuenca):
    [0:6)   "BIGSUB" (literal)
    [6:11)  SUB  (id de subcuenca)
    [11:20) GIS  (siempre 0 en los archivos verificados, sin uso conocido)
    [20:25) MON  (día/mes/año según frecuencia de impresión)
    [25:35) AREA (primera de las 25 variables -- ver SUB_VARIABLE_COLUMNS)
    [35:45) ... [266:276)  24 variables más, un campo de 10 caracteres cada una
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Callable

import pandas as pd

from .cio_parser import PRINT_FREQUENCY_DAILY, PRINT_FREQUENCY_MONTHLY, PRINT_FREQUENCY_YEARLY, RunSettings
from .common.encoding import read_text_with_fallback
from .tool_outputs import tool_outputs_dir

SUB_VARIABLE_COLUMNS: list[str] = [
    "AREA", "PRECIP", "SNOMELT", "PET", "ET", "SW", "PERC", "SURQ", "GW_Q", "WYLD",
    "SYLD", "ORGN", "ORGP", "NSURQ", "SOLP", "SEDP", "LATQ", "LATNO3", "GWNO3",
    "CHOLA", "CBODU", "DOXQ", "TNO3", "QTILE", "TVAP",
]

_DATA_ROW_PREFIX = "BIGSUB"
_SUB_ID_SPAN = (6, 11)
_GIS_SPAN = (11, 20)
_MON_SPAN = (20, 25)
# Offsets del primer campo de variable (AREA, [25:35)) en adelante -- ver
# docstring del módulo.
_VARIABLE_BOUNDS = [
    25, 35, 45, 55, 65, 75, 85, 95, 105, 115, 125, 135, 145, 155, 165, 175,
    185, 195, 205, 215, 226, 236, 246, 256, 266, 276,
]
_VARIABLE_COLSPECS: list[tuple[int, int]] = list(zip(_VARIABLE_BOUNDS[:-1], _VARIABLE_BOUNDS[1:]))
assert len(_VARIABLE_COLSPECS) == len(SUB_VARIABLE_COLUMNS)

_SUB_OUTPUT_DIRNAME = "sub_timeseries"
# Igual que rch_parser._YEARLY_SUMMARY_MON_THRESHOLD: un MON menor a esto en
# salida Yearly es la fila de resumen "average annual" (años promediados,
# ej. "3.0"), no un año calendario real.
_YEARLY_SUMMARY_MON_THRESHOLD = 1000


class SubParseError(ValueError):
    """output.sub no tiene el formato esperado en alguna línea de datos."""


def parse_sub_file(path: Path | str) -> pd.DataFrame:
    """Parsea todas las filas de datos de output.sub.

    Devuelve un DataFrame con una fila por registro del archivo (una
    subcuenca en un paso de tiempo), preservando el orden original del
    archivo -- build_sub_timeseries depende de ese orden para reconstruir
    fechas reales en salidas Monthly/Daily. Columnas: "sub", "gis", "mon",
    más una por cada SUB_VARIABLE_COLUMNS.
    """
    path = Path(path)
    min_length = _VARIABLE_BOUNDS[-1]
    rows: list[list[float]] = []

    text = read_text_with_fallback(path).text
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.startswith(_DATA_ROW_PREFIX):
            continue
        if len(line) < min_length:
            raise SubParseError(f"{path.name}:{line_number}: line shorter than expected ({len(line)} characters)")

        try:
            sub_id = int(line[_SUB_ID_SPAN[0]:_SUB_ID_SPAN[1]].strip())
            gis = int(line[_GIS_SPAN[0]:_GIS_SPAN[1]].strip())
            mon = float(line[_MON_SPAN[0]:_MON_SPAN[1]].strip())
        except ValueError as exc:
            raise SubParseError(f"{path.name}:{line_number}: SUB/GIS/MON not numeric ({exc})") from exc

        values: list[float] = []
        for start, end in _VARIABLE_COLSPECS:
            token = line[start:end].strip()
            try:
                values.append(float(token))
            except ValueError as exc:
                raise SubParseError(f"{path.name}:{line_number}: non-numeric value ({exc})") from exc

        rows.append([sub_id, gis, mon, *values])

    if not rows:
        raise SubParseError(f"{path.name}: no data row was found (prefix 'BIGSUB')")

    columns = ["sub", "gis", "mon"] + SUB_VARIABLE_COLUMNS
    df = pd.DataFrame(rows, columns=columns)
    df["sub"] = df["sub"].astype(int)
    df["gis"] = df["gis"].astype(int)
    return df


def build_sub_timeseries(df: pd.DataFrame, run_settings: RunSettings) -> pd.DataFrame:
    """Agrega una columna "date" (datetime64) a las filas parseadas, según
    la frecuencia de impresión de la corrida -- misma lógica que
    swat_io.rch_parser.build_rch_timeseries (fila de resumen "average
    annual" en Yearly, wraparound de MON en Monthly/Daily), aplicada por
    subcuenca en vez de por reach."""
    start_year = run_settings.start_year + run_settings.years_to_skip

    if run_settings.print_frequency == PRINT_FREQUENCY_YEARLY:
        result = df[df["mon"] >= _YEARLY_SUMMARY_MON_THRESHOLD].copy()
        result["date"] = pd.to_datetime(result["mon"].astype(int).astype(str), format="%Y")
        return result.drop(columns=["mon"]).sort_values(["sub", "date"]).reset_index(drop=True)

    if run_settings.print_frequency == PRINT_FREQUENCY_MONTHLY:
        return _assign_calendar_dates(
            df,
            start_year,
            is_annual_summary_row=lambda mon: mon > 12,
            date_from=lambda year, mon: date(year, mon, 1),
        )

    if run_settings.print_frequency == PRINT_FREQUENCY_DAILY:
        return _assign_calendar_dates(
            df,
            start_year,
            is_annual_summary_row=None,
            date_from=lambda year, day: date(year, 1, 1) + pd.Timedelta(days=day - 1),
        )

    raise ValueError(f"Unknown print_frequency: {run_settings.print_frequency}")


def _assign_calendar_dates(
    df: pd.DataFrame,
    start_year: int,
    *,
    is_annual_summary_row: Callable[[int], bool] | None,
    date_from: Callable[[int, int], object],
) -> pd.DataFrame:
    kept_rows: list[dict] = []
    for _, group in df.groupby("sub", sort=False):
        year = start_year
        prev_mon = 0
        for _, row in group.iterrows():
            mon = int(row["mon"])
            if is_annual_summary_row is not None and is_annual_summary_row(mon):
                continue
            if mon <= prev_mon:
                year += 1
            new_row = row.to_dict()
            new_row["date"] = date_from(year, mon)
            kept_rows.append(new_row)
            prev_mon = mon

    result = pd.DataFrame(kept_rows).drop(columns=["mon"])
    result["date"] = pd.to_datetime(result["date"])
    return result.sort_values(["sub", "date"]).reset_index(drop=True)


def sub_timeseries_dir(project_dir: Path | str) -> Path:
    """tool_outputs/sub_timeseries/ del proyecto, creándola si no existe."""
    path = tool_outputs_dir(project_dir) / _SUB_OUTPUT_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def export_sub_timeseries_csvs(timeseries: pd.DataFrame, dest_dir: Path | str) -> dict[int, Path]:
    """Escribe un CSV por subcuenca en dest_dir (sub_<id>.csv): una fila por
    fecha, columnas = date + SUB_VARIABLE_COLUMNS. Devuelve {sub_id: ruta}."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    columns = ["date"] + SUB_VARIABLE_COLUMNS
    written: dict[int, Path] = {}
    for sub_id, group in timeseries.groupby("sub", sort=True):
        csv_path = dest_dir / f"sub_{int(sub_id)}.csv"
        group[columns].to_csv(csv_path, index=False)
        written[int(sub_id)] = csv_path
    return written


def read_sub_timeseries_csv(path: Path | str) -> pd.DataFrame:
    """Lee de vuelta un CSV escrito por export_sub_timeseries_csvs, con "date" ya parseado."""
    return pd.read_csv(path, parse_dates=["date"])


_SUB_CSV_PATTERN = re.compile(r"^sub_(\d+)\.csv$")


def read_sub_timeseries_dir(dest_dir: Path | str) -> pd.DataFrame:
    """Relee todos los sub_<id>.csv de dest_dir (ver export_sub_timeseries_csvs)
    y los combina en un único DataFrame con la columna "sub" de vuelta.
    Permite a la pestaña Results (.sub) mostrar los resultados de una
    corrida anterior de Organize sin volver a parsear el output.sub.

    Devuelve un DataFrame vacío (con las columnas esperadas, sin filas) si
    dest_dir no existe o no tiene ningún sub_*.csv.
    """
    dest_dir = Path(dest_dir)
    frames: list[pd.DataFrame] = []
    if dest_dir.is_dir():
        for csv_path in sorted(dest_dir.glob("sub_*.csv")):
            match = _SUB_CSV_PATTERN.match(csv_path.name)
            if not match:
                continue
            frame = read_sub_timeseries_csv(csv_path)
            frame.insert(0, "sub", int(match.group(1)))
            frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=["sub", "date"] + SUB_VARIABLE_COLUMNS)
    return pd.concat(frames, ignore_index=True)
