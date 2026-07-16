# Panel de escenarios de referencia y ventana Wetlands — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the create/open-project flow, the embedded parametrización view, and the "Configurar escenario" execution-prep button with: a generic "Abrir proyecto" folder browser, a right-hand panel to pick a read-only reference scenario, a "Cargar" action that names and copies a new working scenario, and a "Parametrización → Wetlands" menu that opens a separate table window with Cargar CSV / Guardar / Cancelar.

**Architecture:** Same layered structure as today (`swat_io/` → `scenarios/` → `engine/` → `ui/`). `Project` shrinks to a bare `project_dir`. A new `discover_scenario_folders` finds reference candidates. `scenarios/draft.py` keeps its CSV-borrador mechanics but is re-pointed at an explicit `txtinout_dir` instead of deriving one from `Project`. `engine/configure.py` splits into `create_working_scenario` (whole-folder copy, runs on "Cargar") and `apply_draft_to_pnd` (writes the borrador to real `.pnd` files, runs on "Guardar"). The old embedded `ParametrizacionView` becomes a `CTkToplevel` (`WetlandsWindow`).

**Tech Stack:** Python 3.x, CustomTkinter/Tkinter, pandas, pytest.

## Global Constraints

- Nunca escribir sobre la carpeta de escenario de referencia elegida por el usuario (calibrada o no) — toda edición ocurre solo en la copia nombrada por el usuario. (CLAUDE.md, no negociable)
- El renombrado/colocación del ejecutable SWAT y cualquier invocación de `swat2012.exe` quedan fuera de alcance de este plan.
- Nombre de escenario de trabajo sigue `{Watershed}_{Abbrev}_{timestep}` vía `build_scenario_name` ya existente (`scenarios/models.py`), con `Watershed = project_dir.name`.
- No tocar `config/settings.py`, `ui/config_dialog.py`, ni sus tests — el gate de configuración de rutas queda fuera de alcance de este plan.
- No eliminar `discover_base_models`/`BaseModelInfo` de `swat_io/discovery.py` — quedan sin uso pero fuera de alcance de este plan (podrían servir a una futura pantalla de creación de proyecto).
- Todos los tests existentes deben seguir en verde salvo los que este plan reescribe explícitamente.

---

### Task 1: Simplify `Project` and remove the old project-creation helper

**Files:**
- Modify: `scenarios/models.py:9-14` (the `Project` dataclass)
- Delete: `scenarios/project.py`
- Delete: `tests/scenarios/test_project.py`
- Modify: `tests/scenarios/test_models.py` (no field changes needed — it only tests `build_scenario_name`/`WETLAND_ABBREVIATIONS`, already independent of `Project`)

**Interfaces:**
- Produces: `Project(project_dir: Path)` — a frozen dataclass with a single field, used by every other task in this plan.

- [ ] **Step 1: Update `Project` to a single field**

Edit `scenarios/models.py`:

```python
@dataclass(frozen=True)
class Project:
    project_dir: Path
```

(Replaces the four-field version — remove `watershed`, `base_model_dir`, `base_txtinout_dir`.)

- [ ] **Step 2: Delete the now-obsolete project-creation helper**

```bash
rm scenarios/project.py tests/scenarios/test_project.py
```

- [ ] **Step 3: Run the scenarios test suite to confirm nothing else references the deleted module**

Run: `pytest tests/scenarios -v`
Expected: all tests pass (no import errors from `scenarios.project`).

- [ ] **Step 4: Commit**

```bash
git add scenarios/models.py
git rm scenarios/project.py tests/scenarios/test_project.py
git commit -m "refactor: simplify Project to a bare project_dir"
```

---

### Task 2: Discover scenario folders inside a project directory

**Files:**
- Modify: `swat_io/discovery.py` (add alongside existing `discover_base_models`/`discover_subbasins`)
- Test: `tests/swat_io/test_discovery.py` (add new tests; keep existing ones)

**Interfaces:**
- Consumes: `_SUB_FILENAME` regex already defined in `swat_io/discovery.py`.
- Produces: `ScenarioFolder(name: str, dir: Path, txtinout_dir: Path)` and `discover_scenario_folders(project_dir: Path) -> list[ScenarioFolder]`, used by Task 5 (`ui/project_window.py`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/swat_io/test_discovery.py`:

```python
from swat_io.discovery import discover_scenario_folders


def test_discover_scenario_folders_finds_subfolders_with_txtinout(tmp_path: Path) -> None:
    calibrated = tmp_path / "Buffalo_calibrated_annual" / "TxtInOut"
    calibrated.mkdir(parents=True)
    (calibrated / "000010000.sub").write_text("x")
    gi = tmp_path / "Buffalo_GI_annual" / "TxtInOut"
    gi.mkdir(parents=True)
    (gi / "000010000.sub").write_text("x")
    (tmp_path / "not_a_scenario.txt").write_text("x")

    folders = discover_scenario_folders(tmp_path)

    names = sorted(f.name for f in folders)
    assert names == ["Buffalo_GI_annual", "Buffalo_calibrated_annual"]


def test_discover_scenario_folders_skips_subfolders_without_valid_sub_files(tmp_path: Path) -> None:
    empty_txtinout = tmp_path / "Empty_annual" / "TxtInOut"
    empty_txtinout.mkdir(parents=True)

    folders = discover_scenario_folders(tmp_path)

    assert folders == []


def test_discover_scenario_folders_returns_empty_for_missing_project_dir(tmp_path: Path) -> None:
    assert discover_scenario_folders(tmp_path / "does_not_exist") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/swat_io/test_discovery.py -v`
Expected: FAIL with `ImportError: cannot import name 'discover_scenario_folders'`

- [ ] **Step 3: Implement `ScenarioFolder` and `discover_scenario_folders`**

Append to `swat_io/discovery.py` (after `discover_base_models`, before or after `discover_subbasins` — module already imports `re`, `dataclass`, `Path`):

```python
@dataclass(frozen=True)
class ScenarioFolder:
    name: str
    dir: Path
    txtinout_dir: Path


def discover_scenario_folders(project_dir: Path) -> list["ScenarioFolder"]:
    """Lista las subcarpetas directas de project_dir que son escenarios válidos.

    Un escenario válido es cualquier subcarpeta con TxtInOut/ que contenga
    al menos un archivo .sub reconocible. No importa si su nombre sigue la
    convención "*_calibrated_*" o no: aquí se listan por igual, ya que son
    solo referencias de solo lectura para copiar.
    """
    project_dir = Path(project_dir)
    folders: list[ScenarioFolder] = []
    if not project_dir.is_dir():
        return folders
    for candidate in sorted(project_dir.iterdir()):
        if not candidate.is_dir():
            continue
        txtinout_dir = candidate / "TxtInOut"
        if not txtinout_dir.is_dir():
            continue
        if any(_SUB_FILENAME.match(p.name) for p in txtinout_dir.iterdir()):
            folders.append(ScenarioFolder(candidate.name, candidate, txtinout_dir))
    return folders
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/swat_io/test_discovery.py -v`
Expected: PASS (6 tests: 3 existing + 3 new)

- [ ] **Step 5: Commit**

```bash
git add swat_io/discovery.py tests/swat_io/test_discovery.py
git commit -m "feat: discover scenario folders inside a project directory"
```

---

### Task 3: Re-point the draft CSV at an explicit TxtInOut, and split engine/configure.py

**Files:**
- Modify: `scenarios/draft.py` (`init_draft` signature)
- Modify: `engine/configure.py` (replace `configure_scenario`/`ConfigureResult` with `create_working_scenario` and `apply_draft_to_pnd`)
- Modify: `tests/scenarios/test_draft.py`
- Modify: `tests/engine/test_configure.py`

**Interfaces:**
- Consumes: `Project(project_dir: Path)` from Task 1; `summarize_project(txtinout_dir) -> pd.DataFrame` (`swat_io/summary.py`, unchanged); `write_wetland_params(path, values)` (`swat_io/pnd_parser.py`, unchanged).
- Produces:
  - `draft_csv_path(project_dir: Path, scenario_name: str) -> Path`
  - `init_draft(project_dir: Path, scenario_name: str, txtinout_dir: Path) -> Path`
  - `read_draft`, `update_draft_value`, `import_draft_csv` unchanged (already path-based).
  - `create_working_scenario(project_dir: Path, reference_dir: Path, scenario_name: str) -> Path` (returns the new scenario dir; raises `FileExistsError` if it already exists).
  - `apply_draft_to_pnd(txtinout_dir: Path, draft: pd.DataFrame) -> None`.
  - Used by Task 5 (`ui/project_window.py`, "Cargar") and Task 6 (`ui/wetlands_window.py`, "Guardar").

- [ ] **Step 1: Update `scenarios/draft.py`'s `init_draft` to take an explicit `txtinout_dir`**

Edit `scenarios/draft.py`:

```python
def draft_csv_path(project_dir: Path, scenario_name: str) -> Path:
    return Path(project_dir) / _DRAFT_DIRNAME / f"{scenario_name}.csv"


def init_draft(project_dir: Path, scenario_name: str, txtinout_dir: Path) -> Path:
    """Crea el borrador de un escenario, sembrado con los valores actuales
    de txtinout_dir (la copia de trabajo recién creada, no la referencia)."""
    summary = summarize_project(txtinout_dir)
    draft = summary[list(_SUMMARY_TO_FIELD.keys())].rename(columns=_SUMMARY_TO_FIELD)
    path = draft_csv_path(project_dir, scenario_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    draft.to_csv(path)
    return path
```

Remove the now-unused `from .models import Project` import at the top of the file if nothing else in it references `Project`.

- [ ] **Step 2: Update `tests/scenarios/test_draft.py` for the new signature**

Replace the `_make_project` helper and every `init_draft(project, "...")` call:

```python
from pathlib import Path

import pandas as pd
import pytest

from scenarios.draft import draft_csv_path, import_draft_csv, init_draft, read_draft, update_draft_value
from tests.helpers import make_synthetic_txtinout

_LAYOUT = {
    "fields": [
        {"id": "wet_fr", "range": [0.0, 1.0]},
        {"id": "wet_nsa", "range": [0.0, None]},
        {"id": "wet_nvol", "range": [0.0, None]},
        {"id": "wet_mxsa", "range": [0.0, None]},
        {"id": "wet_mxvol", "range": [0.0, None]},
        {"id": "wet_vol", "range": [0.0, None]},
        {"id": "wet_k", "range": [0.0, None]},
    ]
}


def _make_project_dir(tmp_path: Path) -> tuple[Path, Path]:
    txtinout_dir = make_synthetic_txtinout(
        tmp_path / "workspace" / "Buffalo" / "Buffalo_WET_MS_annual",
        {
            1: {"WET_FR": 0.2, "WET_NSA": 10.0},
            2: {"WET_FR": 0.0, "WET_NSA": 0.0},
        },
    )
    project_dir = tmp_path / "workspace" / "Buffalo"
    return project_dir, txtinout_dir


def test_init_draft_seeds_from_txtinout_dir(tmp_path: Path) -> None:
    project_dir, txtinout_dir = _make_project_dir(tmp_path)

    path = init_draft(project_dir, "Buffalo_WET_MS_annual", txtinout_dir)

    assert path == draft_csv_path(project_dir, "Buffalo_WET_MS_annual")
    draft = read_draft(path)
    assert list(draft.index) == [1, 2]
    assert draft.loc[1, "wet_fr"] == 0.2
    assert draft.loc[2, "wet_fr"] == 0.0


def test_update_draft_value_writes_valid_value(tmp_path: Path) -> None:
    project_dir, txtinout_dir = _make_project_dir(tmp_path)
    path = init_draft(project_dir, "Buffalo_WET_MS_annual", txtinout_dir)

    draft = update_draft_value(path, 1, "wet_fr", 0.75, _LAYOUT)

    assert draft.loc[1, "wet_fr"] == 0.75
    assert read_draft(path).loc[1, "wet_fr"] == 0.75


def test_update_draft_value_rejects_out_of_range_and_writes_nothing(tmp_path: Path) -> None:
    project_dir, txtinout_dir = _make_project_dir(tmp_path)
    path = init_draft(project_dir, "Buffalo_WET_MS_annual", txtinout_dir)

    with pytest.raises(ValueError):
        update_draft_value(path, 1, "wet_fr", 1.5, _LAYOUT)

    assert read_draft(path).loc[1, "wet_fr"] == 0.2


def test_update_draft_value_rejects_unknown_subbasin(tmp_path: Path) -> None:
    project_dir, txtinout_dir = _make_project_dir(tmp_path)
    path = init_draft(project_dir, "Buffalo_WET_MS_annual", txtinout_dir)

    with pytest.raises(KeyError):
        update_draft_value(path, 999, "wet_fr", 0.5, _LAYOUT)


def test_import_draft_csv_applies_all_valid_rows(tmp_path: Path) -> None:
    project_dir, txtinout_dir = _make_project_dir(tmp_path)
    path = init_draft(project_dir, "Buffalo_WET_MS_annual", txtinout_dir)

    import_path = tmp_path / "import.csv"
    pd.DataFrame(
        [
            {"subbasin_id": 1, "wet_fr": 0.5, "wet_nsa": 15.0, "wet_nvol": 0.0,
             "wet_mxsa": 0.0, "wet_mxvol": 0.0, "wet_vol": 0.0, "wet_k": 0.0},
            {"subbasin_id": 2, "wet_fr": 0.3, "wet_nsa": 5.0, "wet_nvol": 0.0,
             "wet_mxsa": 0.0, "wet_mxvol": 0.0, "wet_vol": 0.0, "wet_k": 0.0},
        ]
    ).to_csv(import_path, index=False)

    draft = import_draft_csv(path, import_path, _LAYOUT)

    assert draft.loc[1, "wet_fr"] == 0.5
    assert draft.loc[2, "wet_fr"] == 0.3
    assert read_draft(path).loc[1, "wet_nsa"] == 15.0


def test_import_draft_csv_rejects_missing_column_and_applies_nothing(tmp_path: Path) -> None:
    project_dir, txtinout_dir = _make_project_dir(tmp_path)
    path = init_draft(project_dir, "Buffalo_WET_MS_annual", txtinout_dir)

    import_path = tmp_path / "import.csv"
    pd.DataFrame([{"subbasin_id": 1, "wet_fr": 0.5}]).to_csv(import_path, index=False)

    with pytest.raises(ValueError):
        import_draft_csv(path, import_path, _LAYOUT)

    assert read_draft(path).loc[1, "wet_fr"] == 0.2


def test_import_draft_csv_rejects_out_of_range_value_and_applies_nothing(tmp_path: Path) -> None:
    project_dir, txtinout_dir = _make_project_dir(tmp_path)
    path = init_draft(project_dir, "Buffalo_WET_MS_annual", txtinout_dir)

    import_path = tmp_path / "import.csv"
    pd.DataFrame(
        [
            {"subbasin_id": 1, "wet_fr": 5.0, "wet_nsa": 15.0, "wet_nvol": 0.0,
             "wet_mxsa": 0.0, "wet_mxvol": 0.0, "wet_vol": 0.0, "wet_k": 0.0},
        ]
    ).to_csv(import_path, index=False)

    with pytest.raises(ValueError):
        import_draft_csv(path, import_path, _LAYOUT)

    assert read_draft(path).loc[1, "wet_fr"] == 0.2
```

- [ ] **Step 3: Run the draft tests to verify they fail, then pass**

Run: `pytest tests/scenarios/test_draft.py -v`
Expected first: FAIL (`init_draft() missing 1 required positional argument: 'txtinout_dir'`)
After Step 1's edit: PASS (7 tests)

- [ ] **Step 4: Replace `engine/configure.py`**

```python
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from swat_io.pnd_parser import write_wetland_params


def create_working_scenario(project_dir: Path, reference_dir: Path, scenario_name: str) -> Path:
    """Copia toda la carpeta de referencia (TablesIn/TablesOut/TxtInOut/...)
    a project_dir/scenario_name. La carpeta de referencia nunca se modifica.

    Es el paso 1 de la secuencia obligatoria de CLAUDE.md, disparado por el
    botón "Cargar" (ver ui/project_window.py).
    """
    scenario_dir = Path(project_dir) / scenario_name
    if scenario_dir.exists():
        raise FileExistsError(f"Ya existe una carpeta de escenario para {scenario_name!r}: {scenario_dir}")
    shutil.copytree(Path(reference_dir), scenario_dir)
    return scenario_dir


def apply_draft_to_pnd(txtinout_dir: Path, draft: pd.DataFrame) -> None:
    """Escribe cada fila del borrador en el .pnd real de su subcuenca,
    dentro de la copia de trabajo del escenario (nunca en la referencia).

    Es lo que ejecuta el botón "Guardar" de la ventana Wetlands.
    """
    txtinout_dir = Path(txtinout_dir)
    field_ids = list(draft.columns)
    for subbasin_id, row in draft.iterrows():
        pnd_file = txtinout_dir / f"{int(subbasin_id):05d}0000.pnd"
        write_wetland_params(pnd_file, {field_id: float(row[field_id]) for field_id in field_ids})
```

- [ ] **Step 5: Replace `tests/engine/test_configure.py`**

```python
from pathlib import Path

import pytest

from engine.configure import apply_draft_to_pnd, create_working_scenario
from scenarios.draft import init_draft, read_draft, update_draft_value
from swat_io.pnd_parser import parse_pnd_file
from tests.helpers import make_synthetic_txtinout

_LAYOUT = {"fields": [{"id": "wet_fr", "range": [0.0, 1.0]}]}


def test_create_working_scenario_copies_whole_reference_folder(tmp_path: Path) -> None:
    reference_dir = tmp_path / "Buffalo_calibrated_annual"
    make_synthetic_txtinout(reference_dir, {1: {"WET_FR": 0.2}})
    (reference_dir / "TablesIn").mkdir()
    (reference_dir / "TablesOut").mkdir()
    project_dir = tmp_path / "workspace" / "Buffalo"
    project_dir.mkdir(parents=True)

    scenario_dir = create_working_scenario(project_dir, reference_dir, "Buffalo_WET_MS_annual")

    assert scenario_dir == project_dir / "Buffalo_WET_MS_annual"
    assert (scenario_dir / "TxtInOut" / "000010000.pnd").exists()
    assert (scenario_dir / "TablesIn").is_dir()
    assert (scenario_dir / "TablesOut").is_dir()
    # reference untouched
    reference_pnd = parse_pnd_file(reference_dir / "TxtInOut" / "000010000.pnd", subbasin_id=1)
    assert reference_pnd.wet_fr == 0.2


def test_create_working_scenario_refuses_to_overwrite_existing(tmp_path: Path) -> None:
    reference_dir = tmp_path / "Buffalo_calibrated_annual"
    make_synthetic_txtinout(reference_dir, {1: {"WET_FR": 0.2}})
    project_dir = tmp_path / "workspace" / "Buffalo"
    project_dir.mkdir(parents=True)
    create_working_scenario(project_dir, reference_dir, "Buffalo_WET_MS_annual")

    with pytest.raises(FileExistsError):
        create_working_scenario(project_dir, reference_dir, "Buffalo_WET_MS_annual")


def test_apply_draft_to_pnd_writes_edited_values_only_to_working_copy(tmp_path: Path) -> None:
    reference_dir = tmp_path / "Buffalo_calibrated_annual"
    make_synthetic_txtinout(reference_dir, {1: {"WET_FR": 0.2}, 2: {"WET_FR": 0.0}})
    project_dir = tmp_path / "workspace" / "Buffalo"
    project_dir.mkdir(parents=True)
    scenario_dir = create_working_scenario(project_dir, reference_dir, "Buffalo_WET_MS_annual")
    txtinout_dir = scenario_dir / "TxtInOut"
    draft_path = init_draft(project_dir, "Buffalo_WET_MS_annual", txtinout_dir)
    update_draft_value(draft_path, 1, "wet_fr", 0.9, _LAYOUT)
    draft = read_draft(draft_path)

    apply_draft_to_pnd(txtinout_dir, draft)

    updated = parse_pnd_file(txtinout_dir / "000010000.pnd", subbasin_id=1)
    assert updated.wet_fr == 0.9
    unchanged = parse_pnd_file(txtinout_dir / "000020000.pnd", subbasin_id=2)
    assert unchanged.wet_fr == 0.0
    # reference still untouched
    reference_pnd = parse_pnd_file(reference_dir / "TxtInOut" / "000010000.pnd", subbasin_id=1)
    assert reference_pnd.wet_fr == 0.2
```

- [ ] **Step 6: Run both test files to verify everything passes**

Run: `pytest tests/scenarios/test_draft.py tests/engine/test_configure.py -v`
Expected: PASS (7 + 3 tests)

- [ ] **Step 7: Commit**

```bash
git add scenarios/draft.py engine/configure.py tests/scenarios/test_draft.py tests/engine/test_configure.py
git commit -m "refactor: split engine/configure.py into create_working_scenario + apply_draft_to_pnd"
```

---

### Task 4: Rewrite the initial window — single "Abrir proyecto" button

**Files:**
- Modify: `ui/initial_window.py`
- Modify: `tests/ui/test_initial_window.py`
- Modify: `resources/strings/es.json` (add `project.open`, remove `project.open_or_create`, `project.action.create`, `project.action.open`)
- Modify: `tests/resources/test_strings.py` (update `_REQUIRED_NEW_KEYS`)

**Interfaces:**
- Consumes: `Project(project_dir: Path)` from Task 1.
- Produces: `InitialWindowFrame(master, config, on_project_selected)` unchanged in shape, calls `on_project_selected(Project(project_dir=...))`.

- [ ] **Step 1: Update `resources/strings/es.json`**

Remove the lines for `"project.open_or_create"`, `"project.action.create"`, `"project.action.open"`, `"watershed.select"`, `"watershed.select_placeholder"`. Add in their place:

```json
  "project.open": "Abrir proyecto",
```

(Keep `"project.no_selection"` and `"project.no_scenario"` as-is; `"project.no_scenario"`'s wording is updated in Task 5.)

- [ ] **Step 2: Update `tests/resources/test_strings.py`**

Replace the `_REQUIRED_NEW_KEYS` list:

```python
_REQUIRED_NEW_KEYS = [
    "config.target_executable_name",
    "config.error.invalid_directory",
    "project.open",
    "project.no_selection",
    "project.no_scenario",
    "project.load",
    "scenario.abbreviation",
    "scenario.timestep",
    "scenario.error.duplicate_name",
    "wetland.count",
    "wetland.import_csv",
    "wetland.import_error",
    "wetland.import_success",
    "action.parametrizacion",
    "action.save",
    "menu.wetlands",
]
```

(`project.load`, `action.parametrizacion`, `action.save`, `menu.wetlands` are added in Task 5/6 — this step only removes `project.open_or_create`/`action.configure_scenario`/`project.action.*`; leave the four new-in-later-tasks keys as a forward reference since this file is only re-run at the end of Task 6. Run the suite after Task 6, not now.)

- [ ] **Step 3: Rewrite `tests/ui/test_initial_window.py`**

```python
from pathlib import Path

from config.settings import ConfigManager
from ui.initial_window import InitialWindowFrame


def _make_config(tmp_path: Path) -> ConfigManager:
    resources_dir = Path(__file__).resolve().parents[2] / "resources"
    config = ConfigManager(resources_dir=resources_dir, config_file=tmp_path / "config.json")
    config.load_all()
    config.paths.workspace_root = tmp_path / "workspace"
    (tmp_path / "workspace").mkdir()
    return config


def test_initial_window_shows_no_selection_placeholder(hidden_root, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    frame = InitialWindowFrame(hidden_root, config, on_project_selected=lambda project: None)

    assert frame.path_entry.get() == config.text("project.no_selection")


def test_initial_window_open_project_invokes_callback(hidden_root, tmp_path: Path, monkeypatch) -> None:
    config = _make_config(tmp_path)
    project_folder = tmp_path / "03-Models" / "Buffalo"
    project_folder.mkdir(parents=True)
    selected = []

    monkeypatch.setattr("ui.initial_window.filedialog.askdirectory", lambda **kwargs: str(project_folder))

    frame = InitialWindowFrame(hidden_root, config, on_project_selected=lambda project: selected.append(project))
    frame._open_project()

    assert len(selected) == 1
    assert selected[0].project_dir == project_folder
    assert frame.path_entry.get() == str(project_folder)


def test_initial_window_open_project_cancelled_does_nothing(hidden_root, tmp_path: Path, monkeypatch) -> None:
    config = _make_config(tmp_path)
    selected = []

    monkeypatch.setattr("ui.initial_window.filedialog.askdirectory", lambda **kwargs: "")

    frame = InitialWindowFrame(hidden_root, config, on_project_selected=lambda project: selected.append(project))
    frame._open_project()

    assert selected == []
    assert frame.path_entry.get() == config.text("project.no_selection")
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/ui/test_initial_window.py -v`
Expected: FAIL (`AttributeError: 'InitialWindowFrame' object has no attribute '_open_project'`)

- [ ] **Step 5: Rewrite `ui/initial_window.py`**

```python
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog
from typing import Callable

import customtkinter as ctk

from config.settings import ConfigManager
from scenarios.models import Project


class InitialWindowFrame(ctk.CTkFrame):
    def __init__(
        self, master, config: ConfigManager, on_project_selected: Callable[[Project], None]
    ) -> None:
        super().__init__(master)
        self.config = config
        self.on_project_selected = on_project_selected

        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(expand=True)

        ctk.CTkLabel(container, text=config.text("app.title")).pack(pady=(0, 24))
        ctk.CTkButton(
            container, text=config.text("project.open"), command=self._open_project
        ).pack()

        self.path_entry = ctk.CTkEntry(container, width=320)
        self.path_entry.pack(pady=(20, 0))
        self._set_path_display(config.text("project.no_selection"))

    def _set_path_display(self, text: str) -> None:
        self.path_entry.configure(state="normal")
        self.path_entry.delete(0, "end")
        self.path_entry.insert(0, text)
        self.path_entry.configure(state="disabled")

    def _open_project(self) -> None:
        initial_dir = (
            str(self.config.paths.workspace_root) if self.config.paths.workspace_root else None
        )
        directory = filedialog.askdirectory(parent=self, initialdir=initial_dir)
        if not directory:
            return
        project = Project(project_dir=Path(directory))
        self._set_path_display(str(project.project_dir))
        self.on_project_selected(project)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/ui/test_initial_window.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git add ui/initial_window.py tests/ui/test_initial_window.py resources/strings/es.json tests/resources/test_strings.py
git commit -m "feat: replace create/open-project flow with a single Abrir proyecto folder picker"
```

---

### Task 5: Rewrite the project window — reference panel, Cargar, Parametrización menu

**Files:**
- Modify: `ui/project_window.py` (full rewrite)
- Modify: `tests/ui/test_project_window.py` (full rewrite)
- Modify: `resources/strings/es.json` (add `project.load`, `project.select_reference_hint`, `action.parametrizacion`, `menu.wetlands`; update `project.no_scenario` wording; remove `action.configure_scenario`)

**Interfaces:**
- Consumes: `Project(project_dir: Path)` (Task 1), `discover_scenario_folders`/`ScenarioFolder` (Task 2), `create_working_scenario`/`init_draft` (Task 3), `WETLAND_ABBREVIATIONS`/`build_scenario_name` (`scenarios/models.py`, unchanged), `ask_choice`/`ask_text` (`ui/dialogs.py`, unchanged).
- Produces: `ProjectWindowFrame(master, config, project)` with attributes `radio_buttons`, `load_button`, `param_button`, `status_label`, `scenario_label`, `working_scenario_name`, `working_txtinout_dir`, and methods `_on_reference_checked`, `_on_cargar`, `_open_wetlands_window` — the last one is what Task 6's `WetlandsWindow` gets constructed from.

- [ ] **Step 1: Update `resources/strings/es.json`**

Remove `"action.configure_scenario"`. Update `"project.no_scenario"` and add new keys:

```json
  "project.no_scenario": "Sin escenario — marca una referencia y presiona Cargar",
  "project.load": "Cargar",
  "project.select_reference_hint": "Selecciona un escenario de referencia y presiona Cargar para comenzar.",
  "action.parametrizacion": "Parametrización",
  "menu.wetlands": "Wetlands",
```

- [ ] **Step 2: Rewrite `tests/ui/test_project_window.py`**

```python
from pathlib import Path

from config.settings import ConfigManager
from scenarios.draft import draft_csv_path, read_draft
from scenarios.models import Project
from tests.helpers import make_synthetic_txtinout
from ui.project_window import ProjectWindowFrame


def _make_project_and_config(tmp_path: Path) -> tuple[Project, ConfigManager]:
    resources_dir = Path(__file__).resolve().parents[2] / "resources"
    config = ConfigManager(resources_dir=resources_dir, config_file=tmp_path / "config.json")
    config.load_all()

    project_dir = tmp_path / "Buffalo"
    make_synthetic_txtinout(project_dir / "Buffalo_calibrated_annual", {1: {"WET_FR": 0.2}, 2: {"WET_FR": 0.0}})
    make_synthetic_txtinout(project_dir / "Buffalo_GI_annual", {1: {"WET_FR": 0.1}, 2: {"WET_FR": 0.0}})
    project = Project(project_dir=project_dir)
    return project, config


def test_project_window_lists_reference_scenarios_and_disables_load(hidden_root, tmp_path: Path) -> None:
    project, config = _make_project_and_config(tmp_path)

    frame = ProjectWindowFrame(hidden_root, config, project)

    assert len(frame.radio_buttons) == 2
    assert frame.load_button.cget("state") == "disabled"
    assert frame.param_button.cget("state") == "disabled"


def test_project_window_checking_a_reference_enables_load(hidden_root, tmp_path: Path) -> None:
    project, config = _make_project_and_config(tmp_path)
    frame = ProjectWindowFrame(hidden_root, config, project)

    frame.reference_var.set("Buffalo_calibrated_annual")
    frame._on_reference_checked()

    assert frame.load_button.cget("state") == "normal"


def test_project_window_cargar_copies_reference_and_seeds_draft(hidden_root, tmp_path: Path, monkeypatch) -> None:
    project, config = _make_project_and_config(tmp_path)
    frame = ProjectWindowFrame(hidden_root, config, project)
    frame.reference_var.set("Buffalo_calibrated_annual")
    frame._on_reference_checked()

    monkeypatch.setattr("ui.project_window.ask_choice", lambda *a, **k: "WET_MS")
    monkeypatch.setattr("ui.project_window.ask_text", lambda *a, **k: "annual")

    frame._on_cargar()

    scenario_name = "Buffalo_WET_MS_annual"
    assert frame.working_scenario_name == scenario_name
    assert (project.project_dir / scenario_name / "TxtInOut" / "000010000.pnd").exists()
    draft = read_draft(draft_csv_path(project.project_dir, scenario_name))
    assert draft.loc[1, "wet_fr"] == 0.2
    # reference untouched
    from swat_io.pnd_parser import parse_pnd_file
    reference_pnd = parse_pnd_file(
        project.project_dir / "Buffalo_calibrated_annual" / "TxtInOut" / "000010000.pnd", subbasin_id=1
    )
    assert reference_pnd.wet_fr == 0.2


def test_project_window_cargar_locks_reference_panel_and_enables_parametrizacion(
    hidden_root, tmp_path: Path, monkeypatch
) -> None:
    project, config = _make_project_and_config(tmp_path)
    frame = ProjectWindowFrame(hidden_root, config, project)
    frame.reference_var.set("Buffalo_calibrated_annual")
    frame._on_reference_checked()
    monkeypatch.setattr("ui.project_window.ask_choice", lambda *a, **k: "WET_MS")
    monkeypatch.setattr("ui.project_window.ask_text", lambda *a, **k: "annual")

    frame._on_cargar()

    assert frame.load_button.cget("state") == "disabled"
    assert all(radio.cget("state") == "disabled" for radio in frame.radio_buttons)
    assert frame.param_button.cget("state") == "normal"
    assert frame.scenario_label.cget("text") == "Buffalo_WET_MS_annual"


def test_project_window_cargar_rejects_duplicate_scenario_name(hidden_root, tmp_path: Path, monkeypatch) -> None:
    project, config = _make_project_and_config(tmp_path)
    (project.project_dir / "Buffalo_WET_MS_annual").mkdir()
    frame = ProjectWindowFrame(hidden_root, config, project)
    frame.reference_var.set("Buffalo_calibrated_annual")
    frame._on_reference_checked()
    monkeypatch.setattr("ui.project_window.ask_choice", lambda *a, **k: "WET_MS")
    monkeypatch.setattr("ui.project_window.ask_text", lambda *a, **k: "annual")

    frame._on_cargar()

    assert frame.working_scenario_name is None
    assert config.text("scenario.error.duplicate_name") in frame.status_label.cget("text")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/ui/test_project_window.py -v`
Expected: FAIL (old `ProjectWindowFrame` has none of `radio_buttons`/`load_button`/`reference_var`/etc.)

- [ ] **Step 4: Rewrite `ui/project_window.py`**

```python
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from config.settings import ConfigManager
from engine.configure import create_working_scenario
from scenarios.draft import draft_csv_path, init_draft
from scenarios.models import WETLAND_ABBREVIATIONS, Project, build_scenario_name
from swat_io.discovery import discover_scenario_folders
from ui.dialogs import ask_choice, ask_text
from ui.wetlands_window import WetlandsWindow


class ProjectWindowFrame(ctk.CTkFrame):
    def __init__(self, master, config: ConfigManager, project: Project) -> None:
        super().__init__(master)
        self.config = config
        self.project = project
        self.working_scenario_name: str | None = None
        self.working_txtinout_dir = None

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=12)
        ctk.CTkLabel(header, text=project.project_dir.name).pack(anchor="w")
        self.scenario_label = ctk.CTkLabel(header, text=config.text("project.no_scenario"))
        self.scenario_label.pack(anchor="w")

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=12)
        self.param_button = ctk.CTkButton(
            toolbar, text=config.text("action.parametrizacion"),
            command=self._show_parametrizacion_menu, state="disabled",
        )
        self.param_button.pack(side="left")

        self.status_label = ctk.CTkLabel(self, text="")
        self.status_label.pack(fill="x", padx=12, pady=(8, 0))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=12)

        self.main_area = ctk.CTkFrame(body)
        self.main_area.pack(side="left", fill="both", expand=True, padx=(0, 8))
        ctk.CTkLabel(self.main_area, text=config.text("project.select_reference_hint")).pack(
            padx=16, pady=16, anchor="nw"
        )

        self.reference_panel = ctk.CTkFrame(body, width=240)
        self.reference_panel.pack(side="right", fill="y")

        self._build_reference_panel()

    def _build_reference_panel(self) -> None:
        self.scenario_folders = discover_scenario_folders(self.project.project_dir)
        self.reference_var = ctk.StringVar(value="")
        self.radio_buttons: list[ctk.CTkRadioButton] = []
        for folder in self.scenario_folders:
            radio = ctk.CTkRadioButton(
                self.reference_panel, text=folder.name, variable=self.reference_var,
                value=folder.name, command=self._on_reference_checked,
            )
            radio.pack(anchor="w", padx=8, pady=4)
            self.radio_buttons.append(radio)
        self.load_button = ctk.CTkButton(
            self.reference_panel, text=self.config.text("project.load"),
            command=self._on_cargar, state="disabled",
        )
        self.load_button.pack(padx=8, pady=(12, 8))

    def _on_reference_checked(self) -> None:
        self.load_button.configure(state="normal")

    def _on_cargar(self) -> None:
        reference_name = self.reference_var.get()
        reference = next(f for f in self.scenario_folders if f.name == reference_name)

        abbreviation = ask_choice(
            self, self.config.text("scenario.abbreviation"), list(WETLAND_ABBREVIATIONS),
            self.config.text("action.confirm"), self.config.text("action.cancel"),
        )
        if abbreviation is None:
            return
        timestep = ask_text(
            self, self.config.text("scenario.timestep"),
            self.config.text("action.confirm"), self.config.text("action.cancel"), default="annual",
        )
        if not timestep:
            return

        watershed = self.project.project_dir.name
        try:
            name = build_scenario_name(watershed, abbreviation, timestep)
        except ValueError as exc:
            self.status_label.configure(text=str(exc))
            return

        already_exists = (self.project.project_dir / name).exists() or draft_csv_path(
            self.project.project_dir, name
        ).exists()
        if already_exists:
            self.status_label.configure(text=self.config.text("scenario.error.duplicate_name"))
            return

        try:
            scenario_dir = create_working_scenario(self.project.project_dir, reference.dir, name)
        except OSError as exc:
            self.status_label.configure(text=str(exc))
            return

        txtinout_dir = scenario_dir / "TxtInOut"
        init_draft(self.project.project_dir, name, txtinout_dir)

        self.working_scenario_name = name
        self.working_txtinout_dir = txtinout_dir
        self.scenario_label.configure(text=name)
        self.status_label.configure(text="")
        self._lock_reference_panel()
        self.param_button.configure(state="normal")

    def _lock_reference_panel(self) -> None:
        for radio in self.radio_buttons:
            radio.configure(state="disabled")
        self.load_button.configure(state="disabled")

    def _show_parametrizacion_menu(self) -> None:
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label=self.config.text("menu.wetlands"), command=self._open_wetlands_window)
        x = self.param_button.winfo_rootx()
        y = self.param_button.winfo_rooty() + self.param_button.winfo_height()
        menu.tk_popup(x, y)

    def _open_wetlands_window(self) -> None:
        WetlandsWindow(
            self, self.config, self.project.project_dir,
            self.working_scenario_name, self.working_txtinout_dir,
        )
```

- [ ] **Step 5: Run tests — expect an import error for `ui.wetlands_window` (Task 6 hasn't created it yet)**

Run: `pytest tests/ui/test_project_window.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ui.wetlands_window'` — this is expected at this point in the plan; Task 6 creates that module. Do not attempt to fix it here.

- [ ] **Step 6: Commit** (test suite for this task finishes going green at the end of Task 6 — commit the code now so history stays small and reviewable)

```bash
git add ui/project_window.py tests/ui/test_project_window.py resources/strings/es.json
git commit -m "feat: add reference-scenario panel, Cargar flow, and Parametrizacion menu to project window"
```

---

### Task 6: Wetlands window (Toplevel) with Cargar CSV / Guardar / Cancelar

**Files:**
- Create: `ui/wetlands_window.py`
- Delete: `ui/parametrizacion_view.py`
- Create: `tests/ui/test_wetlands_window.py`
- Delete: `tests/ui/test_parametrizacion_view.py`
- Modify: `resources/strings/es.json` (add `action.save`; change `wetland.import_csv` label to "Cargar CSV")
- Modify: `tests/resources/test_strings.py` (finalize `_REQUIRED_NEW_KEYS`, already listed in Task 4 Step 2)

**Interfaces:**
- Consumes: `draft_csv_path`, `read_draft`, `update_draft_value`, `import_draft_csv`, `init_draft` (`scenarios/draft.py`, Task 3), `apply_draft_to_pnd` (`engine/configure.py`, Task 3), `build_wetland_form` (`ui/form_builder.py`, unchanged).
- Produces: `WetlandsWindow(master, config, project_dir: Path, scenario_name: str, txtinout_dir: Path)` — constructed by `ProjectWindowFrame._open_wetlands_window` (Task 5).

- [ ] **Step 1: Update `resources/strings/es.json`**

Change:
```json
  "wetland.import_csv": "Cargar CSV",
```
Add:
```json
  "action.save": "Guardar",
```

- [ ] **Step 2: Write `tests/ui/test_wetlands_window.py`**

```python
from pathlib import Path

from config.settings import ConfigManager
from engine.configure import create_working_scenario
from scenarios.draft import draft_csv_path, init_draft, read_draft
from swat_io.pnd_parser import parse_pnd_file
from tests.helpers import make_synthetic_txtinout
from ui.wetlands_window import WetlandsWindow


def _make_scenario(tmp_path: Path) -> tuple[ConfigManager, Path, str, Path]:
    resources_dir = Path(__file__).resolve().parents[2] / "resources"
    config = ConfigManager(resources_dir=resources_dir, config_file=tmp_path / "config.json")
    config.load_all()

    project_dir = tmp_path / "Buffalo"
    reference_dir = make_synthetic_txtinout(
        project_dir / "Buffalo_calibrated_annual", {1: {"WET_FR": 0.2}, 2: {"WET_FR": 0.0}}
    ).parent
    scenario_dir = create_working_scenario(project_dir, reference_dir, "Buffalo_WET_MS_annual")
    txtinout_dir = scenario_dir / "TxtInOut"
    init_draft(project_dir, "Buffalo_WET_MS_annual", txtinout_dir)
    return config, project_dir, "Buffalo_WET_MS_annual", txtinout_dir


def test_wetlands_window_shows_draft_and_count(hidden_root, tmp_path: Path) -> None:
    config, project_dir, scenario_name, txtinout_dir = _make_scenario(tmp_path)

    window = WetlandsWindow(hidden_root, config, project_dir, scenario_name, txtinout_dir)

    assert "1" in window.count_label.cget("text")
    assert "2" in window.count_label.cget("text")
    window.destroy()


def test_wetlands_window_field_commit_persists_to_draft_csv_only(hidden_root, tmp_path: Path) -> None:
    config, project_dir, scenario_name, txtinout_dir = _make_scenario(tmp_path)
    window = WetlandsWindow(hidden_root, config, project_dir, scenario_name, txtinout_dir)
    window._select_row(1)

    window._on_field_commit("wet_fr", 0.8)

    assert read_draft(window.draft_path).loc[1, "wet_fr"] == 0.8
    # not yet applied to the real .pnd
    pnd = parse_pnd_file(txtinout_dir / "000010000.pnd", subbasin_id=1)
    assert pnd.wet_fr == 0.2
    window.destroy()


def test_wetlands_window_guardar_applies_draft_to_real_pnd(hidden_root, tmp_path: Path) -> None:
    config, project_dir, scenario_name, txtinout_dir = _make_scenario(tmp_path)
    window = WetlandsWindow(hidden_root, config, project_dir, scenario_name, txtinout_dir)
    window._select_row(1)
    window._on_field_commit("wet_fr", 0.8)

    window._on_guardar()

    pnd = parse_pnd_file(txtinout_dir / "000010000.pnd", subbasin_id=1)
    assert pnd.wet_fr == 0.8
    window.destroy()


def test_wetlands_window_cancelar_closes_without_touching_pnd(hidden_root, tmp_path: Path) -> None:
    config, project_dir, scenario_name, txtinout_dir = _make_scenario(tmp_path)
    window = WetlandsWindow(hidden_root, config, project_dir, scenario_name, txtinout_dir)
    window._select_row(1)
    window._on_field_commit("wet_fr", 0.8)

    window._on_cancelar()

    pnd = parse_pnd_file(txtinout_dir / "000010000.pnd", subbasin_id=1)
    assert pnd.wet_fr == 0.2
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/ui/test_wetlands_window.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ui.wetlands_window'`

- [ ] **Step 4: Create `ui/wetlands_window.py`**

```python
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from config.settings import ConfigManager
from engine.configure import apply_draft_to_pnd
from scenarios.draft import draft_csv_path, import_draft_csv, init_draft, read_draft, update_draft_value
from ui.form_builder import build_wetland_form


class WetlandsWindow(ctk.CTkToplevel):
    def __init__(
        self, master, config: ConfigManager, project_dir: Path, scenario_name: str, txtinout_dir: Path
    ) -> None:
        super().__init__(master)
        self.title(config.text("wetland.form.title"))
        self.config = config
        self.project_dir = project_dir
        self.scenario_name = scenario_name
        self.txtinout_dir = txtinout_dir
        self.layout_def = config.load_layout("wetland_pond")

        self.draft_path = draft_csv_path(project_dir, scenario_name)
        if not self.draft_path.exists():
            init_draft(project_dir, scenario_name, txtinout_dir)
        self.draft = read_draft(self.draft_path)
        self.selected_id = self.draft.index[0]

        self._build_widgets()
        self._populate_list()
        self._select_row(self.selected_id)

    def _build_widgets(self) -> None:
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=8, pady=8)
        self.count_label = ctk.CTkLabel(top, text="")
        self.count_label.pack(side="left")
        ctk.CTkButton(
            top, text=self.config.text("wetland.import_csv"), command=self._on_import_csv
        ).pack(side="right")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=8, pady=8)

        self.list_frame = ctk.CTkScrollableFrame(body, width=280)
        self.list_frame.pack(side="left", fill="y", padx=(0, 8))

        self.form_frame = ctk.CTkFrame(body)
        self.form_frame.pack(side="left", fill="both", expand=True)

        self.error_label = ctk.CTkLabel(self, text="", text_color="#B3261E")
        self.error_label.pack(fill="x", padx=8)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=8, pady=(0, 8))
        ctk.CTkButton(actions, text=self.config.text("action.cancel"), command=self._on_cancelar).pack(
            side="right", padx=(8, 0)
        )
        ctk.CTkButton(actions, text=self.config.text("action.save"), command=self._on_guardar).pack(
            side="right"
        )

    def _populate_list(self) -> None:
        for child in self.list_frame.winfo_children():
            child.destroy()
        with_wetland = int((self.draft["wet_fr"] > 0).sum())
        total = len(self.draft)
        self.count_label.configure(
            text=self.config.text("wetland.count").format(with_wetland=with_wetland, total=total)
        )
        for subbasin_id, row in self.draft.iterrows():
            marker = "●" if row["wet_fr"] > 0 else "○"
            text = f"{marker} Sub {subbasin_id} — WET_FR {row['wet_fr']:.3f}"
            ctk.CTkButton(
                self.list_frame,
                text=text,
                fg_color="transparent",
                anchor="w",
                command=lambda sid=subbasin_id: self._select_row(sid),
            ).pack(fill="x", pady=2)

    def _select_row(self, subbasin_id: int) -> None:
        self.selected_id = subbasin_id
        for child in self.form_frame.winfo_children():
            child.destroy()
        row = self.draft.loc[subbasin_id]
        initial_values = {field["id"]: row[field["id"]] for field in self.layout_def["fields"]}
        build_wetland_form(
            self.form_frame, self.config, self.layout_def, initial_values,
            on_commit=self._on_field_commit, on_error=self._on_field_error,
        )

    def _on_field_commit(self, field_id: str, value: float) -> None:
        self.draft = update_draft_value(self.draft_path, self.selected_id, field_id, value, self.layout_def)
        self.error_label.configure(text="")
        self._populate_list()

    def _on_field_error(self, field_id: str, message: str) -> None:
        self.error_label.configure(text=f"{field_id}: {message}")

    def _on_import_csv(self) -> None:
        path = filedialog.askopenfilename(parent=self)
        if not path:
            return
        try:
            self.draft = import_draft_csv(self.draft_path, Path(path), self.layout_def)
        except ValueError as exc:
            self.error_label.configure(text=self.config.text("wetland.import_error").format(error=str(exc)))
            return
        self.error_label.configure(text=self.config.text("wetland.import_success"))
        self._populate_list()
        self._select_row(self.selected_id)

    def _on_guardar(self) -> None:
        apply_draft_to_pnd(self.txtinout_dir, self.draft)

    def _on_cancelar(self) -> None:
        self.destroy()
```

- [ ] **Step 5: Delete the old embedded view and its test**

```bash
rm ui/parametrizacion_view.py tests/ui/test_parametrizacion_view.py
```

- [ ] **Step 6: Run the new Wetlands tests, then the project-window tests from Task 5, then the full suite**

Run: `pytest tests/ui/test_wetlands_window.py -v`
Expected: PASS (4 tests)

Run: `pytest tests/ui/test_project_window.py -v`
Expected: PASS (5 tests — the `ModuleNotFoundError` from Task 5 Step 5 is now resolved)

Run: `pytest -v`
Expected: PASS, full suite green (no reference to `ui.parametrizacion_view`, `scenarios.project`, `configure_scenario`, or the old `Project` fields anywhere)

- [ ] **Step 7: Commit**

```bash
git add ui/wetlands_window.py tests/ui/test_wetlands_window.py resources/strings/es.json tests/resources/test_strings.py
git rm ui/parametrizacion_view.py tests/ui/test_parametrizacion_view.py
git commit -m "feat: add Wetlands Toplevel window with Cargar CSV / Guardar / Cancelar"
```

---

### Task 7: Manual smoke check

**Files:** none (verification only)

- [ ] **Step 1: Launch the app**

Run: `python main.py`
Expected: config dialog (if paths incomplete) or initial window opens without crashing.

- [ ] **Step 2: Walk the golden path**

1. Click "Abrir proyecto", pick a folder containing at least one `{name}/TxtInOut/*.sub` subfolder (a synthetic one is fine for this check — real data isn't required to verify wiring).
2. Confirm the right panel lists the subfolder(s) and "Cargar" is disabled until one is checked.
3. Check one, confirm "Cargar" enables.
4. Click "Cargar", provide an abbreviation/timestep, confirm the panel locks and "Parametrización" enables.
5. Click "Parametrización" → "Wetlands", confirm the table window opens with the seeded values.
6. Edit a field, click "Guardar", confirm no error; click "Cancelar" on a second edit and confirm the window closes.

Expected: no unhandled exceptions at any step; report back if any step misbehaves rather than silently working around it.

- [ ] **Step 3: Report result**

No commit for this task — it's a verification checkpoint, not a code change.

---

## Self-review notes

- Spec coverage: sections 2 (ventana inicial), 3.1–3.3 (panel derecho, Cargar, toolbar), 4 (ventana Wetlands), 5 (arquitectura), 6 (errores: duplicado ya cubierto en Task 5's test; falla de copia surfaces via `OSError` catch in `_on_cargar`; falla de importación de CSV already covered by existing `import_draft_csv` all-or-nothing behavior, unchanged from before) are each implemented by a task above.
- `discover_base_models`/`BaseModelInfo` and the config-gate files are explicitly left untouched per the Global Constraints — confirmed no task modifies them.
- Type/signature consistency checked: `init_draft(project_dir, scenario_name, txtinout_dir)` used identically in Task 3, 5, 6; `create_working_scenario(project_dir, reference_dir, scenario_name) -> Path` used identically in Task 3 and 5; `apply_draft_to_pnd(txtinout_dir, draft)` used identically in Task 3 and 6.
