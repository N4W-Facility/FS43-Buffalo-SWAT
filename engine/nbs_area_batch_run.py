"""Orquestación de un batch de aplicación de una NbS por área en serie de
porcentajes (10%, 20%, ..., 100%), pedido explícito del usuario
(2026-08-12): mismo patrón de serie independiente que engine.batch_run
(cada paso se calcula siempre desde el proyecto de referencia, nunca
encadenado; reutiliza ``scenario_folder_name`` para que el nombre de
carpeta sea consistente entre ambas features de batch), pero aplicando una
NbS completa (scenarios.nbs_apply.apply_nbs) sobre el plan de área de
scenarios.nbs_mass_apply/scenarios.nbs_area_apply en vez de la reasignación
simple de HRU_FR que usa el batch de cobertura.

Por cada paso:

1. Copia el proyecto de referencia a ``<destino>/scenario_<pct>pct/``
   (engine.configure.create_working_scenario).
2. Escala el área NbS "al 100%" configurada a ese % (scenarios.
   nbs_area_batch.scale_allocations) y calcula el plan de esa copia
   (scenarios.nbs_mass_apply.plan_mass_area_allocation, ``strict=False`` --
   pedido explícito del usuario: un déficit puntual no debe impedir la
   corrida de SWAT de ese paso, solo quedar documentado en el log y en el
   reporte del paso).
3. Aplica la NbS sobre los targets alcanzables (scenarios.nbs_apply.
   apply_nbs) y escribe su reporte por HRU de siempre
   (scenarios.nbs_apply.write_apply_report_csv) más el reporte de área por
   paso (scenarios.nbs_area_batch.write_area_batch_step_report_csv). Si no
   hay ningún target alcanzable en ningún lado, el paso igual sigue
   adelante y corre SWAT sobre una copia sin cambios -- refleja fielmente
   "a este % no se pudo aplicar nada", coherente con no bloquear la
   corrida por un déficit.
4. Ejecuta swat2012.exe sobre la copia (engine.run.run_scenario).
5. Organiza las salidas que el usuario haya marcado en
   ``OutputOrganizeOptions`` (output.rch/.sub/.hru -- solo si existen), más
   el mismo resumen de coberturas/humedales que ya corre engine.batch_run
   para cada paso.

Un fallo en un paso puntual (copia, cálculo, SWAT, o post-procesamiento) no
aborta el batch completo -- mismo criterio que engine.batch_run.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from engine.batch_run import scenario_folder_name
from engine.configure import create_working_scenario
from engine.run import run_scenario
from generar_resumen_coberturas import generar_resumen_coberturas
from generar_resumen_humedales import generar_resumen_humedales
from scenarios.activity_log import log_action
from scenarios.nbs import NbSDefinition
from scenarios.nbs_apply import apply_nbs, write_apply_report_csv
from scenarios.nbs_area_batch import (
    OutputOrganizeOptions,
    area_batch_step_totals,
    scale_allocations,
    write_area_batch_step_report_csv,
    write_area_batch_summary_csv,
)
from scenarios.nbs_mass_apply import SubbasinAreaAllocation, plan_mass_area_allocation
from swat_io.cio_parser import parse_run_settings
from swat_io.hru_output_parser import build_hru_output_database, hru_output_db_path
from swat_io.rch_parser import build_rch_timeseries, export_rch_timeseries_csvs, parse_rch_file, rch_timeseries_dir
from swat_io.sub_output_parser import (
    build_sub_timeseries,
    export_sub_timeseries_csvs,
    parse_sub_file,
    sub_timeseries_dir,
)

ProgressCallback = Callable[[str], None]


@dataclass
class NbSAreaScenarioResult:
    target_pct: float
    scenario_dir: Path
    status: str  # "ok" | "error"
    error: str | None = None
    applied_count: int = 0
    total_requested_ha: float = 0.0
    total_applied_ha: float = 0.0
    total_deficit_ha: float = 0.0
    area_report_path: Path | None = None


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


def run_nbs_area_batch(
    reference_project_dir: Path,
    destination_dir: Path,
    nbs: NbSDefinition,
    allocations: dict[int, SubbasinAreaAllocation],
    pct_series: list[float],
    swat_executable: Path,
    target_executable_name: str,
    *,
    slope_priority: list[str] | None = None,
    soil_priority: list[str] | None = None,
    output_options: OutputOrganizeOptions | None = None,
    on_progress: ProgressCallback | None = None,
) -> list[NbSAreaScenarioResult]:
    """Corre la serie completa de ``pct_series``, cada paso calculado de
    forma independiente desde ``reference_project_dir`` (que nunca se
    modifica)."""
    reference_project_dir = Path(reference_project_dir)
    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    output_options = output_options or OutputOrganizeOptions()

    log_action(
        reference_project_dir,
        "NBS_BATCH",
        f"Started NbS area batch to '{destination_dir}': nbs='{nbs.name}', series={pct_series}.",
    )

    def report(message: str) -> None:
        if on_progress is not None:
            on_progress(message)

    results: list[NbSAreaScenarioResult] = []
    summary_rows: list[dict] = []
    total_steps = len(pct_series)

    for index, pct in enumerate(pct_series, start=1):
        folder_name = scenario_folder_name(pct)
        step_label = f"[{index}/{total_steps}] {folder_name}"

        try:
            report(f"{step_label}: copying base project...")
            scenario_dir = create_working_scenario(
                destination_dir, reference_project_dir, folder_name,
                on_progress=lambda copied, total: report(f"{step_label}: copying ({copied}/{total})..."),
            )
        except FileExistsError as error:
            results.append(
                NbSAreaScenarioResult(
                    target_pct=pct, scenario_dir=destination_dir / folder_name, status="error", error=str(error),
                )
            )
            summary_rows.append({"target_pct": pct, "scenario_dir": folder_name, "status": "error", "error": str(error)})
            report(f"{step_label}: error -- {error}")
            continue

        try:
            report(f"{step_label}: computing achievable area...")
            scaled = scale_allocations(allocations, pct)
            plan_result = plan_mass_area_allocation(
                scenario_dir, scaled, slope_priority=slope_priority, soil_priority=soil_priority, strict=False,
            )
            area_report_path = write_area_batch_step_report_csv(scenario_dir, pct, plan_result)
            area_totals = area_batch_step_totals(plan_result)
            for subbasin_id, reason in plan_result.skipped.items():
                report(f"{step_label}: subbasin {subbasin_id} skipped -- {reason}")
            for plan in plan_result.plans:
                if plan.total_deficit_ha > 0:
                    report(
                        f"{step_label}: subbasin {plan.subbasin} has a deficit of "
                        f"{plan.total_deficit_ha:.2f} ha (see {area_report_path.name})."
                    )

            targets = plan_result.targets
            applied_count = 0
            if targets:
                report(f"{step_label}: applying the NbS to {len(targets)} HRU...")
                apply_report = apply_nbs(scenario_dir, nbs, targets)
                write_apply_report_csv(scenario_dir, apply_report, datetime.now())
                applied_count = apply_report.applied_count
            else:
                report(f"{step_label}: no HRU achievable at this step -- running SWAT without NbS changes.")

            report(f"{step_label}: running swat2012.exe...")
            run_result = run_scenario(scenario_dir / "TxtInOut", swat_executable, target_executable_name)
            if not run_result.success:
                raise RuntimeError(f"swat2012.exe exited with code {run_result.exit_code}")

            report(f"{step_label}: organizing outputs...")
            _organize_outputs(scenario_dir, output_options, report)

            results.append(
                NbSAreaScenarioResult(
                    target_pct=pct, scenario_dir=scenario_dir, status="ok",
                    applied_count=applied_count,
                    total_requested_ha=area_totals["total_requested_ha"],
                    total_applied_ha=area_totals["total_applied_ha"],
                    total_deficit_ha=area_totals["total_deficit_ha"],
                    area_report_path=area_report_path,
                )
            )
            report(
                f"{step_label}: done. Applied {area_totals['total_applied_ha']:.2f}/"
                f"{area_totals['total_requested_ha']:.2f} ha requested "
                f"({area_totals['subbasins_applied_full']} subbasin(s) in full, "
                f"{area_totals['subbasins_applied_with_deficit']} with deficit, "
                f"{area_totals['subbasins_skipped']} skipped), {applied_count} HRU(s) applied "
                f"(see {area_report_path.name})."
            )
            log_action(
                scenario_dir,
                "NBS_BATCH",
                f"NbS area batch step {folder_name} completed: nbs='{nbs.name}', "
                f"{applied_count} HRU(s) applied, "
                f"{area_totals['total_applied_ha']:.2f}/{area_totals['total_requested_ha']:.2f} ha applied "
                f"({area_totals['subbasins_applied_full']} subbasin(s) in full, "
                f"{area_totals['subbasins_applied_with_deficit']} with deficit, "
                f"{area_totals['subbasins_skipped']} skipped). Detailed report: '{area_report_path}'.",
            )
            summary_rows.append(
                {
                    "target_pct": pct,
                    "scenario_dir": folder_name,
                    "status": "ok",
                    "total_requested_ha": area_totals["total_requested_ha"],
                    "total_applied_ha": area_totals["total_applied_ha"],
                    "total_deficit_ha": area_totals["total_deficit_ha"],
                    "total_hru_count": area_totals["total_hru_count"],
                    "subbasins_applied_full": area_totals["subbasins_applied_full"],
                    "subbasins_applied_with_deficit": area_totals["subbasins_applied_with_deficit"],
                    "subbasins_skipped": area_totals["subbasins_skipped"],
                    "error": None,
                }
            )
        except Exception as error:  # noqa: BLE001 - un paso puntual no debe abortar el batch completo
            results.append(
                NbSAreaScenarioResult(target_pct=pct, scenario_dir=scenario_dir, status="error", error=str(error))
            )
            summary_rows.append({"target_pct": pct, "scenario_dir": folder_name, "status": "error", "error": str(error)})
            report(f"{step_label}: error -- {error}")
            log_action(reference_project_dir, "NBS_BATCH", f"NbS area batch step {folder_name} failed: {error}")

    summary_path = write_area_batch_summary_csv(destination_dir, summary_rows)
    log_action(
        reference_project_dir,
        "NBS_BATCH",
        f"Finished NbS area batch to '{destination_dir}': "
        f"{sum(1 for r in results if r.status == 'ok')}/{len(results)} step(s) succeeded. "
        f"Summary: '{summary_path}'.",
    )

    return results
