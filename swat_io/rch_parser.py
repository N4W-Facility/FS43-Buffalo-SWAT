"""Parseo de output.rch: caudal y cargas por tramo (reach) de SWAT.

output.rch es texto de ancho fijo, pero su línea de encabezado (la que
trae los nombres "RCH GIS MON AREAkm2 FLOW_INcms ...") no se puede separar
de forma confiable por espacios: cuando un nombre+unidad excede el ancho
reservado para esa columna, queda pegado al siguiente sin espacio (ej.
"SOLPST_INmgSOLPST_OUTmg", cuatro nombres seguidos en
"SETTLPSTmgRESUSP_PSTmgDIFFUSEPSTmgREACBEDPSTmg"). El layout de 47
variables después de RCH/GIS/MON es fijo y estable en SWAT2012 rev670 (el
motor fijo del proyecto, ver CLAUDE.md) -- en vez de parsear ese
encabezado roto, este módulo usa una lista fija de nombres
(RCH_VARIABLE_COLUMNS), verificada contra un output.rch real contando el
número de valores numéricos por fila de datos (esas SÍ vienen separadas
por espacios sin ambigüedad).
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

RCH_VARIABLE_COLUMNS: list[str] = [
    "AREA", "FLOW_IN", "FLOW_OUT", "EVAP", "TLOSS", "SED_IN", "SED_OUT", "SEDCONC",
    "ORGN_IN", "ORGN_OUT", "ORGP_IN", "ORGP_OUT", "NO3_IN", "NO3_OUT", "NH4_IN", "NH4_OUT",
    "NO2_IN", "NO2_OUT", "MINP_IN", "MINP_OUT", "CHLA_IN", "CHLA_OUT", "CBOD_IN", "CBOD_OUT",
    "DISOX_IN", "DISOX_OUT", "SOLPST_IN", "SOLPST_OUT", "SORPST_IN", "SORPST_OUT", "REACTPST",
    "VOLPST", "SETTLPST", "RESUSP_PST", "DIFFUSEPST", "REACBEDPST", "BURYPST", "BED_PST",
    "BACTP_OUT", "BACTLP_OUT", "CMETAL_1", "CMETAL_2", "CMETAL_3", "TOT_N", "TOT_P",
    "NO3_CONC", "WTMP",
]

_DATA_ROW_PREFIX = "REACH"
_RCH_OUTPUT_DIRNAME = "rch_timeseries"
# Un MON menor a esto en salida Yearly es la fila de resumen "average
# annual" (conteo de años promediados, ej. 3), no un año calendario real
# (ej. 2017) -- ver build_rch_timeseries.
_YEARLY_SUMMARY_MON_THRESHOLD = 1000


class RchParseError(ValueError):
    """output.rch no tiene el formato esperado (una fila de datos no trae exactamente
    3 + len(RCH_VARIABLE_COLUMNS) valores numéricos tras el prefijo REACH)."""


def parse_rch_file(path: Path | str) -> pd.DataFrame:
    """Parsea todas las filas de datos de output.rch.

    Devuelve un DataFrame con una fila por registro del archivo (un reach
    en un paso de tiempo), preservando el orden original del archivo --
    build_rch_timeseries depende de ese orden para reconstruir fechas
    reales en salidas Monthly/Daily, donde la columna MON por sí sola no
    trae el año. Columnas: "reach", "gis", "mon", más una por cada
    RCH_VARIABLE_COLUMNS.
    """
    path = Path(path)
    expected_len = 3 + len(RCH_VARIABLE_COLUMNS)
    rows: list[list[float]] = []

    text = read_text_with_fallback(path).text
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith(_DATA_ROW_PREFIX):
            continue
        tokens = stripped.split()[1:]
        if len(tokens) != expected_len:
            raise RchParseError(
                f"{path.name}:{line_number}: expected {expected_len} values after RCH/GIS/MON, "
                f"found {len(tokens)}"
            )
        try:
            rows.append([float(token) for token in tokens])
        except ValueError as exc:
            raise RchParseError(f"{path.name}:{line_number}: non-numeric value ({exc})") from exc

    if not rows:
        raise RchParseError(f"{path.name}: no data row was found (prefix 'REACH')")

    columns = ["reach", "gis", "mon"] + RCH_VARIABLE_COLUMNS
    df = pd.DataFrame(rows, columns=columns)
    df["reach"] = df["reach"].astype(int)
    df["gis"] = df["gis"].astype(int)
    df["mon"] = df["mon"].astype(int)
    return df


def build_rch_timeseries(df: pd.DataFrame, run_settings: RunSettings) -> pd.DataFrame:
    """Agrega una columna "date" (datetime64) a las filas parseadas, según
    la frecuencia de impresión de la corrida (run_settings.print_frequency,
    de swat_io.cio_parser.parse_run_settings).

    - Yearly: MON es el año calendario en las filas reales, pero SWAT
      agrega una fila extra por reach al final con el "average annual"
      de la corrida, donde MON no es un año sino la cantidad de años
      promediados (verificado contra un output.rch real: 3 filas con
      MON=2017/2018/2019 más una cuarta con MON=3 para una corrida de 3
      años de output) -- esa fila se descarta (ver
      _YEARLY_SUMMARY_MON_THRESHOLD).
    - Monthly: MON es el mes (1-12) dentro del bloque anual actual, salvo
      una 13a fila por año y por reach que trae el resumen anual con
      MON = año (confirmado explícitamente para este proyecto) -- esa fila
      se descarta de la serie mensual, no se mezcla con las 12 fechas
      reales.
    - Daily: MON es el día juliano (1-365/366) dentro del año actual.

    En Monthly/Daily el año de cada bloque se detecta por "wrap-around" de
    MON (un valor <= al de la fila anterior de ese mismo reach implica que
    se pasó al año siguiente), arrancando en run_settings.start_year +
    run_settings.years_to_skip (los años de warm-up no se imprimen en el
    output, ver CLAUDE.md/RunTab). No depende de contar días de
    calendario/años bisiestos: el propio archivo ya trae el conteo
    correcto de filas por año.
    """
    start_year = run_settings.start_year + run_settings.years_to_skip

    if run_settings.print_frequency == PRINT_FREQUENCY_YEARLY:
        result = df[df["mon"] >= _YEARLY_SUMMARY_MON_THRESHOLD].copy()
        result["date"] = pd.to_datetime(result["mon"].astype(str), format="%Y")
        return result.drop(columns=["mon"]).sort_values(["reach", "date"]).reset_index(drop=True)

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
    for _, group in df.groupby("reach", sort=False):
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
    return result.sort_values(["reach", "date"]).reset_index(drop=True)


def rch_timeseries_dir(project_dir: Path | str) -> Path:
    """tool_outputs/rch_timeseries/ del proyecto, creándola si no existe."""
    path = tool_outputs_dir(project_dir) / _RCH_OUTPUT_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def export_rch_timeseries_csvs(timeseries: pd.DataFrame, dest_dir: Path | str) -> dict[int, Path]:
    """Escribe un CSV por reach en dest_dir (reach_<id>.csv): una fila por
    fecha, columnas = date + RCH_VARIABLE_COLUMNS. Devuelve {reach_id: ruta}."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    columns = ["date"] + RCH_VARIABLE_COLUMNS
    written: dict[int, Path] = {}
    for reach_id, group in timeseries.groupby("reach", sort=True):
        csv_path = dest_dir / f"reach_{int(reach_id)}.csv"
        group[columns].to_csv(csv_path, index=False)
        written[int(reach_id)] = csv_path
    return written


def read_rch_timeseries_csv(path: Path | str) -> pd.DataFrame:
    """Lee de vuelta un CSV escrito por export_rch_timeseries_csvs, con "date" ya parseado."""
    return pd.read_csv(path, parse_dates=["date"])


_REACH_CSV_PATTERN = re.compile(r"^reach_(\d+)\.csv$")


def read_rch_timeseries_dir(dest_dir: Path | str) -> pd.DataFrame:
    """Relee todos los reach_<id>.csv de dest_dir (ver export_rch_timeseries_csvs)
    y los combina en un único DataFrame con la columna "reach" de vuelta
    (cada CSV individual no la trae, ya que es redundante dentro de su
    propio archivo). Permite a la pestaña Results mostrar los resultados de
    una corrida anterior de Organize sin volver a parsear output.rch.

    Devuelve un DataFrame vacío (con las columnas esperadas, sin filas) si
    dest_dir no existe o no tiene ningún reach_*.csv.
    """
    dest_dir = Path(dest_dir)
    frames: list[pd.DataFrame] = []
    if dest_dir.is_dir():
        for csv_path in sorted(dest_dir.glob("reach_*.csv")):
            match = _REACH_CSV_PATTERN.match(csv_path.name)
            if not match:
                continue
            frame = read_rch_timeseries_csv(csv_path)
            frame.insert(0, "reach", int(match.group(1)))
            frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=["reach", "date"] + RCH_VARIABLE_COLUMNS)
    return pd.concat(frames, ignore_index=True)
