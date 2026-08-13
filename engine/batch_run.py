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
5. Escribe un reporte del escenario (una fila por subcuenca: aplicada,
   omitida y por qué, o aplicada con déficit de área donante, más una fila
   TOTAL con los agregados del paso) en ``tool_outputs/batch_report.csv``
   de esa copia -- CSV (no JSON, como antes de 2026-08-13), mismo formato
   que ``scenarios.nbs_area_batch.write_area_batch_step_report_csv``,
   pedido explícito del usuario: quería poder abrirlo directo en Excel y
   ver de un vistazo cuántas subcuencas se aplicaron completas, cuántas
   con déficit, y cuántas se omitieron -- antes esto quedaba enterrado en
   notas de texto libre dentro de un JSON. Al terminar la serie completa
   también escribe ``<destino>/land_cover_batch_summary.csv``, una fila
   por paso de la serie, para comparar escenarios entre sí sin abrir cada
   carpeta.

Un fallo en un escenario puntual (copia, cálculo, SWAT, o
post-procesamiento) no aborta el batch completo: queda registrado como
error en el resultado de ese escenario y el batch sigue con el siguiente
paso de la serie.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

from engine.configure import create_working_scenario
from engine.run import run_scenario
from generar_resumen_coberturas import generar_resumen_coberturas
from generar_resumen_humedales import generar_resumen_humedales
from scenarios.activity_log import log_action
from scenarios.hru_draft import write_hru_values
from scenarios.land_cover_config import LandCoverBatchConfig
from scenarios.land_cover_reallocation import (
    STATUS_APPLIED,
    STATUS_SKIPPED_NO_TARGET_HRU,
    STATUS_SKIPPED_TARGET_ALREADY_MET,
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

BATCH_REPORT_FILENAME = "batch_report.csv"
BATCH_SUMMARY_FILENAME = "land_cover_batch_summary.csv"


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


_DEFICIT_TOLERANCE = 1e-6


def _batch_step_totals(results: list[SubbasinReallocationResult]) -> dict:
    """Agregados de un paso de la serie, reutilizados por el reporte CSV del
    escenario, el log en vivo, activity_log.txt, y el resumen entre
    escenarios -- un solo lugar que define qué cuenta como "aplicada
    completa" vs. "aplicada con déficit" vs. "omitida", para que las
    cuatro salidas nunca diverjan entre sí."""
    applied_full = sum(1 for r in results if r.status == STATUS_APPLIED and r.deficit_pct <= _DEFICIT_TOLERANCE)
    applied_with_deficit = sum(1 for r in results if r.status == STATUS_APPLIED and r.deficit_pct > _DEFICIT_TOLERANCE)
    skipped_no_target = sum(1 for r in results if r.status == STATUS_SKIPPED_NO_TARGET_HRU)
    skipped_already_met = sum(1 for r in results if r.status == STATUS_SKIPPED_TARGET_ALREADY_MET)
    hru_count_changed = sum(len(r.new_hru_fr) for r in results)
    return {
        "subbasins_total": len(results),
        "subbasins_applied_full": applied_full,
        "subbasins_applied_with_deficit": applied_with_deficit,
        "subbasins_skipped_no_target_hru": skipped_no_target,
        "subbasins_skipped_target_already_met": skipped_already_met,
        "hru_count_changed": hru_count_changed,
    }


def _write_batch_report_csv(
    scenario_dir: Path,
    target_pct: float,
    results: list[SubbasinReallocationResult],
) -> Path:
    rows = [
        {
            "target_pct": target_pct,
            "subbasin": r.subbasin,
            "status": r.status,
            "current_pct_before": round(r.current_target_pct, 4),
            "target_pct_requested": target_pct,
            "deficit_pct": round(r.deficit_pct, 4),
            "hru_count_changed": len(r.new_hru_fr),
            "notes": "; ".join(r.notes),
        }
        for r in results
    ]

    totals = _batch_step_totals(results)
    rows.append(
        {
            "target_pct": target_pct,
            "subbasin": "TOTAL",
            "status": "summary",
            "current_pct_before": None,
            "target_pct_requested": target_pct,
            "deficit_pct": None,
            "hru_count_changed": totals["hru_count_changed"],
            "notes": (
                f"{totals['subbasins_applied_full']} applied in full, "
                f"{totals['subbasins_applied_with_deficit']} applied with deficit, "
                f"{totals['subbasins_skipped_no_target_hru']} skipped (no target coverage), "
                f"{totals['subbasins_skipped_target_already_met']} skipped (target already met), "
                f"out of {totals['subbasins_total']} subbasin(s)."
            ),
        }
    )

    columns = [
        "target_pct", "subbasin", "status", "current_pct_before", "target_pct_requested",
        "deficit_pct", "hru_count_changed", "notes",
    ]
    df = pd.DataFrame(rows, columns=columns)
    dest = scenario_dir / "tool_outputs" / BATCH_REPORT_FILENAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest, index=False)
    return dest


def _write_batch_summary_csv(destination_dir: Path, rows: list[dict]) -> Path:
    """Un resumen del batch completo, una fila por paso de la serie -- para
    comparar escenarios entre sí sin tener que abrir cada carpeta y su
    batch_report.csv individual (pedido explícito del usuario, 2026-08-13:
    "cuanto más detalle mejor"). Vive en la raíz de destination_dir, no
    dentro de ninguna copia de escenario puntual."""
    columns = [
        "target_pct", "scenario_dir", "status", "subbasins_applied_full", "subbasins_applied_with_deficit",
        "subbasins_skipped_no_target_hru", "subbasins_skipped_target_already_met", "hru_count_changed", "error",
    ]
    df = pd.DataFrame(rows, columns=columns)
    dest = Path(destination_dir) / BATCH_SUMMARY_FILENAME
    df.to_csv(dest, index=False)
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

    log_action(
        reference_project_dir,
        "BATCH",
        f"Started land-cover batch to '{destination_dir}': target={config.target_lulc}, "
        f"series={config.target_pct_series}.",
    )

    def report(message: str) -> None:
        if on_progress is not None:
            on_progress(message)

    results: list[ScenarioRunResult] = []
    summary_rows: list[dict] = []
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
            summary_rows.append({"target_pct": target_pct, "scenario_dir": folder_name, "status": "error", "error": str(error)})
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
            report_path = _write_batch_report_csv(scenario_dir, target_pct, reallocation_results)

            for r in reallocation_results:
                if r.status == STATUS_SKIPPED_NO_TARGET_HRU:
                    report(f"{step_label}: subbasin {r.subbasin} skipped -- no HRU with the target coverage.")
                elif r.status == STATUS_SKIPPED_TARGET_ALREADY_MET:
                    report(
                        f"{step_label}: subbasin {r.subbasin} skipped -- already at "
                        f"{r.current_target_pct:.2f}% (>= {target_pct:.2f}% requested)."
                    )
                elif r.deficit_pct > _DEFICIT_TOLERANCE:
                    report(
                        f"{step_label}: subbasin {r.subbasin} applied with a deficit of "
                        f"{r.deficit_pct:.2f} percentage points (not enough donor area)."
                    )

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
            totals = _batch_step_totals(reallocation_results)
            report(
                f"{step_label}: done. {totals['subbasins_applied_full']}/{totals['subbasins_total']} subbasin(s) "
                f"applied in full, {totals['subbasins_applied_with_deficit']} with deficit, "
                f"{totals['subbasins_skipped_no_target_hru'] + totals['subbasins_skipped_target_already_met']} skipped, "
                f"{totals['hru_count_changed']} HRU(s) changed (see {report_path.name})."
            )
            log_action(
                scenario_dir,
                "BATCH",
                f"Land-cover batch step {folder_name} completed: "
                f"{totals['subbasins_applied_full']} applied in full, "
                f"{totals['subbasins_applied_with_deficit']} applied with deficit, "
                f"{totals['subbasins_skipped_no_target_hru'] + totals['subbasins_skipped_target_already_met']} skipped, "
                f"{totals['hru_count_changed']} HRU(s) changed. Detailed report: '{report_path}'.",
            )
            summary_rows.append(
                {
                    "target_pct": target_pct,
                    "scenario_dir": folder_name,
                    "status": "ok",
                    "subbasins_applied_full": totals["subbasins_applied_full"],
                    "subbasins_applied_with_deficit": totals["subbasins_applied_with_deficit"],
                    "subbasins_skipped_no_target_hru": totals["subbasins_skipped_no_target_hru"],
                    "subbasins_skipped_target_already_met": totals["subbasins_skipped_target_already_met"],
                    "hru_count_changed": totals["hru_count_changed"],
                    "error": None,
                }
            )
        except Exception as error:  # noqa: BLE001 - un escenario no debe abortar el batch completo
            results.append(
                ScenarioRunResult(target_pct=target_pct, scenario_dir=scenario_dir, status="error", error=str(error))
            )
            summary_rows.append({"target_pct": target_pct, "scenario_dir": folder_name, "status": "error", "error": str(error)})
            report(f"{step_label}: error -- {error}")
            log_action(reference_project_dir, "BATCH", f"Land-cover batch step {folder_name} failed: {error}")

    summary_path = _write_batch_summary_csv(destination_dir, summary_rows)
    log_action(
        reference_project_dir,
        "BATCH",
        f"Finished land-cover batch to '{destination_dir}': "
        f"{sum(1 for r in results if r.status == 'ok')}/{len(results)} step(s) succeeded. "
        f"Summary: '{summary_path}'.",
    )

    return results
