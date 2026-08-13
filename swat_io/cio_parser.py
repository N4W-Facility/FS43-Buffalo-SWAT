"""Lectura y escritura acotada de file.cio.

file.cio empieza con líneas de encabezado libres, pero su bloque de
parámetros usa la misma gramática "valor | CODIGO : descripción" que .sub
y .pnd, así que se reutiliza text_format.parse_value_code_file/
write_value_code_file en vez de escribir un parser nuevo: las líneas de
encabezado que no matchean el patrón simplemente se ignoran.

Este módulo solo escribe file.cio a través de write_run_settings(), para
el caso que CLAUDE.md permite explícitamente: "cambio explícito de periodo
simulado pedido por el usuario" -- ahora extendido, por pedido del
usuario (2026-07-31), a también cubrir NYSKIP (años de warm-up excluidos
del output) e IPRINT (frecuencia de impresión), que son configuración de
la corrida, no parámetros físicos del modelo. Ningún otro código de
file.cio (clima, archivos de base de datos, arrays de variables de
output) se toca nunca desde acá.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .text_format import parse_value_code_file, write_value_code_file

PRINT_FREQUENCY_MONTHLY = 0
PRINT_FREQUENCY_DAILY = 1
PRINT_FREQUENCY_YEARLY = 2
_VALID_PRINT_FREQUENCIES = (PRINT_FREQUENCY_MONTHLY, PRINT_FREQUENCY_DAILY, PRINT_FREQUENCY_YEARLY)


class CioParseError(ValueError):
    """file.cio no tiene un NBYR/IYR reconocible."""


@dataclass(frozen=True)
class SimulationPeriod:
    start_year: int
    end_year: int
    n_years: int


@dataclass(frozen=True)
class RunSettings:
    """Subconjunto de file.cio editable desde la pestaña Run: periodo
    simulado, años de warm-up excluidos del output, y frecuencia de
    impresión."""

    start_year: int
    end_year: int
    n_years: int
    years_to_skip: int
    print_frequency: int


def parse_file_cio(path: Path | str) -> SimulationPeriod:
    """Devuelve el periodo simulado (NBYR años, empezando en IYR) de file.cio.

    Lanza CioParseError si falta NBYR o IYR, si no son enteros, o si NBYR
    es menor que 1.
    """
    values = parse_value_code_file(Path(path))
    try:
        n_years = int(values["NBYR"])
        start_year = int(values["IYR"])
    except KeyError as exc:
        raise CioParseError(f"file.cio does not have the code {exc.args[0]}") from exc
    except ValueError as exc:
        raise CioParseError(f"file.cio has a non-integer value for NBYR/IYR: {exc}") from exc

    if n_years < 1:
        raise CioParseError(f"NBYR must be >= 1, found {n_years}")

    return SimulationPeriod(
        start_year=start_year,
        end_year=start_year + n_years - 1,
        n_years=n_years,
    )


def parse_run_settings(path: Path | str) -> RunSettings:
    """Como parse_file_cio, más NYSKIP e IPRINT.

    Lanza CioParseError si falta cualquiera de los cuatro códigos, si
    alguno no es entero, o si los valores encontrados son inconsistentes
    (NBYR < 1, NYSKIP fuera de [0, NBYR)).
    """
    period = parse_file_cio(path)
    values = parse_value_code_file(Path(path))
    try:
        years_to_skip = int(values["NYSKIP"])
        print_frequency = int(values["IPRINT"])
    except KeyError as exc:
        raise CioParseError(f"file.cio does not have the code {exc.args[0]}") from exc
    except ValueError as exc:
        raise CioParseError(f"file.cio has a non-integer value for NYSKIP/IPRINT: {exc}") from exc

    if not 0 <= years_to_skip < period.n_years:
        raise CioParseError(f"NYSKIP must be in [0, {period.n_years}), found {years_to_skip}")

    return RunSettings(
        start_year=period.start_year,
        end_year=period.end_year,
        n_years=period.n_years,
        years_to_skip=years_to_skip,
        print_frequency=print_frequency,
    )


def write_run_settings(
    path: Path | str, *, start_year: int, end_year: int, years_to_skip: int, print_frequency: int
) -> None:
    """Escribe NBYR/IYR/NYSKIP/IPRINT sobre el file.cio real, dejando todo
    lo demás intacto (ver docstring del módulo). Valida antes de escribir;
    no se llega a tocar el archivo si algún valor es inconsistente.
    """
    n_years = end_year - start_year + 1
    if n_years < 1:
        raise ValueError(f"end_year ({end_year}) must be >= start_year ({start_year})")
    if not 0 <= years_to_skip < n_years:
        raise ValueError(f"years_to_skip must be in [0, {n_years}), found {years_to_skip}")
    if print_frequency not in _VALID_PRINT_FREQUENCIES:
        raise ValueError(f"print_frequency must be one of {_VALID_PRINT_FREQUENCIES}, found {print_frequency}")

    write_value_code_file(
        Path(path),
        {
            "NBYR": float(n_years),
            "IYR": float(start_year),
            "NYSKIP": float(years_to_skip),
            "IPRINT": float(print_frequency),
        },
        decimals=0,
    )
