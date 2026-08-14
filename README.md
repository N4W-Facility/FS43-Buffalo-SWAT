# FS43-Buffalo-SWAT

A Python desktop application (CustomTkinter/Tkinter) for configuring, running, and visualizing **wetland degradation/restoration and land-cover scenarios** on top of an already-calibrated SWAT2012 hydrological model.

The app is an orchestration layer around the external `swat2012.exe` engine — it does not simulate hydrology, recalibrate anything, or reimplement SWAT physics. Its job is:

1. Let the user define a scenario by editing wetland/land-cover parameters on an isolated copy of the model configuration.
2. Run `swat2012.exe` as a local subprocess on that copy.
3. Read the model outputs and visualize them (flow, sediment, nutrients), including comparisons across scenarios.

All screenshots below are from a real project (`Crooked/BaseLine`, 22 subbasins, 1518 HRUs) — no mocked or synthetic data.

## Setup

- Python 3.x, conda environment `swat`.
- Key dependencies: `customtkinter`, `matplotlib`, `pyshp`, `pandas` (plus the standard library `sqlite3`).
- Run with:

  ```
  python main.py
  ```

- The path to `rev670_64rel.exe` is configured inside the app (Run tab) and persisted locally — it is never hardcoded.

## The interface

The app opens with a single window and a row of tabs across the top. Tabs stay disabled until a project (any folder containing `TxtInOut/` directly) is opened from the **Project** tab; from there they follow the natural workflow: configure the scenario (Wetlands, HRUs, NbS) → run it → look at results, with Batch Scenarios at the end since it orchestrates everything else in a series.

## Tabs

### 1. Project

Open or switch the active project folder, edit its name/description, and — in a separate card — point to the subbasin/reach shapefiles used to draw the small maps in the Results tabs. Metadata is cached in a `project.json` file next to `TxtInOut/`.

![Project tab](docs/screenshots/01_project.png)

### 2. Summary

A one-click overview of the project: wetland coverage (subbasin count, wetland area/%) and HRU/land-use stats (HRU count, land-use classes, simulated period), plus a land-use-by-subbasin bar chart. Both summaries are cached, so reopening the project shows the last generated numbers immediately without recomputing.

![Summary tab](docs/screenshots/02_summary.png)

### 3. Wetland Parameters (.pnd)

A read-only table with the 20 "Wetland inputs" parameters as rows and subbasins as columns, read live from the real `.pnd` files. Clicking a column header opens a per-subbasin editor; there's also a bulk path (Load CSV → stage changes in memory → Materialize to SWAT) for editing many subbasins at once without touching disk until you confirm.

![Wetland Parameters tab](docs/screenshots/03_wetlands.png)

### 4. HRU Parameters (.hru)

Same idea as Wetlands, but scoped to one subbasin at a time (a subbasin has many HRUs, not one wetland record): rows are HRUs, columns are every parameter the app recognizes in `.hru`. Supports single-cell inline editing, a full per-HRU editor, CSV export/import for bulk edits, and shows a running `HRU_FR` sum per subbasin (should stay close to 1.0) as an informational check.

![HRU Parameters tab](docs/screenshots/04_hru.png)

### 5. NbS (Nature-based Solutions)

Build a reusable land-cover change ("plant forest here", "restore wetland there") once — covering plant physiology, `.hru` surface parameters, and the full `.mgt` management calendar — then apply it to any HRUs you pick, either one by one, by target area within a subbasin, or by area across every subbasin at once via a CSV. Applying writes directly to the real `.hru`/`.mgt`/`plant.dat` files, so it asks for confirmation and runs in the background.

Every Apply now streams a line per HRU into a live log as it runs, and automatically opens a results window when it's done — a filterable table (errors-only toggle included) so you can spot problems in a large batch without opening the CSV report by hand:

![NbS library and Apply panel](docs/screenshots/05_nbs_library.png)

![NbS Apply — live log and results summary](docs/screenshots/07_nbs_apply_log.png)

![NbS Apply results window, with a real error row highlighted](docs/screenshots/06_nbs_apply_summary.png)

### 6. Run

Configure the SWAT executable path and the run period (`file.cio`: start/end year, warm-up years to skip, print frequency), then run `swat2012.exe` as a subprocess with a live stdout/stderr log. The executable you point at is copied into the scenario's `TxtInOut/` for each run — your original file is never modified or renamed.

![Run tab](docs/screenshots/08_run.png)

### 7. Results (output.rch)

Organizes `output.rch` (flow and loads per reach) into one time series per reach, then lets you plot any of its 47 variables with a small map that highlights the selected reach.

![Results (.rch) tab](docs/screenshots/09_results_rch.png)

### 8. Results (output.sub)

Same idea as above, for the subbasin water balance in `output.sub`.

![Results (.sub) tab](docs/screenshots/10_results_sub.png)

### 9. HRU Results (output.hru)

`output.hru` can be huge (millions of rows across thousands of HRUs), so this tab organizes it into a local SQLite database instead of CSVs, and queries it on demand — nothing is ever fully loaded into memory. Pick a subbasin, HRU, and variable to chart its time series, with several CSV export options (one series, one variable for a whole subbasin, all variables for one HRU, or a custom selection).

![HRU Results tab](docs/screenshots/11_hru_results.png)

### 10. Batch Scenarios

Runs a whole series of scenarios automatically against the open project as a fixed reference: either a land-cover percentage series (e.g. "grow forest to 10%, 20%, 30% of each subbasin") or an NbS applied by area across an increasing percentage series. Each step copies the project, applies the change, runs `swat2012.exe`, and organizes its outputs — with a CSV report per step and a summary CSV across the whole series. A "Compare scenarios..." window can then pull the same variable across every scenario into one file per variable.

![Batch Scenarios tab](docs/screenshots/12_batch.png)

## Notes

- **Scenario isolation is not enforced by the app yet.** Wetlands/HRU Parameters/NbS Apply/Run all write in place on whatever project folder is currently open — including a calibrated reference model, if you point the app at one directly. Treat opening a reference folder as "at your own risk" until an isolation guard is added; Batch Scenarios already works around this by always copying the reference project before writing anything.
- This is purely a text-file orchestration layer: no SWAT Editor automation, and no `.mdb` (SWATGDB/SSURGO) reading or writing anywhere.
- The compute engine is fixed at SWAT2012 rev670 (`rev670_64rel.exe`); the app never modifies or reimplements the hydrology it computes.
