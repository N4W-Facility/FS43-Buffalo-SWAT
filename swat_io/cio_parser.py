"""Lectura de solo lectura del periodo simulado declarado en file.cio.

file.cio empieza con líneas de encabezado libres, pero su bloque de
parámetros usa la misma gramática "valor | CODIGO : descripción" que .sub
y .pnd, así que se reutiliza text_format.parse_value_code_file en vez de
escribir un parser nuevo: las líneas de encabezado que no matchean el
patrón simplemente se ignoran.

Este módulo nunca escribe file.cio: CLAUDE.md solo permite tocar ese
archivo ante un cambio explícito de periodo simulado pedido por el
usuario, algo fuera de alcance de este módulo.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .text_format import parse_value_code_file


class CioParseError(ValueError):
    """file.cio no tiene un NBYR/IYR reconocible."""


@dataclass(frozen=True)
class SimulationPeriod:
    start_year: int
    end_year: int
    n_years: int


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
        raise CioParseError(f"file.cio no tiene el código {exc.args[0]}") from exc
    except ValueError as exc:
        raise CioParseError(f"file.cio tiene un valor no entero para NBYR/IYR: {exc}") from exc

    if n_years < 1:
        raise CioParseError(f"NBYR debe ser >= 1, se encontró {n_years}")

    return SimulationPeriod(
        start_year=start_year,
        end_year=start_year + n_years - 1,
        n_years=n_years,
    )
