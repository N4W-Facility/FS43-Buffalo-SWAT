"""Análisis de combinaciones de parámetros existentes para una cobertura,
usado en el paso "copiar de una configuración existente" del wizard de NbS.

Dado el proyecto abierto (calibrado o no) y una cobertura objetivo (CPNM),
escanea las HRU que hoy tienen esa cobertura (Luse, ver swat_io.hru.scanner)
y agrupa los parámetros .hru/.mgt/calendario reales en combinaciones
exactas (con tolerancia de redondeo) -- el usuario elige una fila completa
como base de su NbS en vez de partir de cero (pedido explícito del
usuario). El grupo hidrológico de suelo (HYDGRP, ver swat_io.sol_parser)
se excluye deliberadamente de la clave de agrupación porque CN2 debe variar
por HSG (ver guía del proyecto, sección 10): dentro de cada combinación se
reporta el CN2 típico observado por cada HSG, no un único valor.

Es de solo lectura (nunca escribe nada) y puede tardar sobre un TxtInOut
real (miles de .hru/.mgt/.sol) -- pensado para correr en hilo de fondo
desde la UI (ui.tasks.run_in_background), mismo patrón que el resto de
operaciones largas de la app.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from swat_io.hru.parser import parse_hru_file
from swat_io.hru.scanner import find_hru_files
from swat_io.mgt.parser import parse_mgt_file
from swat_io.sol_parser import read_hydrologic_group

from .nbs import NbSOperation

_ROUND_DECIMALS = 4

_HRU_PARAM_NAMES: tuple[str, ...] = ("CANMX", "OV_N", "RSDIN")
_MGT_INITIAL_NAMES: tuple[str, ...] = ("IGRO", "LAI_INIT", "BIO_INIT", "PHU_PLT")


def _round(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round(float(value), _ROUND_DECIMALS)
    return value


@dataclass
class ExistingHRUSample:
    """Una HRU real que hoy tiene la cobertura objetivo."""

    subbasin: int
    hru: int
    hydrologic_group: str | None
    hru_params: dict[str, float | None]
    mgt_initial: dict[str, float | int | None]
    cn2: float | None
    operations: list[NbSOperation]


@dataclass
class ParameterCombination:
    """Una combinación distinta de parámetros .hru/.mgt/calendario
    observada entre las HRU reales de la cobertura objetivo."""

    hru_params: dict[str, float | None]
    mgt_initial: dict[str, float | int | None]
    cn2_by_hsg: dict[str, float]
    operations: list[NbSOperation]
    hru_count: int
    subbasins: list[int]
    sample_hru: tuple[int, int]


def _operation_signature(operations: list[NbSOperation]) -> tuple:
    return tuple(
        (
            op.mgt_op,
            op.month,
            op.day,
            _round(op.husc),
            tuple(sorted((k, _round(v)) for k, v in op.fields.items())),
        )
        for op in operations
    )


def _load_sample(hru_path: Path, hru_file) -> ExistingHRUSample | None:
    if hru_file.metadata.subbasin is None or hru_file.metadata.hru is None:
        return None

    mgt_path = hru_path.with_suffix(".mgt")
    sol_path = hru_path.with_suffix(".sol")
    if not mgt_path.exists():
        return None

    mgt_file = parse_mgt_file(mgt_path)
    hydgrp = read_hydrologic_group(sol_path) if sol_path.exists() else None

    hru_params = {name: hru_file.get_value(name) for name in _HRU_PARAM_NAMES}
    mgt_initial = {name: mgt_file.get_header_value(name) for name in _MGT_INITIAL_NAMES}
    cn2 = mgt_file.get_header_value("CN2")

    operations = [
        NbSOperation(mgt_op=op.mgt_op, month=op.month, day=op.day, husc=op.husc, fields=dict(op.fields))
        for op in mgt_file.operations()
    ]

    return ExistingHRUSample(
        subbasin=hru_file.metadata.subbasin,
        hru=hru_file.metadata.hru,
        hydrologic_group=hydgrp,
        hru_params=hru_params,
        mgt_initial=mgt_initial,
        cn2=float(cn2) if cn2 is not None else None,
        operations=operations,
    )


def collect_existing_samples(txtinout_dir: str | Path, target_lulc: str) -> list[ExistingHRUSample]:
    """HRU reales cuya cobertura actual (Luse) coincide con ``target_lulc``
    (comparación sin distinguir mayúsculas/minúsculas)."""
    target_upper = target_lulc.upper()
    samples: list[ExistingHRUSample] = []
    for hru_path in find_hru_files(txtinout_dir, recursive=False):
        hru_file = parse_hru_file(hru_path)
        land_use = hru_file.metadata.land_use
        if land_use is None or land_use.upper() != target_upper:
            continue
        sample = _load_sample(hru_path, hru_file)
        if sample is not None:
            samples.append(sample)
    return samples


def group_into_combinations(samples: list[ExistingHRUSample]) -> list[ParameterCombination]:
    """Agrupa ``samples`` por combinación exacta (redondeada) de
    hru_params + mgt_initial + calendario, excluyendo CN2/HSG de la clave.
    Devuelve las combinaciones ordenadas de más a menos HRU."""
    groups: dict[tuple, list[ExistingHRUSample]] = {}
    order: list[tuple] = []

    for sample in samples:
        key = (
            tuple(sorted((k, _round(v)) for k, v in sample.hru_params.items())),
            tuple(sorted((k, _round(v)) for k, v in sample.mgt_initial.items())),
            _operation_signature(sample.operations),
        )
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(sample)

    combinations: list[ParameterCombination] = []
    for key in order:
        members = groups[key]
        representative = members[0]

        cn2_by_hsg: dict[str, float] = {}
        by_hsg: dict[str, list[float]] = {}
        for member in members:
            if member.hydrologic_group is None or member.cn2 is None:
                continue
            by_hsg.setdefault(member.hydrologic_group, []).append(member.cn2)
        for hsg, values in by_hsg.items():
            # Valor más frecuente dentro del HSG; ante empate, el primero
            # visto (orden estable de Counter.most_common).
            cn2_by_hsg[hsg] = Counter(values).most_common(1)[0][0]

        combinations.append(
            ParameterCombination(
                hru_params=representative.hru_params,
                mgt_initial=representative.mgt_initial,
                cn2_by_hsg=cn2_by_hsg,
                operations=representative.operations,
                hru_count=len(members),
                subbasins=sorted({m.subbasin for m in members}),
                sample_hru=(representative.subbasin, representative.hru),
            )
        )

    combinations.sort(key=lambda c: c.hru_count, reverse=True)
    return combinations


def scan_existing_parameter_combinations(txtinout_dir: str | Path, target_lulc: str) -> list[ParameterCombination]:
    """Punto de entrada único: escanea y agrupa en un solo paso."""
    samples = collect_existing_samples(txtinout_dir, target_lulc)
    return group_into_combinations(samples)
