"""Orquestación de un batch de escenarios de cambio de cobertura ("aumentar
bosque a X%, incremental"), acordado con el usuario 2026-08-03.

El proyecto abierto es siempre la referencia: nunca se modifica. Por cada
porcentaje de ``LandCoverBatchConfig.target_pct_series`` -- calculado
siempre de forma independiente desde esa misma referencia, nunca
encadenado entre pasos (ver scenarios.land_cover_reallocation) -- este
módulo:

1. Copia la carpeta completa del proyecto a
   ``<destino>/scenario_<pct>pct/`` (engine.configure.create_working_scenario):
   la copia queda con ``TxtInOut/`` directo, lista para abrirse como
   proyecto en la app, tal como pidió el usuario.
2. Calcula el plan de reasignación de ``HRU_FR`` por subcuenca
   (scenarios.land_cover_reallocation.plan_batch_reallocation) y lo
   escribe en los .hru reales de esa copia
   (scenarios.hru_draft.write_hru_values) -- nunca en la referencia.
3. Ejecuta swat2012.exe sobre la copia (engine.run.run_scenario).
4. Corre automáticamente el mismo post-procesamiento que hoy dispara el
   usuario a mano desde Summary/Results/HRU Results:
   generar_resumen_coberturas + generar_resumen_humedales siempre, y
   organizar output.rch (swat_io.rch_parser), output.sub
   (swat_io.sub_output_parser) y output.hru (swat_io.hru_output_parser)
   según ``output_options`` (``OutputOrganizeOptions``, ver
   scenarios/nbs_area_batch.py -- pedido explícito del usuario, 2026-08-12,
   mismo control que ya tenía "NbS area batch": default organiza los tres
   si existen, mismo motivo de siempre por el que puede faltar alguno --
   IPRINT que no genera esa salida).
5. Escribe un reporte del escenario (subcuencas modificadas/omitidas y por
   qué) en ``tool_outputs/batch_report.json`` de esa copia.

Un fallo en un escenario puntual (copia, cálculo, SWAT, o
post-procesamiento) no aborta el batch completo: queda registrado como
error en el resultado de ese escenario y el batch sigue con el siguiente
paso de la serie.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from engine.configure import create_working_scenario
from engine.run import run_scenario
from generar_resumen_coberturas import generar_resumen_coberturas
from generar_resumen_humedales import generar_resumen_humedales
from scenarios.hru_draft import write_hru_values
from scenarios.land_cover_config import LandCoverBatchConfig
from scenarios.land_cover_reallocation import (
    STATUS_APPLIED,
    SubbasinReallocationResult,
    plan_batch_reallocation,
)
# OutputOrganizeOptions se definió originalmente para "NbS area batch" (ver
# scenarios/nbs_area_batch.py), pero pasó a ser compartida por ambas
# secciones de esta pestaña -- pedido explícito del usuario, 2026-08-12:
# quería el mismo control de qué organizar (antes esta función organizaba
# .rch/.hru siempre sin preguntar, y nunca organizaba .sub) también acá.
# Vive en scenarios/ y no en engine/ para no invertir la dirección de
# dependencia (engine depende de scenarios, nunca al revés).
from scenarios.nbs_area_batch import OutputOrganizeOptions
from swat_io.cio_parser import parse_run_settings
from swat_io.hru.models import HRUFile
from swat_io.hru.scanner import parse_hru_directory
from swat_io.hru_output_parser import build_hru_output_database, hru_output_db_path
from swat_io.rch_parser import (
    build_rch_timeseries,
    export_rch_timeseries_csvs,
    parse_rch_file,
    rch_timeseries_dir,
)
from swat_io.sub_output_parser import (
    build_sub_timeseries,
    export_sub_timeseries_csvs,
    parse_sub_file,
    sub_timeseries_dir,
)

ProgressCallback = Callable[[str], None]

BATCH_REPORT_FILENAME = "batch_report.json"


@dataclass
class ScenarioRunResult:
    target_pct: float
    scenario_dir: Path
    status: str  # "ok" | "error"
    error: str | None = None
    reallocation: list[SubbasinReallocationResult] = field(default_factory=list)


def scenario_folder_name(target_pct: float) -> str:
    """Nombre de carpeta determinista para un paso de la serie -- también
    lo usa la UI (preview de escenarios antes de correr el batch), para
    que el nombre mostrado nunca diverja del que realmente se crea."""
    text = f"{target_pct:g}".replace(".", "_")
    return f"scenario_{text}pct"


def _load_all_subbasin_hru_files(txtinout_dir: Path) -> dict[int, dict[int, HRUFile]]:
    """Agrupa todas las HRU de ``txtinout_dir`` por subcuenca, a partir de
    sus propios metadatos (Subbasin/Hru del encabezado del .hru). No
    depende de .sub/.pnd -- swat_io.discovery.discover_subbasins es para
    el módulo de humedales, no aplica al cambio de cobertura."""
    scan = parse_hru_directory(txtinout_dir)
    grouped: dict[int, dict[int, HRUFile]] = {}
    for hru_file in scan.files:
        subbasin = hru_file.metadata.subbasin
        hru_id = hru_file.metadata.hru
        if subbasin is None or hru_id is None:
            continue
        grouped.setdefault(subbasin, {})[hru_id] = hru_file
    return grouped


def _apply_reallocation(
    hru_files_by_subbasin: dict[int, dict[int, HRUFile]],
    results: list[SubbasinReallocationResult],
) -> None:
    for result in results:
        if result.status != STATUS_APPLIED or not result.new_hru_fr:
            continue
        hru_files = hru_files_by_subbasin[result.subbasin]
        for hru_id, new_fr in result.new_hru_fr.items():
            write_hru_values(hru_files[hru_id], {"HRU_FR": new_fr})


def _write_batch_report(
    scenario_dir: Path,
    config: LandCoverBatchConfig,
    target_pct: float,
    results: list[SubbasinReallocationResult],
) -> Path:
    payload = {
        "target_lulc": config.target_lulc,
        "target_pct": target_pct,
        "donor_priority": config.donor_priority,
        "slope_priority": config.slope_priority,
        "soil_priority": config.soil_priority,
        "subbasins": [
            {
                "subbasin": r.subbasin,
                "status": r.status,
                "current_target_pct": r.current_target_pct,
                "notes": r.notes,
            }
            for r in results
        ],
    }
    dest = scenario_dir / "tool_outputs" / BATCH_REPORT_FILENAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return dest


def _organize_outputs(scenario_dir: Path, options: OutputOrganizeOptions, report: ProgressCallback) -> None:
    generar_resumen_coberturas(scenario_dir)
    generar_resumen_humedales(scenario_dir)

    txtinout_dir = scenario_dir / "TxtInOut"
    rch_path = txtinout_dir / "output.rch"
    sub_path = txtinout_dir / "output.sub"
    hru_output_path = txtinout_dir / "output.hru"

    wants_rch = options.rch and rch_path.is_file()
    wants_sub = options.sub and sub_path.is_file()
    wants_hru = options.hru and hru_output_path.is_file()
    if not (wants_rch or wants_sub or wants_hru):
        return

    run_settings = parse_run_settings(txtinout_dir / "file.cio")

    if wants_rch:
        raw = parse_rch_file(rch_path)
        timeseries = build_rch_timeseries(raw, run_settings)
        export_rch_timeseries_csvs(timeseries, rch_timeseries_dir(scenario_dir))

    if wants_sub:
        raw = parse_sub_file(sub_path)
        timeseries = build_sub_timeseries(raw, run_settings)
        export_sub_timeseries_csvs(timeseries, sub_timeseries_dir(scenario_dir))

    if wants_hru:
        build_hru_output_database(
            hru_output_path, run_settings, hru_output_db_path(scenario_dir), report_progress=report
        )


def run_land_cover_batch(
    reference_project_dir: Path,
    destination_dir: Path,
    config: LandCoverBatchConfig,
    swat_executable: Path,
    target_executable_name: str,
    on_progress: ProgressCallback | None = None,
    output_options: OutputOrganizeOptions | None = None,
) -> list[ScenarioRunResult]:
    """Corre la serie completa de ``config.target_pct_series``, cada paso
    calculado de forma independiente desde ``reference_project_dir`` (que
    nunca se modifica).

    ``output_options`` (default None -> ``OutputOrganizeOptions()``, los
    tres en True -- mismo comportamiento "organizar todo lo que exista" que
    ya tenía esta función) elige qué salidas organizar después de cada
    corrida, mismo criterio y mismo tipo que
    ``scenarios.nbs_area_batch.OutputOrganizeOptions`` / la tarjeta "NbS
    area batch" de esta misma pestaña, pedido explícito del usuario
    (2026-08-12) para tener el mismo control acá -- antes esta función
    organizaba .rch/.hru siempre sin preguntar, y nunca organizaba .sub."""
    reference_project_dir = Path(reference_project_dir)
    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    output_options = output_options or OutputOrganizeOptions()

    def report(message: str) -> None:
        if on_progress is not None:
            on_progress(message)

    results: list[ScenarioRunResult] = []
    total_steps = len(config.target_pct_series)

    for index, target_pct in enumerate(config.target_pct_series, start=1):
        folder_name = scenario_folder_name(target_pct)
        step_label = f"[{index}/{total_steps}] {folder_name}"

        try:
            report(f"{step_label}: copying base project...")
            scenario_dir = create_working_scenario(
                destination_dir,
                reference_project_dir,
                folder_name,
                on_progress=lambda copied, total: report(f"{step_label}: copying ({copied}/{total})..."),
            )
        except FileExistsError as error:
            results.append(
                ScenarioRunResult(
                    target_pct=target_pct,
                    scenario_dir=destination_dir / folder_name,
                    status="error",
                    error=str(error),
                )
            )
            report(f"{step_label}: error -- {error}")
            continue

        try:
            txtinout_dir = scenario_dir / "TxtInOut"

            report(f"{step_label}: computing area reallocation...")
            hru_files_by_subbasin = _load_all_subbasin_hru_files(txtinout_dir)
            reallocation_results = plan_batch_reallocation(
                hru_files_by_subbasin,
                target_lulc=config.target_lulc,
                target_pct=target_pct,
                donor_priority=config.donor_priority,
                slope_priority=config.slope_priority,
                soil_priority=config.soil_priority,
            )
            _apply_reallocation(hru_files_by_subbasin, reallocation_results)
            _write_batch_report(scenario_dir, config, target_pct, reallocation_results)

            report(f"{step_label}: running swat2012.exe...")
            run_result = run_scenario(txtinout_dir, swat_executable, target_executable_name)
            if not run_result.success:
                raise RuntimeError(f"swat2012.exe exited with code {run_result.exit_code}")

            report(f"{step_label}: organizing outputs...")
            _organize_outputs(scenario_dir, output_options, report)

            results.append(
                ScenarioRunResult(
                    target_pct=target_pct,
                    scenario_dir=scenario_dir,
                    status="ok",
                    reallocation=reallocation_results,
                )
            )
            report(f"{step_label}: done.")
        except Exception as error:  # noqa: BLE001 - un escenario no debe abortar el batch completo
            results.append(
                ScenarioRunResult(target_pct=target_pct, scenario_dir=scenario_dir, status="error", error=str(error))
            )
            report(f"{step_label}: error -- {error}")

    return results
