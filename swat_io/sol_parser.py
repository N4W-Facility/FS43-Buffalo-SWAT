"""Lectura de solo lectura de archivos .sol -- únicamente el grupo
hidrológico de suelo (HYDGRP).

Los .sol son de solo lectura para toda la app (ver guía de coberturas del
proyecto, sección 3.3: un cambio de cobertura nunca modifica el suelo), así
que este módulo, a diferencia de .hru/.mgt/plant.dat, no expone escritura.

Gramática (distinta de la "valor | CODIGO : descripción" de .pnd/.sub/.hru):
línea de texto libre "<Label> : <valor>", ej.

    Soil Hydrologic Group: C

Verificado contra los .sol reales de 03-Models/Buffalo/Buffalo_calibrated_annual
(valores A/B/C/D únicamente, sin grupos dobles tipo "A/D" en este proyecto).
Se usa para agrupar CN2 por HSG en el análisis de combinaciones de
parámetros existentes de una cobertura (ver scenarios/nbs_analysis.py).
"""
from __future__ import annotations

import re
from pathlib import Path

from .common.encoding import read_text_with_fallback

_HYDGRP_RE = re.compile(r"Soil Hydrologic Group\s*:\s*(?P<value>\S+)", re.IGNORECASE)


def read_hydrologic_group(path: str | Path) -> str | None:
    """Devuelve el grupo hidrológico de suelo (p. ej. "A", "B", "C", "D")
    declarado en ``path``, o ``None`` si el archivo no lo declara."""
    decoded = read_text_with_fallback(path)
    match = _HYDGRP_RE.search(decoded.text)
    return match.group("value") if match else None
