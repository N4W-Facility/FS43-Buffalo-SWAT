# Ventana inicial y Parametrización de humedales — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working end-to-end slice of the SWAT Wetlands desktop app: a path-configuration gate, the initial window (open/create project), the project window (toolbar), the Parametrización view (edit wetland params for one scenario, backed by a live CSV, with manual edit + CSV import), and the "Configurar escenario" action that materializes the scenario's working folder per CLAUDE.md's mandatory sequence.

**Architecture:** Bottom-up: (1) extend `swat_io/` with a `.pnd` writer, (2) add scenario/project domain logic in `scenarios/` and `engine/` (UI-agnostic, fully unit-tested), (3) add a handful of small localization keys, (4) build `ui/` widgets that consume only `ConfigManager` + the domain layer — no literals, no business logic in `ui/`.

**Tech Stack:** Python 3.13, CustomTkinter on Tkinter, pandas, PyYAML, pytest. Runs in the existing `swat` conda environment.

## Global Constraints

- Motor fijo SWAT2012 rev670; el `TxtInOut` base (`*_calibrated_*`) nunca se escribe — toda escritura ocurre sobre la copia de trabajo del escenario.
- Secuencia obligatoria antes de ejecutar (CLAUDE.md): copiar `TxtInOut` → aplicar cambios de humedal al `.pnd` de la copia → colocar el ejecutable renombrado. Este plan implementa hasta ahí; invocar `swat2012.exe` como subproceso queda fuera de alcance.
- Cada escenario se construye siempre desde el `TxtInOut` `*_calibrated_*` de su cuenca — nunca desde otro escenario.
- Convención de nombres de escenario: `{Watershed}_{ScenarioAbbreviation}_{timestep}`, con abreviaturas de humedal `WET_LS`, `WET_MS`, `WET_HS`.
- CustomTkinter sobre Tkinter, tema claro (`resources/theme/swat_light.json`), aplicado vía `customtkinter.set_default_color_theme`.
- Cero literales de texto/color/layout hardcodeados en `ui/`: todo texto vía `ConfigManager.text(key)`, todo campo de formulario vía `resources/layout/*.yaml`.
- Ninguna ruta sensible a la máquina (ejecutable SWAT, carpetas de modelos/trabajo, nombre del ejecutable destino) se hardcodea — todas viven en `AppPaths`, configurables desde la UI.
- Entorno: conda env `swat`. **No instalar paquetes nuevos sin confirmar con el usuario primero** — este plan requiere `pyyaml`, `customtkinter`, y `pytest` en ese entorno (pandas ya está confirmado presente); pregunta antes del Task 0 si faltan.
- Los tests que instancian widgets de CustomTkinter necesitan una sesión Windows con escritorio real (no headless). Se identifican explícitamente en cada task.

---

## Task 0: Test infrastructure

**Files:**
- Create: `conftest.py` (project root)
- Create: `tests/helpers.py`

**Interfaces:**
- Produces: `tests.helpers.make_synthetic_txtinout(root: Path, subbasins: dict[int, dict[str, float]]) -> Path` — builds a minimal synthetic `TxtInOut/` with one `.sub` + `.pnd` per subbasin id, using the real SWAT2012 `value | CODE : desc` line format. `subbasins[id]` is a dict of SWAT wetland codes (e.g. `"WET_FR"`) to override; codes not given default to `0.0`.

- [ ] **Step 1: Create the root conftest.py**

An empty `conftest.py` at the project root is required so pytest inserts the project root onto `sys.path` (there's no `pyproject.toml`/`src` layout here) — otherwise `import swat_io`, `import scenarios`, etc. fail when pytest collects files under `tests/`.

```python
# Empty on purpose: its presence makes pytest add the project root to
# sys.path so "import swat_io", "import scenarios", etc. resolve.
```

- [ ] **Step 2: Write tests/helpers.py**

```python
from __future__ import annotations

from pathlib import Path

_WETLAND_CODES = [
    "WET_FR", "WET_NSA", "WET_NVOL", "WET_MXSA", "WET_MXVOL", "WET_VOL",
    "WET_SED", "WET_NSED", "WET_K", "PSETLW1", "PSETLW2", "NSETLW1",
    "NSETLW2", "CHLAW", "SECCIW", "WET_NO3", "WET_SOLP", "WET_ORGN",
    "WET_ORGP", "WETEVCOEFF",
]


def write_synthetic_pnd(path: Path, wetland_values: dict[str, float]) -> None:
    lines = ["Wetland inputs:\n"]
    for code in _WETLAND_CODES:
        value = wetland_values.get(code, 0.0)
        lines.append(f"{value:16.3f}    | {code} : synthetic test value\n")
    path.write_text("".join(lines), encoding="utf-8")


def write_synthetic_sub(path: Path, area_km2: float = 10.0) -> None:
    path.write_text(f"{area_km2:16.3f}    | SUB_KM : synthetic test value\n", encoding="utf-8")


def make_synthetic_txtinout(root: Path, subbasins: dict[int, dict[str, float]]) -> Path:
    txtinout_dir = root / "TxtInOut"
    txtinout_dir.mkdir(parents=True, exist_ok=True)
    for subbasin_id, wetland_values in subbasins.items():
        write_synthetic_sub(txtinout_dir / f"{subbasin_id:05d}0000.sub")
        write_synthetic_pnd(txtinout_dir / f"{subbasin_id:05d}0000.pnd", wetland_values)
    return txtinout_dir
```

- [ ] **Step 3: Verify pytest can collect (no tests yet, just confirm no import errors)**

Run: `conda activate swat && pytest --collect-only -q`
Expected: `no tests ran` (exit code 5), no import errors.

- [ ] **Step 4: Commit**

```bash
git add conftest.py tests/helpers.py
git commit -m "test: add pytest root path fixture and synthetic TxtInOut helper"
```

---

## Task 1: `.pnd` writer — `write_value_code_file`

**Files:**
- Modify: `swat_io/text_format.py`
- Test: `tests/swat_io/test_text_format.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `swat_io.text_format.write_value_code_file(path: Path, updates: dict[str, str | float]) -> None`. Rewrites, in place, only the numeric value of lines whose `CODE` is a key in `updates`; every other line (including the rest of a matched line — separator, code, description) is byte-identical to the original. New values are formatted `%.3f` right-justified to the original field width (computed from the original line, so alignment style is preserved without assuming a fixed global width).

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from swat_io.text_format import parse_value_code_file, write_value_code_file


def test_write_value_code_file_updates_only_matching_codes(tmp_path: Path) -> None:
    path = tmp_path / "sample.pnd"
    path.write_text(
        "Wetland inputs:\n"
        "           0.000    | WET_FR : Fraction of subbasin area that drains into wetlands\n"
        "          42.400    | WET_NSA: Surface area of wetlands at normal water level [ha]\n",
        encoding="utf-8",
    )

    write_value_code_file(path, {"WET_FR": 0.4})

    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert lines[1] == "           0.400    | WET_FR : Fraction of subbasin area that drains into wetlands"
    assert lines[2] == "          42.400    | WET_NSA: Surface area of wetlands at normal water level [ha]"


def test_write_value_code_file_round_trips_through_parser(tmp_path: Path) -> None:
    path = tmp_path / "sample.pnd"
    path.write_text(
        "           0.000    | WET_FR : desc\n"
        "         106.000    | WET_MXSA: desc\n",
        encoding="utf-8",
    )

    write_value_code_file(path, {"WET_FR": 0.75, "WET_MXSA": 12.5})

    parsed = parse_value_code_file(path)
    assert float(parsed["WET_FR"]) == 0.75
    assert float(parsed["WET_MXSA"]) == 12.5


def test_write_value_code_file_ignores_unrelated_codes(tmp_path: Path) -> None:
    path = tmp_path / "sample.pnd"
    original = "           0.000    | WET_K : desc\n"
    path.write_text(original, encoding="utf-8")

    write_value_code_file(path, {"WET_FR": 1.0})

    assert path.read_text(encoding="utf-8") == original
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda activate swat && pytest tests/swat_io/test_text_format.py -v`
Expected: FAIL — `ImportError: cannot import name 'write_value_code_file'`

- [ ] **Step 3: Implement write_value_code_file**

Add to `swat_io/text_format.py`, below `parse_value_code_file`:

```python
def write_value_code_file(path: Path, updates: dict[str, float]) -> None:
    """Reescribe, sobre el mismo archivo, solo el valor numérico de las
    líneas cuyo CODIGO está en updates.

    El resto de cada línea (separador, código, descripción, salto de
    línea) queda exactamente igual. El nuevo valor se formatea con 3
    decimales, justificado a la derecha dentro del ancho de campo que ya
    tenía esa línea (no se asume un ancho fijo global).
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        match = _LINE_PATTERN.match(line)
        if match and match.group("code") in updates:
            width = match.end("value")
            new_value = updates[match.group("code")]
            formatted = f"{new_value:>{width}.3f}"
            line = formatted + line[match.end("value"):]
        new_lines.append(line)

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda activate swat && pytest tests/swat_io/test_text_format.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add swat_io/text_format.py tests/swat_io/test_text_format.py
git commit -m "feat: add write_value_code_file for in-place SWAT text file edits"
```

---

## Task 2: `.pnd` wetland writer — `write_wetland_params`

**Files:**
- Modify: `swat_io/pnd_parser.py`
- Test: `tests/swat_io/test_pnd_parser.py`

**Interfaces:**
- Consumes: `swat_io.text_format.write_value_code_file` (Task 1).
- Produces: `swat_io.pnd_parser.write_wetland_params(path: Path, values: dict[str, float]) -> None`. `values` uses the **form field ids** from `resources/layout/wetland_pond.yaml` (`wet_fr`, `wet_nsa`, `wet_nvol`, `wet_mxsa`, `wet_mxvol`, `wet_vol`, `wet_k`) — not raw SWAT codes.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from swat_io.pnd_parser import parse_pnd_file, write_wetland_params
from tests.helpers import write_synthetic_pnd


def test_write_wetland_params_updates_requested_fields(tmp_path: Path) -> None:
    path = tmp_path / "000010000.pnd"
    write_synthetic_pnd(path, {"WET_FR": 0.1, "WET_K": 50.0})

    write_wetland_params(path, {"wet_fr": 0.6, "wet_nsa": 20.5})

    params = parse_pnd_file(path, subbasin_id=1)
    assert params.wet_fr == 0.6
    assert params.wet_nsa_ha == 20.5
    assert params.wet_k_mmhr == 50.0  # untouched
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda activate swat && pytest tests/swat_io/test_pnd_parser.py -v`
Expected: FAIL — `ImportError: cannot import name 'write_wetland_params'`

- [ ] **Step 3: Implement write_wetland_params**

Add to `swat_io/pnd_parser.py`:

```python
from .text_format import parse_value_code_file, write_value_code_file

_FIELD_TO_CODE = {
    "wet_fr": "WET_FR",
    "wet_nsa": "WET_NSA",
    "wet_nvol": "WET_NVOL",
    "wet_mxsa": "WET_MXSA",
    "wet_mxvol": "WET_MXVOL",
    "wet_vol": "WET_VOL",
    "wet_k": "WET_K",
}


def write_wetland_params(path: Path, values: dict[str, float]) -> None:
    """Escribe los parámetros editables de humedal en un .pnd.

    values usa las claves del formulario declarativo (wet_fr, wet_nsa,
    ...), no los códigos SWAT crudos.
    """
    updates = {_FIELD_TO_CODE[field_id]: value for field_id, value in values.items()}
    write_value_code_file(path, updates)
```

(The existing `from .text_format import parse_value_code_file` import line gets the `write_value_code_file` name added to it.)

- [ ] **Step 4: Run test to verify it passes**

Run: `conda activate swat && pytest tests/swat_io/test_pnd_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add swat_io/pnd_parser.py tests/swat_io/test_pnd_parser.py
git commit -m "feat: add write_wetland_params to write form values back to a .pnd file"
```

---

## Task 3: Base model discovery — `discover_base_models`

**Files:**
- Modify: `swat_io/discovery.py`
- Test: `tests/swat_io/test_discovery.py`

**Interfaces:**
- Produces:
  - `swat_io.discovery.BaseModelInfo` — frozen dataclass: `watershed: str`, `model_dir: Path`, `txtinout_dir: Path`.
  - `swat_io.discovery.discover_base_models(base_models_root: Path) -> list[BaseModelInfo]` — one entry per watershed subfolder of `base_models_root` that contains a `{Watershed}_calibrated_*` directory with a `TxtInOut/` inside. Watersheds without a detectable calibrated model are silently skipped.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from swat_io.discovery import discover_base_models


def test_discover_base_models_finds_calibrated_txtinout(tmp_path: Path) -> None:
    buffalo_calibrated = tmp_path / "Buffalo" / "Buffalo_calibrated_annual" / "TxtInOut"
    buffalo_calibrated.mkdir(parents=True)
    (tmp_path / "Buffalo" / "Buffalo_LS_annual" / "TxtInOut").mkdir(parents=True)

    models = discover_base_models(tmp_path)

    assert len(models) == 1
    assert models[0].watershed == "Buffalo"
    assert models[0].model_dir == tmp_path / "Buffalo" / "Buffalo_calibrated_annual"
    assert models[0].txtinout_dir == buffalo_calibrated


def test_discover_base_models_skips_watershed_without_calibrated_model(tmp_path: Path) -> None:
    (tmp_path / "Crooked" / "Crooked_daily" / "TxtInOut").mkdir(parents=True)

    models = discover_base_models(tmp_path)

    assert models == []


def test_discover_base_models_returns_empty_for_missing_root(tmp_path: Path) -> None:
    assert discover_base_models(tmp_path / "does_not_exist") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda activate swat && pytest tests/swat_io/test_discovery.py -v`
Expected: FAIL — `ImportError: cannot import name 'discover_base_models'`

- [ ] **Step 3: Implement discover_base_models**

Add to `swat_io/discovery.py`:

```python
_CALIBRATED_DIRNAME = re.compile(r"^[A-Za-z0-9]+_calibrated_.+$")


@dataclass(frozen=True)
class BaseModelInfo:
    watershed: str
    model_dir: Path
    txtinout_dir: Path


def discover_base_models(base_models_root: Path) -> list["BaseModelInfo"]:
    """Lista los modelos calibrados bajo base_models_root, uno por cuenca.

    Para cada subcarpeta de primer nivel (una por cuenca), busca una
    carpeta hija que siga la convención "{Watershed}_calibrated_*" y
    contenga TxtInOut/. Cuencas sin modelo calibrado detectable se omiten.
    """
    base_models_root = Path(base_models_root)
    models: list[BaseModelInfo] = []
    if not base_models_root.is_dir():
        return models
    for watershed_dir in sorted(base_models_root.iterdir()):
        if not watershed_dir.is_dir():
            continue
        for candidate in sorted(watershed_dir.iterdir()):
            if not candidate.is_dir() or not _CALIBRATED_DIRNAME.match(candidate.name):
                continue
            txtinout_dir = candidate / "TxtInOut"
            if txtinout_dir.is_dir():
                models.append(BaseModelInfo(watershed_dir.name, candidate, txtinout_dir))
                break
    return models
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda activate swat && pytest tests/swat_io/test_discovery.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add swat_io/discovery.py tests/swat_io/test_discovery.py
git commit -m "feat: add discover_base_models to list calibrated watershed models"
```

---

## Task 4: Config — target executable name, theme path, path validation

**Files:**
- Modify: `config/settings.py`
- Test: `tests/config/test_settings.py`

**Interfaces:**
- Produces:
  - `config.settings.AppPaths.target_executable_name: str` (default `"swatUser.exe"`) — new field.
  - `config.settings.ConfigManager.theme_path() -> Path`.
  - `config.settings.validate_app_paths(swat_executable: Path, base_models_root: Path, workspace_root: Path) -> str | None` — returns an `es.json` error key (`"config.error.invalid_executable"` or `"config.error.invalid_directory"`) or `None` if all three paths are valid on disk.
- Consumes: nothing new (extends existing `AppPaths`/`ConfigManager`).

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from config.settings import AppPaths, ConfigManager, validate_app_paths


def test_app_paths_round_trip_including_target_executable_name(tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"
    manager = ConfigManager(config_file=config_file)
    exe = tmp_path / "swat2012.exe"
    exe.write_text("fake binary")
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    paths = AppPaths(
        swat_executable=exe,
        base_models_root=models_dir,
        workspace_root=workspace_dir,
        target_executable_name="custom.exe",
    )
    manager.save_paths(paths)

    reloaded = ConfigManager(config_file=config_file)
    loaded_paths = reloaded._load_paths()

    assert loaded_paths.swat_executable == exe
    assert loaded_paths.base_models_root == models_dir
    assert loaded_paths.workspace_root == workspace_dir
    assert loaded_paths.target_executable_name == "custom.exe"


def test_app_paths_default_target_executable_name() -> None:
    assert AppPaths().target_executable_name == "swatUser.exe"


def test_theme_path_points_at_theme_json(tmp_path: Path) -> None:
    manager = ConfigManager(resources_dir=tmp_path, config_file=tmp_path / "config.json")
    assert manager.theme_path() == tmp_path / "theme" / "swat_light.json"


def test_validate_app_paths_valid(tmp_path: Path) -> None:
    exe = tmp_path / "swat2012.exe"
    exe.write_text("fake binary")
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    assert validate_app_paths(exe, models_dir, workspace_dir) is None


def test_validate_app_paths_invalid_executable(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    error = validate_app_paths(tmp_path / "missing.exe", models_dir, workspace_dir)

    assert error == "config.error.invalid_executable"


def test_validate_app_paths_invalid_directory(tmp_path: Path) -> None:
    exe = tmp_path / "swat2012.exe"
    exe.write_text("fake binary")

    error = validate_app_paths(exe, tmp_path / "missing_models", tmp_path / "missing_workspace")

    assert error == "config.error.invalid_directory"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda activate swat && pytest tests/config/test_settings.py -v`
Expected: FAIL — `TypeError: AppPaths.__init__() got an unexpected keyword argument 'target_executable_name'`

- [ ] **Step 3: Implement the changes**

In `config/settings.py`, update `AppPaths`:

```python
@dataclass
class AppPaths:
    """Rutas sensibles a la máquina del usuario. Ningún valor por defecto aquí: se piden y validan en la UI."""

    swat_executable: Path | None = None
    base_models_root: Path | None = None
    workspace_root: Path | None = None
    target_executable_name: str = "swatUser.exe"

    def is_complete(self) -> bool:
        return all([self.swat_executable, self.base_models_root, self.workspace_root])
```

Update `ConfigManager.save_paths` and `_load_paths` to only apply `Path(...)` conversion to the actual path fields (not `target_executable_name`), and add `theme_path`:

```python
_PATH_FIELDS = ("swat_executable", "base_models_root", "workspace_root")


class ConfigManager:
    ...

    def theme_path(self) -> Path:
        return self._resources_dir / "theme" / "swat_light.json"

    def save_paths(self, paths: AppPaths) -> None:
        self._config_file.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(paths)
        for field in _PATH_FIELDS:
            data[field] = str(data[field]) if data[field] is not None else None
        with self._config_file.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self.paths = paths

    def _load_paths(self) -> AppPaths:
        if not self._config_file.exists():
            return AppPaths()
        data = self._load_json(self._config_file)
        kwargs: dict = {}
        for field in _PATH_FIELDS:
            value = data.get(field)
            kwargs[field] = Path(value) if value else None
        if data.get("target_executable_name"):
            kwargs["target_executable_name"] = data["target_executable_name"]
        return AppPaths(**kwargs)
```

Add module-level function `validate_app_paths` (below `ConfigManager` or above — either is fine, keep with related code):

```python
def validate_app_paths(swat_executable: Path, base_models_root: Path, workspace_root: Path) -> str | None:
    """Devuelve una clave de error de es.json si alguna ruta es inválida, o None si todas lo son."""
    if not Path(swat_executable).is_file():
        return "config.error.invalid_executable"
    if not Path(base_models_root).is_dir() or not Path(workspace_root).is_dir():
        return "config.error.invalid_directory"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda activate swat && pytest tests/config/test_settings.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add config/settings.py tests/config/test_settings.py
git commit -m "feat: add target executable name, theme_path, and path validation to config"
```

---

## Task 5: Scenario naming — `scenarios/models.py`

**Files:**
- Create: `scenarios/models.py`
- Test: `tests/scenarios/test_models.py`

**Interfaces:**
- Produces:
  - `scenarios.models.WETLAND_ABBREVIATIONS: tuple[str, ...]` = `("WET_LS", "WET_MS", "WET_HS")`.
  - `scenarios.models.Project` — frozen dataclass: `watershed: str`, `base_model_dir: Path`, `base_txtinout_dir: Path`, `project_dir: Path`.
  - `scenarios.models.build_scenario_name(watershed: str, abbreviation: str, timestep: str) -> str` — raises `ValueError` if `abbreviation` isn't in `WETLAND_ABBREVIATIONS` or `timestep` is blank; otherwise returns `f"{watershed}_{abbreviation}_{timestep.strip()}"`.

- [ ] **Step 1: Write the failing test**

```python
import pytest

from scenarios.models import WETLAND_ABBREVIATIONS, build_scenario_name


def test_build_scenario_name_composes_convention() -> None:
    assert build_scenario_name("Buffalo", "WET_MS", "annual") == "Buffalo_WET_MS_annual"


def test_build_scenario_name_strips_timestep_whitespace() -> None:
    assert build_scenario_name("Buffalo", "WET_LS", "  annual  ") == "Buffalo_WET_LS_annual"


@pytest.mark.parametrize("abbreviation", ["LS", "wet_ms", "WET_XX", ""])
def test_build_scenario_name_rejects_invalid_abbreviation(abbreviation: str) -> None:
    with pytest.raises(ValueError):
        build_scenario_name("Buffalo", abbreviation, "annual")


@pytest.mark.parametrize("timestep", ["", "   "])
def test_build_scenario_name_rejects_blank_timestep(timestep: str) -> None:
    with pytest.raises(ValueError):
        build_scenario_name("Buffalo", "WET_MS", timestep)


def test_wetland_abbreviations_content() -> None:
    assert WETLAND_ABBREVIATIONS == ("WET_LS", "WET_MS", "WET_HS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda activate swat && pytest tests/scenarios/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scenarios.models'`

- [ ] **Step 3: Implement scenarios/models.py**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

WETLAND_ABBREVIATIONS: tuple[str, ...] = ("WET_LS", "WET_MS", "WET_HS")


@dataclass(frozen=True)
class Project:
    watershed: str
    base_model_dir: Path
    base_txtinout_dir: Path
    project_dir: Path


def build_scenario_name(watershed: str, abbreviation: str, timestep: str) -> str:
    """Compone el nombre de escenario {Watershed}_{Abbrev}_{timestep} de CLAUDE.md."""
    if abbreviation not in WETLAND_ABBREVIATIONS:
        raise ValueError(
            f"Abreviación inválida: {abbreviation!r}. Debe ser una de {WETLAND_ABBREVIATIONS}."
        )
    if not timestep or not timestep.strip():
        raise ValueError("El periodo (timestep) no puede estar vacío.")
    return f"{watershed}_{abbreviation}_{timestep.strip()}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda activate swat && pytest tests/scenarios/test_models.py -v`
Expected: PASS (9 tests, counting parametrize expansion)

- [ ] **Step 5: Commit**

```bash
git add scenarios/models.py tests/scenarios/test_models.py
git commit -m "feat: add Project model and scenario name convention builder"
```

---

## Task 6: Project lifecycle — `scenarios/project.py`

**Files:**
- Create: `scenarios/project.py`
- Test: `tests/scenarios/test_project.py`

**Interfaces:**
- Consumes: `scenarios.models.Project` (Task 5).
- Produces: `scenarios.project.open_or_create_project(workspace_root: Path, watershed: str, base_model_dir: Path, base_txtinout_dir: Path) -> Project`. Creates `workspace_root/{watershed}/` if it doesn't exist (idempotent — safe to call again on an existing project).

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from scenarios.project import open_or_create_project


def test_open_or_create_project_creates_directory(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    base_model_dir = tmp_path / "base" / "Buffalo_calibrated_annual"
    base_txtinout_dir = base_model_dir / "TxtInOut"

    project = open_or_create_project(workspace_root, "Buffalo", base_model_dir, base_txtinout_dir)

    assert project.project_dir == workspace_root / "Buffalo"
    assert project.project_dir.is_dir()
    assert project.watershed == "Buffalo"
    assert project.base_model_dir == base_model_dir
    assert project.base_txtinout_dir == base_txtinout_dir


def test_open_or_create_project_is_idempotent(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    base_model_dir = tmp_path / "base" / "Buffalo_calibrated_annual"
    base_txtinout_dir = base_model_dir / "TxtInOut"

    open_or_create_project(workspace_root, "Buffalo", base_model_dir, base_txtinout_dir)
    project = open_or_create_project(workspace_root, "Buffalo", base_model_dir, base_txtinout_dir)

    assert project.project_dir.is_dir()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda activate swat && pytest tests/scenarios/test_project.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scenarios.project'`

- [ ] **Step 3: Implement scenarios/project.py**

```python
from __future__ import annotations

from pathlib import Path

from .models import Project


def open_or_create_project(
    workspace_root: Path, watershed: str, base_model_dir: Path, base_txtinout_dir: Path
) -> Project:
    """Abre (o crea si no existe) la carpeta de proyecto de una cuenca."""
    project_dir = Path(workspace_root) / watershed
    project_dir.mkdir(parents=True, exist_ok=True)
    return Project(
        watershed=watershed,
        base_model_dir=Path(base_model_dir),
        base_txtinout_dir=Path(base_txtinout_dir),
        project_dir=project_dir,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda activate swat && pytest tests/scenarios/test_project.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add scenarios/project.py tests/scenarios/test_project.py
git commit -m "feat: add open_or_create_project for the initial window's project flow"
```

---

## Task 7: Field validation — `scenarios/validation.py`

**Files:**
- Create: `scenarios/validation.py`
- Test: `tests/scenarios/test_validation.py`

**Interfaces:**
- Consumes: a `layout: dict` shaped like the parsed `resources/layout/wetland_pond.yaml` (`{"fields": [{"id": ..., "range": [lo, hi], ...}, ...]}`).
- Produces: `scenarios.validation.validate_field_value(field_id: str, value: float, layout: dict) -> None` — raises `ValueError` (message includes `field_id` and the offending bound) if `value` is outside `range`; `None` bounds are unbounded. Raises `KeyError` if `field_id` isn't in `layout["fields"]`.

- [ ] **Step 1: Write the failing test**

```python
import pytest

from scenarios.validation import validate_field_value

_LAYOUT = {
    "fields": [
        {"id": "wet_fr", "range": [0.0, 1.0]},
        {"id": "wet_nsa", "range": [0.0, None]},
    ]
}


def test_validate_field_value_accepts_in_range_value() -> None:
    validate_field_value("wet_fr", 0.5, _LAYOUT)  # no exception


def test_validate_field_value_rejects_below_minimum() -> None:
    with pytest.raises(ValueError, match="wet_fr"):
        validate_field_value("wet_fr", -0.1, _LAYOUT)


def test_validate_field_value_rejects_above_maximum() -> None:
    with pytest.raises(ValueError, match="wet_fr"):
        validate_field_value("wet_fr", 1.5, _LAYOUT)


def test_validate_field_value_allows_unbounded_maximum() -> None:
    validate_field_value("wet_nsa", 1_000_000.0, _LAYOUT)  # no exception


def test_validate_field_value_rejects_unknown_field() -> None:
    with pytest.raises(KeyError):
        validate_field_value("not_a_field", 1.0, _LAYOUT)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda activate swat && pytest tests/scenarios/test_validation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scenarios.validation'`

- [ ] **Step 3: Implement scenarios/validation.py**

```python
from __future__ import annotations


def _field_by_id(layout: dict, field_id: str) -> dict:
    for field in layout["fields"]:
        if field["id"] == field_id:
            return field
    raise KeyError(f"Campo desconocido en el layout: {field_id}")


def validate_field_value(field_id: str, value: float, layout: dict) -> None:
    """Valida value contra el rango [lo, hi] declarado para field_id en layout.

    lo/hi en None significan "sin cota" de ese lado.
    """
    field = _field_by_id(layout, field_id)
    lo, hi = field["range"]
    if lo is not None and value < lo:
        raise ValueError(f"{field_id}: {value} está por debajo del mínimo permitido ({lo}).")
    if hi is not None and value > hi:
        raise ValueError(f"{field_id}: {value} está por encima del máximo permitido ({hi}).")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda activate swat && pytest tests/scenarios/test_validation.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add scenarios/validation.py tests/scenarios/test_validation.py
git commit -m "feat: add validate_field_value for wetland form range checks"
```

---

## Task 8: Draft CSV lifecycle — `scenarios/draft.py`

**Files:**
- Create: `scenarios/draft.py`
- Test: `tests/scenarios/test_draft.py`

**Interfaces:**
- Consumes: `scenarios.models.Project` (Task 5), `scenarios.validation.validate_field_value` (Task 7), `swat_io.summary.summarize_project` (existing).
- Produces:
  - `scenarios.draft.draft_csv_path(project: Project, scenario_name: str) -> Path` → `project.project_dir / "_borradores" / f"{scenario_name}.csv"`.
  - `scenarios.draft.init_draft(project: Project, scenario_name: str) -> Path` — builds the draft CSV (columns: `subbasin_id` index + `wet_fr`, `wet_nsa`, `wet_nvol`, `wet_mxsa`, `wet_mxvol`, `wet_vol`, `wet_k`) seeded from the base model's current values, writes it, returns its path.
  - `scenarios.draft.read_draft(csv_path: Path) -> pandas.DataFrame`.
  - `scenarios.draft.update_draft_value(csv_path: Path, subbasin_id: int, field_id: str, value: float, layout: dict) -> pandas.DataFrame` — validates then writes a single cell, persists to disk, returns the updated DataFrame. Raises `ValueError` on an invalid value (nothing is written), `KeyError` if `subbasin_id` isn't in the draft.
  - `scenarios.draft.import_draft_csv(csv_path: Path, import_path: Path, layout: dict) -> pandas.DataFrame` — validates the entire imported CSV (required columns present, every value in range, every `subbasin_id` already present in the draft) before writing anything; raises `ValueError` with a message identifying the offending row/column on the first problem found, and applies nothing in that case.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

import pandas as pd
import pytest

from scenarios.draft import draft_csv_path, import_draft_csv, init_draft, read_draft, update_draft_value
from scenarios.models import Project
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


def _make_project(tmp_path: Path) -> Project:
    base_dir = tmp_path / "base" / "Buffalo_calibrated_annual"
    txtinout_dir = make_synthetic_txtinout(
        base_dir,
        {
            1: {"WET_FR": 0.2, "WET_NSA": 10.0},
            2: {"WET_FR": 0.0, "WET_NSA": 0.0},
        },
    )
    project_dir = tmp_path / "workspace" / "Buffalo"
    project_dir.mkdir(parents=True)
    return Project(
        watershed="Buffalo",
        base_model_dir=base_dir,
        base_txtinout_dir=txtinout_dir,
        project_dir=project_dir,
    )


def test_init_draft_seeds_from_base_model(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    path = init_draft(project, "Buffalo_WET_MS_annual")

    assert path == draft_csv_path(project, "Buffalo_WET_MS_annual")
    draft = read_draft(path)
    assert list(draft.index) == [1, 2]
    assert draft.loc[1, "wet_fr"] == 0.2
    assert draft.loc[2, "wet_fr"] == 0.0


def test_update_draft_value_writes_valid_value(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    path = init_draft(project, "Buffalo_WET_MS_annual")

    draft = update_draft_value(path, 1, "wet_fr", 0.75, _LAYOUT)

    assert draft.loc[1, "wet_fr"] == 0.75
    assert read_draft(path).loc[1, "wet_fr"] == 0.75


def test_update_draft_value_rejects_out_of_range_and_writes_nothing(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    path = init_draft(project, "Buffalo_WET_MS_annual")

    with pytest.raises(ValueError):
        update_draft_value(path, 1, "wet_fr", 1.5, _LAYOUT)

    assert read_draft(path).loc[1, "wet_fr"] == 0.2


def test_update_draft_value_rejects_unknown_subbasin(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    path = init_draft(project, "Buffalo_WET_MS_annual")

    with pytest.raises(KeyError):
        update_draft_value(path, 999, "wet_fr", 0.5, _LAYOUT)


def test_import_draft_csv_applies_all_valid_rows(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    path = init_draft(project, "Buffalo_WET_MS_annual")

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
    project = _make_project(tmp_path)
    path = init_draft(project, "Buffalo_WET_MS_annual")

    import_path = tmp_path / "import.csv"
    pd.DataFrame([{"subbasin_id": 1, "wet_fr": 0.5}]).to_csv(import_path, index=False)

    with pytest.raises(ValueError):
        import_draft_csv(path, import_path, _LAYOUT)

    assert read_draft(path).loc[1, "wet_fr"] == 0.2


def test_import_draft_csv_rejects_out_of_range_value_and_applies_nothing(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    path = init_draft(project, "Buffalo_WET_MS_annual")

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

- [ ] **Step 2: Run test to verify it fails**

Run: `conda activate swat && pytest tests/scenarios/test_draft.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scenarios.draft'`

- [ ] **Step 3: Implement scenarios/draft.py**

```python
from __future__ import annotations

from pathlib import Path

import pandas as pd

from swat_io.summary import summarize_project

from .models import Project
from .validation import validate_field_value

_DRAFT_DIRNAME = "_borradores"

_SUMMARY_TO_FIELD = {
    "wet_fr": "wet_fr",
    "wet_nsa_ha": "wet_nsa",
    "wet_nvol_104m3": "wet_nvol",
    "wet_mxsa_ha": "wet_mxsa",
    "wet_mxvol_104m3": "wet_mxvol",
    "wet_vol_104m3": "wet_vol",
    "wet_k_mmhr": "wet_k",
}


def draft_csv_path(project: Project, scenario_name: str) -> Path:
    return project.project_dir / _DRAFT_DIRNAME / f"{scenario_name}.csv"


def init_draft(project: Project, scenario_name: str) -> Path:
    """Crea el borrador de un escenario, sembrado con los valores actuales del modelo base."""
    summary = summarize_project(project.base_txtinout_dir)
    draft = summary[list(_SUMMARY_TO_FIELD.keys())].rename(columns=_SUMMARY_TO_FIELD)
    path = draft_csv_path(project, scenario_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    draft.to_csv(path)
    return path


def read_draft(csv_path: Path) -> pd.DataFrame:
    return pd.read_csv(csv_path, index_col="subbasin_id")


def update_draft_value(
    csv_path: Path, subbasin_id: int, field_id: str, value: float, layout: dict
) -> pd.DataFrame:
    """Valida value y, si es válido, lo escribe en el borrador (memoria + disco)."""
    validate_field_value(field_id, value, layout)
    draft = read_draft(csv_path)
    if subbasin_id not in draft.index:
        raise KeyError(f"Subcuenca {subbasin_id} no está en el borrador.")
    draft.loc[subbasin_id, field_id] = value
    draft.to_csv(csv_path)
    return draft


def import_draft_csv(csv_path: Path, import_path: Path, layout: dict) -> pd.DataFrame:
    """Valida el CSV importado por completo antes de aplicar nada (all-or-nothing)."""
    field_ids = [f["id"] for f in layout["fields"]]
    incoming = pd.read_csv(import_path)

    if "subbasin_id" not in incoming.columns:
        raise ValueError("El CSV importado no tiene la columna 'subbasin_id'.")
    missing = [f for f in field_ids if f not in incoming.columns]
    if missing:
        raise ValueError(f"El CSV importado no tiene las columnas: {', '.join(missing)}.")

    draft = read_draft(csv_path)
    for _, row in incoming.iterrows():
        subbasin_id = int(row["subbasin_id"])
        if subbasin_id not in draft.index:
            raise ValueError(f"Fila con subbasin_id={subbasin_id}: no existe en este escenario.")
        for field_id in field_ids:
            validate_field_value(field_id, float(row[field_id]), layout)

    for _, row in incoming.iterrows():
        subbasin_id = int(row["subbasin_id"])
        for field_id in field_ids:
            draft.loc[subbasin_id, field_id] = float(row[field_id])

    draft.to_csv(csv_path)
    return draft
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda activate swat && pytest tests/scenarios/test_draft.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add scenarios/draft.py tests/scenarios/test_draft.py
git commit -m "feat: add scenario draft CSV lifecycle (init, read, update, import)"
```

---

## Task 9: Scenario materialization — `engine/configure.py`

**Files:**
- Create: `engine/configure.py`
- Test: `tests/engine/test_configure.py`

**Interfaces:**
- Consumes: `scenarios.models.Project`, `scenarios.draft.draft_csv_path`/`read_draft` (Task 8), `swat_io.pnd_parser.write_wetland_params` (Task 2).
- Produces:
  - `engine.configure.ConfigureResult` — frozen dataclass: `scenario_dir: Path`, `txtinout_dir: Path`, `params_csv: Path`.
  - `engine.configure.configure_scenario(project: Project, scenario_name: str, swat_executable: Path, target_executable_name: str) -> ConfigureResult`. Implements CLAUDE.md steps 1–3: copies `project.base_txtinout_dir` to `project.project_dir/{scenario_name}/TxtInOut`, writes every draft row into the corresponding copied `.pnd`, copies `swat_executable` into that folder renamed to `target_executable_name`, then moves the draft CSV to `{scenario_name}/tool_outputs/scenario_params.csv`. Raises `FileNotFoundError` if no draft exists for `scenario_name`; raises `FileExistsError` if the scenario's `TxtInOut` already exists (never overwrites a previously configured scenario).

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

import pytest

from engine.configure import configure_scenario
from scenarios.draft import draft_csv_path, init_draft, update_draft_value
from scenarios.models import Project
from swat_io.pnd_parser import parse_pnd_file
from tests.helpers import make_synthetic_txtinout

_LAYOUT = {"fields": [{"id": "wet_fr", "range": [0.0, 1.0]}]}


def _make_project(tmp_path: Path) -> Project:
    base_dir = tmp_path / "base" / "Buffalo_calibrated_annual"
    txtinout_dir = make_synthetic_txtinout(base_dir, {1: {"WET_FR": 0.2}, 2: {"WET_FR": 0.0}})
    project_dir = tmp_path / "workspace" / "Buffalo"
    project_dir.mkdir(parents=True)
    return Project(
        watershed="Buffalo",
        base_model_dir=base_dir,
        base_txtinout_dir=txtinout_dir,
        project_dir=project_dir,
    )


def test_configure_scenario_materializes_working_copy(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    draft_path = init_draft(project, "Buffalo_WET_MS_annual")
    update_draft_value(draft_path, 1, "wet_fr", 0.9, _LAYOUT)
    swat_executable = tmp_path / "rev670_64rel.exe"
    swat_executable.write_text("fake binary")

    result = configure_scenario(project, "Buffalo_WET_MS_annual", swat_executable, "swatUser.exe")

    assert result.txtinout_dir == project.project_dir / "Buffalo_WET_MS_annual" / "TxtInOut"
    assert (result.txtinout_dir / "swatUser.exe").exists()
    updated = parse_pnd_file(result.txtinout_dir / "000010000.pnd", subbasin_id=1)
    assert updated.wet_fr == 0.9
    unchanged = parse_pnd_file(result.txtinout_dir / "000020000.pnd", subbasin_id=2)
    assert unchanged.wet_fr == 0.0
    assert result.params_csv == result.scenario_dir / "tool_outputs" / "scenario_params.csv"
    assert result.params_csv.exists()
    assert not draft_path.exists()
    # base model untouched
    base_pnd = parse_pnd_file(project.base_txtinout_dir / "000010000.pnd", subbasin_id=1)
    assert base_pnd.wet_fr == 0.2


def test_configure_scenario_raises_without_a_draft(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    swat_executable = tmp_path / "rev670_64rel.exe"
    swat_executable.write_text("fake binary")

    with pytest.raises(FileNotFoundError):
        configure_scenario(project, "Buffalo_WET_MS_annual", swat_executable, "swatUser.exe")


def test_configure_scenario_refuses_to_overwrite_existing_scenario(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    init_draft(project, "Buffalo_WET_MS_annual")
    swat_executable = tmp_path / "rev670_64rel.exe"
    swat_executable.write_text("fake binary")
    configure_scenario(project, "Buffalo_WET_MS_annual", swat_executable, "swatUser.exe")

    init_draft(project, "Buffalo_WET_MS_annual")  # recreate a draft with the same name
    with pytest.raises(FileExistsError):
        configure_scenario(project, "Buffalo_WET_MS_annual", swat_executable, "swatUser.exe")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda activate swat && pytest tests/engine/test_configure.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.configure'`

- [ ] **Step 3: Implement engine/configure.py**

```python
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from scenarios.draft import draft_csv_path, read_draft
from scenarios.models import Project
from swat_io.pnd_parser import write_wetland_params


@dataclass(frozen=True)
class ConfigureResult:
    scenario_dir: Path
    txtinout_dir: Path
    params_csv: Path


def configure_scenario(
    project: Project, scenario_name: str, swat_executable: Path, target_executable_name: str
) -> ConfigureResult:
    """Materializa un escenario: copia TxtInOut, aplica el borrador a los
    .pnd de la copia, y coloca el ejecutable configurado.

    Implementa los pasos 1-3 de la secuencia obligatoria de CLAUDE.md. No
    invoca el subproceso de SWAT.
    """
    draft_path = draft_csv_path(project, scenario_name)
    if not draft_path.exists():
        raise FileNotFoundError(f"No existe un borrador para el escenario {scenario_name!r}.")
    draft = read_draft(draft_path)

    scenario_dir = project.project_dir / scenario_name
    txtinout_dir = scenario_dir / "TxtInOut"
    if txtinout_dir.exists():
        raise FileExistsError(
            f"Ya existe una carpeta de trabajo para {scenario_name!r}: {txtinout_dir}"
        )
    shutil.copytree(project.base_txtinout_dir, txtinout_dir)

    field_ids = list(draft.columns)
    for subbasin_id, row in draft.iterrows():
        pnd_file = txtinout_dir / f"{int(subbasin_id):05d}0000.pnd"
        write_wetland_params(pnd_file, {field_id: float(row[field_id]) for field_id in field_ids})

    shutil.copy2(swat_executable, txtinout_dir / target_executable_name)

    tool_outputs_dir = scenario_dir / "tool_outputs"
    tool_outputs_dir.mkdir(parents=True, exist_ok=True)
    params_csv = tool_outputs_dir / "scenario_params.csv"
    shutil.move(str(draft_path), str(params_csv))

    return ConfigureResult(scenario_dir=scenario_dir, txtinout_dir=txtinout_dir, params_csv=params_csv)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda activate swat && pytest tests/engine/test_configure.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/configure.py tests/engine/test_configure.py
git commit -m "feat: add configure_scenario to materialize a scenario working folder"
```

---

## Task 10: Localization keys

**Files:**
- Modify: `resources/strings/es.json`
- Test: `tests/resources/test_strings.py`

**Interfaces:**
- Produces: new keys consumed by Tasks 11-17's `ui/` code (listed in Step 3).

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path

_STRINGS_PATH = Path(__file__).resolve().parents[2] / "resources" / "strings" / "es.json"

_REQUIRED_NEW_KEYS = [
    "config.target_executable_name",
    "config.error.invalid_directory",
    "project.open_or_create",
    "project.no_selection",
    "project.no_scenario",
    "project.action.create",
    "project.action.open",
    "scenario.abbreviation",
    "scenario.timestep",
    "scenario.error.duplicate_name",
    "wetland.count",
    "wetland.import_csv",
    "wetland.import_error",
    "wetland.import_success",
    "action.configure_scenario",
]


def test_es_json_has_new_keys() -> None:
    strings = json.loads(_STRINGS_PATH.read_text(encoding="utf-8"))
    missing = [key for key in _REQUIRED_NEW_KEYS if key not in strings]
    assert missing == []


def test_wetland_count_has_expected_placeholders() -> None:
    strings = json.loads(_STRINGS_PATH.read_text(encoding="utf-8"))
    assert strings["wetland.count"].format(with_wetland=3, total=84) == "3 de 84 subcuencas con humedal"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda activate swat && pytest tests/resources/test_strings.py -v`
Expected: FAIL — `assert missing == []` fails with the full list of missing keys

- [ ] **Step 3: Add the new keys to resources/strings/es.json**

Insert these entries (e.g. `config.*` ones next to the existing `config.*` block, `project.*`/`scenario.*`/`wetland.*` next to their existing blocks, `action.configure_scenario` next to `action.cancel`/`action.confirm`):

```json
  "config.target_executable_name": "Nombre del ejecutable en la carpeta de escenario",
  "config.error.invalid_directory": "La ruta no apunta a una carpeta válida.",

  "project.open_or_create": "Abrir o crear proyecto",
  "project.no_selection": "Ningún proyecto seleccionado",
  "project.no_scenario": "Sin escenario — define uno en Parametrización",
  "project.action.create": "Crear proyecto nuevo",
  "project.action.open": "Abrir proyecto existente",

  "scenario.abbreviation": "Tipo de escenario",
  "scenario.timestep": "Periodo (timestep)",
  "scenario.error.duplicate_name": "Ya existe un escenario con ese nombre en este proyecto.",

  "wetland.count": "{with_wetland} de {total} subcuencas con humedal",
  "wetland.import_csv": "Importar CSV",
  "wetland.import_error": "No se pudo importar el CSV: {error}",
  "wetland.import_success": "CSV importado correctamente.",

  "action.configure_scenario": "Configurar escenario"
```

Keep the file valid JSON (comma placement, no trailing comma on the last key overall).

- [ ] **Step 4: Run test to verify it passes**

Run: `conda activate swat && pytest tests/resources/test_strings.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add resources/strings/es.json tests/resources/test_strings.py
git commit -m "feat: add localization keys for project/scenario/parametrización UI"
```

---

## Task 11: Reusable modal dialogs — `ui/dialogs.py`

**Files:**
- Create: `ui/dialogs.py`
- Test: `tests/ui/conftest.py`, `tests/ui/test_dialogs.py`

**Note:** these tests instantiate real CustomTkinter widgets and need a local Windows session with a display.

**Interfaces:**
- Produces:
  - `ui.dialogs.ask_choice(parent, title: str, options: list[str], confirm_text: str, cancel_text: str) -> str | None`.
  - `ui.dialogs.ask_text(parent, title: str, confirm_text: str, cancel_text: str, default: str = "") -> str | None`.

Both open a modal `CTkToplevel`, block via `parent.wait_window(dialog)`, and return `None` if the user cancels or closes the window.

- [ ] **Step 1: Write tests/ui/conftest.py**

```python
import customtkinter as ctk
import pytest


@pytest.fixture
def hidden_root():
    root = ctk.CTk()
    root.withdraw()
    yield root
    root.destroy()
```

- [ ] **Step 2: Write the failing test**

`ask_choice`/`ask_text` block on `wait_window` until a button is clicked, which makes driving them with simulated events brittle. Keep this test file to a plain importability/signature smoke test; Tasks 14 and 16 exercise the real decision logic around them (`_create_project`, `_prompt_scenario_name`) by monkeypatching `ask_choice`/`ask_text` directly, which is the reliable way to test code that calls these.

```python
def test_dialogs_module_exposes_ask_choice_and_ask_text() -> None:
    from ui import dialogs

    assert callable(dialogs.ask_choice)
    assert callable(dialogs.ask_text)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `conda activate swat && pytest tests/ui/test_dialogs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui.dialogs'`

- [ ] **Step 4: Implement ui/dialogs.py**

```python
from __future__ import annotations

import customtkinter as ctk


def ask_choice(
    parent, title: str, options: list[str], confirm_text: str, cancel_text: str
) -> str | None:
    if not options:
        return None
    dialog = ctk.CTkToplevel(parent)
    dialog.title(title)
    dialog.grab_set()
    result: dict[str, str | None] = {"value": None}

    var = ctk.StringVar(value=options[0])
    ctk.CTkLabel(dialog, text=title).pack(padx=20, pady=(20, 8))
    ctk.CTkOptionMenu(dialog, variable=var, values=options).pack(padx=20, pady=8)

    def confirm() -> None:
        result["value"] = var.get()
        dialog.destroy()

    button_row = ctk.CTkFrame(dialog, fg_color="transparent")
    button_row.pack(pady=(8, 20))
    ctk.CTkButton(button_row, text=confirm_text, command=confirm).pack(side="left", padx=8)
    ctk.CTkButton(button_row, text=cancel_text, command=dialog.destroy).pack(side="left", padx=8)

    parent.wait_window(dialog)
    return result["value"]


def ask_text(parent, title: str, confirm_text: str, cancel_text: str, default: str = "") -> str | None:
    dialog = ctk.CTkToplevel(parent)
    dialog.title(title)
    dialog.grab_set()
    result: dict[str, str | None] = {"value": None}

    ctk.CTkLabel(dialog, text=title).pack(padx=20, pady=(20, 8))
    entry = ctk.CTkEntry(dialog)
    entry.insert(0, default)
    entry.pack(padx=20, pady=8)

    def confirm() -> None:
        result["value"] = entry.get()
        dialog.destroy()

    button_row = ctk.CTkFrame(dialog, fg_color="transparent")
    button_row.pack(pady=(8, 20))
    ctk.CTkButton(button_row, text=confirm_text, command=confirm).pack(side="left", padx=8)
    ctk.CTkButton(button_row, text=cancel_text, command=dialog.destroy).pack(side="left", padx=8)

    parent.wait_window(dialog)
    return result["value"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `conda activate swat && pytest tests/ui/test_dialogs.py -v`
Expected: PASS (1 test)

- [ ] **Step 6: Commit**

```bash
git add ui/dialogs.py tests/ui/conftest.py tests/ui/test_dialogs.py
git commit -m "feat: add reusable ask_choice/ask_text modal dialogs"
```

---

## Task 12: Generic wetland form builder — `ui/form_builder.py`

**Files:**
- Create: `ui/form_builder.py`
- Test: `tests/ui/test_form_builder.py`

**Note:** needs a local display (uses `hidden_root` from Task 11's `tests/ui/conftest.py`).

**Interfaces:**
- Consumes: `config.settings.ConfigManager.text` (existing), a `layout: dict` from `ConfigManager.load_layout("wetland_pond")`.
- Produces: `ui.form_builder.build_wetland_form(parent, config: ConfigManager, layout: dict, initial_values: dict[str, float], on_commit: Callable[[str, float], None], on_error: Callable[[str, str], None]) -> dict[str, ctk.CTkEntry]`. For each field in `layout["fields"]`, creates a label (via `config.text(field["label_key"])`) + a pre-filled entry. On `<FocusOut>`/`<Return>`, parses the entry text as `float`; on parse failure calls `on_error(field_id, message)`; on parse success calls `on_commit(field_id, value)`, and if that raises `ValueError`, calls `on_error(field_id, str(exc))` — no exception propagates out of the widget callback either way.

- [ ] **Step 1: Write the failing test**

```python
import customtkinter as ctk

from ui.form_builder import build_wetland_form

_LAYOUT = {
    "fields": [
        {"id": "wet_fr", "label_key": "wetland.wet_fr", "range": [0.0, 1.0]},
        {"id": "wet_nsa", "label_key": "wetland.wet_nsa", "range": [0.0, None]},
    ]
}


class _FakeConfig:
    def text(self, key: str) -> str:
        return {"wetland.wet_fr": "WET_FR", "wetland.wet_nsa": "WET_NSA"}[key]


def test_build_wetland_form_creates_one_entry_per_field(hidden_root) -> None:
    parent = ctk.CTkFrame(hidden_root)
    entries = build_wetland_form(parent, _FakeConfig(), _LAYOUT, {"wet_fr": 0.2, "wet_nsa": 10.0}, lambda *_: None, lambda *_: None)

    assert set(entries.keys()) == {"wet_fr", "wet_nsa"}
    assert entries["wet_fr"].get() == "0.2"
    assert entries["wet_nsa"].get() == "10.0"


def test_build_wetland_form_commits_valid_edit(hidden_root) -> None:
    parent = ctk.CTkFrame(hidden_root)
    committed = []
    entries = build_wetland_form(
        parent, _FakeConfig(), _LAYOUT, {"wet_fr": 0.2, "wet_nsa": 10.0},
        on_commit=lambda field_id, value: committed.append((field_id, value)),
        on_error=lambda *_: None,
    )

    entries["wet_fr"].delete(0, "end")
    entries["wet_fr"].insert(0, "0.9")
    entries["wet_fr"].event_generate("<Return>")
    hidden_root.update()

    assert committed == [("wet_fr", 0.9)]


def test_build_wetland_form_reports_unparseable_input(hidden_root) -> None:
    parent = ctk.CTkFrame(hidden_root)
    errors = []
    entries = build_wetland_form(
        parent, _FakeConfig(), _LAYOUT, {"wet_fr": 0.2, "wet_nsa": 10.0},
        on_commit=lambda *_: None,
        on_error=lambda field_id, message: errors.append((field_id, message)),
    )

    entries["wet_fr"].delete(0, "end")
    entries["wet_fr"].insert(0, "not-a-number")
    entries["wet_fr"].event_generate("<Return>")
    hidden_root.update()

    assert errors and errors[0][0] == "wet_fr"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda activate swat && pytest tests/ui/test_form_builder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui.form_builder'`

- [ ] **Step 3: Implement ui/form_builder.py**

```python
from __future__ import annotations

from typing import Callable

import customtkinter as ctk


def build_wetland_form(
    parent: ctk.CTkFrame,
    config,
    layout: dict,
    initial_values: dict[str, float],
    on_commit: Callable[[str, float], None],
    on_error: Callable[[str, str], None],
) -> dict[str, ctk.CTkEntry]:
    entries: dict[str, ctk.CTkEntry] = {}
    for row, field in enumerate(layout["fields"]):
        ctk.CTkLabel(parent, text=config.text(field["label_key"])).grid(
            row=row, column=0, sticky="w", padx=8, pady=4
        )
        entry = ctk.CTkEntry(parent)
        entry.insert(0, str(initial_values.get(field["id"], "")))
        entry.grid(row=row, column=1, sticky="ew", padx=8, pady=4)

        def make_handler(field_id: str, entry_widget: ctk.CTkEntry) -> Callable[[object], None]:
            def handler(_event=None) -> None:
                raw = entry_widget.get()
                try:
                    value = float(raw)
                except ValueError:
                    on_error(field_id, f"'{raw}' no es un número válido.")
                    return
                try:
                    on_commit(field_id, value)
                except ValueError as exc:
                    on_error(field_id, str(exc))

            return handler

        handler = make_handler(field["id"], entry)
        entry.bind("<FocusOut>", handler)
        entry.bind("<Return>", handler)
        entries[field["id"]] = entry

    parent.grid_columnconfigure(1, weight=1)
    return entries
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda activate swat && pytest tests/ui/test_form_builder.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add ui/form_builder.py tests/ui/test_form_builder.py
git commit -m "feat: add generic wetland form builder driven by layout YAML"
```

---

## Task 13: Path configuration dialog — `ui/config_dialog.py`

**Files:**
- Create: `ui/config_dialog.py`
- Test: `tests/ui/test_config_dialog.py`

**Note:** needs a local display.

**Interfaces:**
- Consumes: `config.settings.ConfigManager`, `AppPaths`, `validate_app_paths` (Task 4).
- Produces: `ui.config_dialog.show_config_dialog(parent, config: ConfigManager, on_saved: Callable[[], None]) -> ctk.CTkToplevel` — builds and returns the dialog (returned so tests can drive it without needing to simulate real clicks); calls `on_saved()` and destroys itself once a valid `AppPaths` has been saved via `config.save_paths`.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from config.settings import ConfigManager
from ui.config_dialog import show_config_dialog


def test_show_config_dialog_saves_valid_paths_and_calls_on_saved(hidden_root, tmp_path: Path) -> None:
    resources_dir = Path(__file__).resolve().parents[2] / "resources"
    config = ConfigManager(resources_dir=resources_dir, config_file=tmp_path / "config.json")
    config.load_all()

    exe = tmp_path / "swat2012.exe"
    exe.write_text("fake binary")
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    saved = []
    dialog = show_config_dialog(hidden_root, config, on_saved=lambda: saved.append(True))

    dialog.entries["swat_executable"].insert(0, str(exe))
    dialog.entries["base_models_root"].insert(0, str(models_dir))
    dialog.entries["workspace_root"].insert(0, str(workspace_dir))
    dialog.save_button.invoke()
    hidden_root.update()

    assert saved == [True]
    assert config.paths.swat_executable == exe
    assert config.paths.base_models_root == models_dir
    assert config.paths.workspace_root == workspace_dir


def test_show_config_dialog_shows_error_and_does_not_call_on_saved_when_invalid(hidden_root, tmp_path: Path) -> None:
    resources_dir = Path(__file__).resolve().parents[2] / "resources"
    config = ConfigManager(resources_dir=resources_dir, config_file=tmp_path / "config.json")
    config.load_all()

    saved = []
    dialog = show_config_dialog(hidden_root, config, on_saved=lambda: saved.append(True))

    dialog.entries["swat_executable"].insert(0, str(tmp_path / "missing.exe"))
    dialog.entries["base_models_root"].insert(0, str(tmp_path / "missing_models"))
    dialog.entries["workspace_root"].insert(0, str(tmp_path / "missing_workspace"))
    dialog.save_button.invoke()
    hidden_root.update()

    assert saved == []
    assert dialog.error_label.cget("text") != ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda activate swat && pytest tests/ui/test_config_dialog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui.config_dialog'`

- [ ] **Step 3: Implement ui/config_dialog.py**

```python
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog
from typing import Callable

import customtkinter as ctk

from config.settings import AppPaths, ConfigManager, validate_app_paths


def show_config_dialog(
    parent, config: ConfigManager, on_saved: Callable[[], None]
) -> ctk.CTkToplevel:
    dialog = ctk.CTkToplevel(parent)
    dialog.title(config.text("config.title"))
    dialog.geometry("560x360")
    dialog.grab_set()

    entries: dict[str, ctk.CTkEntry] = {}
    error_label = ctk.CTkLabel(dialog, text="", text_color="#B3261E")

    def add_path_row(row: int, label_key: str, field: str, select_dir: bool) -> None:
        ctk.CTkLabel(dialog, text=config.text(label_key)).grid(
            row=row, column=0, sticky="w", padx=12, pady=8
        )
        entry = ctk.CTkEntry(dialog, width=280)
        current = getattr(config.paths, field)
        if current:
            entry.insert(0, str(current))
        entry.grid(row=row, column=1, sticky="ew", padx=6, pady=8)
        entries[field] = entry

        def browse() -> None:
            path = (
                filedialog.askdirectory(parent=dialog)
                if select_dir
                else filedialog.askopenfilename(parent=dialog)
            )
            if path:
                entry.delete(0, "end")
                entry.insert(0, path)

        ctk.CTkButton(dialog, text=config.text("config.browse"), command=browse).grid(
            row=row, column=2, padx=12, pady=8
        )

    add_path_row(0, "config.executable_path", "swat_executable", select_dir=False)
    add_path_row(1, "config.base_models_root", "base_models_root", select_dir=True)
    add_path_row(2, "config.workspace_root", "workspace_root", select_dir=True)

    ctk.CTkLabel(dialog, text=config.text("config.target_executable_name")).grid(
        row=3, column=0, sticky="w", padx=12, pady=8
    )
    exe_name_entry = ctk.CTkEntry(dialog, width=280)
    exe_name_entry.insert(0, config.paths.target_executable_name)
    exe_name_entry.grid(row=3, column=1, sticky="ew", padx=6, pady=8)

    error_label.grid(row=4, column=0, columnspan=3, sticky="w", padx=12)

    def save() -> None:
        swat_executable_text = entries["swat_executable"].get().strip()
        base_models_root_text = entries["base_models_root"].get().strip()
        workspace_root_text = entries["workspace_root"].get().strip()

        if not swat_executable_text or not base_models_root_text or not workspace_root_text:
            error_label.configure(text=config.text("config.error.missing_path"))
            return

        swat_executable = Path(swat_executable_text)
        base_models_root = Path(base_models_root_text)
        workspace_root = Path(workspace_root_text)

        error_key = validate_app_paths(swat_executable, base_models_root, workspace_root)
        if error_key is not None:
            error_label.configure(text=config.text(error_key))
            return

        config.save_paths(
            AppPaths(
                swat_executable=swat_executable,
                base_models_root=base_models_root,
                workspace_root=workspace_root,
                target_executable_name=exe_name_entry.get().strip() or "swatUser.exe",
            )
        )
        dialog.destroy()
        on_saved()

    save_button = ctk.CTkButton(dialog, text=config.text("config.save"), command=save)
    save_button.grid(row=5, column=0, columnspan=3, pady=16)
    dialog.grid_columnconfigure(1, weight=1)

    dialog.entries = entries
    dialog.error_label = error_label
    dialog.save_button = save_button
    return dialog
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda activate swat && pytest tests/ui/test_config_dialog.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add ui/config_dialog.py tests/ui/test_config_dialog.py
git commit -m "feat: add path configuration dialog gating app startup"
```

---

## Task 14: Initial window — `ui/initial_window.py`

**Files:**
- Create: `ui/initial_window.py`
- Test: `tests/ui/test_initial_window.py`

**Note:** needs a local display.

**Interfaces:**
- Consumes: `config.settings.ConfigManager`, `swat_io.discovery.discover_base_models` (Task 3), `scenarios.project.open_or_create_project` (Task 6), `scenarios.models.Project`, `ui.dialogs.ask_choice`.
- Produces: `ui.initial_window.InitialWindowFrame(master, config: ConfigManager, on_project_selected: Callable[[Project], None])` — a `ctk.CTkFrame`. Centered layout: app title, `project.open_or_create` button, read-only path display defaulting to `project.no_selection`. Clicking the button asks (via `ask_choice`) whether to create a new project or open an existing one, then either lists `discover_base_models(config.paths.base_models_root)` watersheds to pick from, or opens a directory browser rooted at `config.paths.workspace_root`.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from config.settings import ConfigManager
from swat_io.discovery import BaseModelInfo
from tests.helpers import make_synthetic_txtinout
from ui.initial_window import InitialWindowFrame


def _make_config(tmp_path: Path) -> ConfigManager:
    resources_dir = Path(__file__).resolve().parents[2] / "resources"
    config = ConfigManager(resources_dir=resources_dir, config_file=tmp_path / "config.json")
    config.load_all()
    config.paths.base_models_root = tmp_path / "models"
    config.paths.workspace_root = tmp_path / "workspace"
    make_synthetic_txtinout(tmp_path / "models" / "Buffalo" / "Buffalo_calibrated_annual", {1: {}})
    (tmp_path / "workspace").mkdir()
    return config


def test_initial_window_shows_no_selection_placeholder(hidden_root, tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    frame = InitialWindowFrame(hidden_root, config, on_project_selected=lambda project: None)

    assert frame.path_entry.get() == config.text("project.no_selection")


def test_initial_window_create_flow_invokes_callback(hidden_root, tmp_path: Path, monkeypatch) -> None:
    config = _make_config(tmp_path)
    selected = []

    monkeypatch.setattr(
        "ui.initial_window.ask_choice",
        lambda parent, title, options, confirm_text, cancel_text: options[0],
    )

    frame = InitialWindowFrame(hidden_root, config, on_project_selected=lambda project: selected.append(project))
    frame._create_project()

    assert len(selected) == 1
    assert selected[0].watershed == "Buffalo"
    assert frame.path_entry.get() == str(selected[0].project_dir)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda activate swat && pytest tests/ui/test_initial_window.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui.initial_window'`

- [ ] **Step 3: Implement ui/initial_window.py**

```python
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog
from typing import Callable

import customtkinter as ctk

from config.settings import ConfigManager
from scenarios.models import Project
from scenarios.project import open_or_create_project
from swat_io.discovery import discover_base_models
from ui.dialogs import ask_choice


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
            container, text=config.text("project.open_or_create"), command=self._open_or_create
        ).pack()

        self.path_entry = ctk.CTkEntry(container, width=320)
        self.path_entry.pack(pady=(20, 0))
        self._set_path_display(config.text("project.no_selection"))

    def _set_path_display(self, text: str) -> None:
        self.path_entry.configure(state="normal")
        self.path_entry.delete(0, "end")
        self.path_entry.insert(0, text)
        self.path_entry.configure(state="disabled")

    def _open_or_create(self) -> None:
        action = ask_choice(
            self,
            self.config.text("project.open_or_create"),
            [self.config.text("project.action.create"), self.config.text("project.action.open")],
            self.config.text("action.confirm"),
            self.config.text("action.cancel"),
        )
        if action == self.config.text("project.action.create"):
            self._create_project()
        elif action == self.config.text("project.action.open"):
            self._open_existing_project()

    def _create_project(self) -> None:
        models = discover_base_models(self.config.paths.base_models_root)
        if not models:
            self._set_path_display(self.config.text("scenario.error.parse_failed"))
            return
        watershed = ask_choice(
            self,
            self.config.text("watershed.select"),
            [m.watershed for m in models],
            self.config.text("action.confirm"),
            self.config.text("action.cancel"),
        )
        if watershed is None:
            return
        match = next(m for m in models if m.watershed == watershed)
        project = open_or_create_project(
            self.config.paths.workspace_root, match.watershed, match.model_dir, match.txtinout_dir
        )
        self._set_path_display(str(project.project_dir))
        self.on_project_selected(project)

    def _open_existing_project(self) -> None:
        directory = filedialog.askdirectory(
            parent=self, initialdir=str(self.config.paths.workspace_root)
        )
        if not directory:
            return
        project_dir = Path(directory)
        watershed = project_dir.name
        models = discover_base_models(self.config.paths.base_models_root)
        match = next((m for m in models if m.watershed == watershed), None)
        if match is None:
            self._set_path_display(self.config.text("scenario.error.parse_failed"))
            return
        project = Project(
            watershed=watershed,
            base_model_dir=match.model_dir,
            base_txtinout_dir=match.txtinout_dir,
            project_dir=project_dir,
        )
        self._set_path_display(str(project.project_dir))
        self.on_project_selected(project)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda activate swat && pytest tests/ui/test_initial_window.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add ui/initial_window.py tests/ui/test_initial_window.py
git commit -m "feat: add centered initial window with open/create project flow"
```

---

## Task 15: Parametrización view — `ui/parametrizacion_view.py`

**Files:**
- Create: `ui/parametrizacion_view.py`
- Test: `tests/ui/test_parametrizacion_view.py`

**Note:** needs a local display.

**Interfaces:**
- Consumes: `scenarios.draft.*` (Task 8), `ui.form_builder.build_wetland_form` (Task 12), `ConfigManager.load_layout`/`text`.
- Produces: `ui.parametrizacion_view.ParametrizacionView(master, config: ConfigManager, project: Project, scenario_name: str)` — a `ctk.CTkFrame`. Initializes the draft (via `init_draft` if it doesn't exist yet), renders the count badge + subbasin list (left) + the field form for the selected subbasin (right, via `build_wetland_form`), and an "Importar CSV" button that calls `import_draft_csv`.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from config.settings import ConfigManager
from scenarios.draft import read_draft
from scenarios.models import Project
from tests.helpers import make_synthetic_txtinout
from ui.parametrizacion_view import ParametrizacionView


def _make_project_and_config(tmp_path: Path) -> tuple[Project, ConfigManager]:
    resources_dir = Path(__file__).resolve().parents[2] / "resources"
    config = ConfigManager(resources_dir=resources_dir, config_file=tmp_path / "config.json")
    config.load_all()

    base_dir = tmp_path / "base" / "Buffalo_calibrated_annual"
    txtinout_dir = make_synthetic_txtinout(base_dir, {1: {"WET_FR": 0.2}, 2: {"WET_FR": 0.0}})
    project_dir = tmp_path / "workspace" / "Buffalo"
    project_dir.mkdir(parents=True)
    project = Project(
        watershed="Buffalo", base_model_dir=base_dir, base_txtinout_dir=txtinout_dir, project_dir=project_dir
    )
    return project, config


def test_parametrizacion_view_initializes_draft_and_shows_count(hidden_root, tmp_path: Path) -> None:
    project, config = _make_project_and_config(tmp_path)

    view = ParametrizacionView(hidden_root, config, project, "Buffalo_WET_MS_annual")

    assert view.draft_path.exists()
    assert "1" in view.count_label.cget("text")
    assert "2" in view.count_label.cget("text")


def test_parametrizacion_view_field_commit_persists_to_csv(hidden_root, tmp_path: Path) -> None:
    project, config = _make_project_and_config(tmp_path)
    view = ParametrizacionView(hidden_root, config, project, "Buffalo_WET_MS_annual")
    view._select_row(1)

    view._on_field_commit("wet_fr", 0.8)

    assert read_draft(view.draft_path).loc[1, "wet_fr"] == 0.8


def test_parametrizacion_view_field_error_does_not_touch_csv(hidden_root, tmp_path: Path) -> None:
    project, config = _make_project_and_config(tmp_path)
    view = ParametrizacionView(hidden_root, config, project, "Buffalo_WET_MS_annual")
    view._select_row(1)

    view._on_field_error("wet_fr", "'x' no es un número válido.")

    assert read_draft(view.draft_path).loc[1, "wet_fr"] == 0.2
    assert view.error_label.cget("text") != ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda activate swat && pytest tests/ui/test_parametrizacion_view.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui.parametrizacion_view'`

- [ ] **Step 3: Implement ui/parametrizacion_view.py**

```python
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from config.settings import ConfigManager
from scenarios.draft import draft_csv_path, import_draft_csv, init_draft, read_draft, update_draft_value
from scenarios.models import Project
from ui.form_builder import build_wetland_form


class ParametrizacionView(ctk.CTkFrame):
    def __init__(self, master, config: ConfigManager, project: Project, scenario_name: str) -> None:
        super().__init__(master)
        self.config = config
        self.project = project
        self.scenario_name = scenario_name
        self.layout_def = config.load_layout("wetland_pond")

        self.draft_path = draft_csv_path(project, scenario_name)
        if not self.draft_path.exists():
            init_draft(project, scenario_name)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda activate swat && pytest tests/ui/test_parametrizacion_view.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add ui/parametrizacion_view.py tests/ui/test_parametrizacion_view.py
git commit -m "feat: add Parametrización master-detail view with CSV import"
```

---

## Task 16: Project window — `ui/project_window.py`

**Files:**
- Create: `ui/project_window.py`
- Test: `tests/ui/test_project_window.py`

**Note:** needs a local display.

**Interfaces:**
- Consumes: `scenarios.models.{Project, WETLAND_ABBREVIATIONS, build_scenario_name}`, `scenarios.draft.draft_csv_path`, `engine.configure.configure_scenario`, `ui.dialogs.{ask_choice, ask_text}`, `ui.parametrizacion_view.ParametrizacionView`.
- Produces: `ui.project_window.ProjectWindowFrame(master, config: ConfigManager, project: Project)` — a `ctk.CTkFrame` with the header (watershed + active scenario name), a 2-button toolbar (`Parametrización`, disabled `Configurar escenario` until a scenario exists), and a content area that swaps in `ParametrizacionView`.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from config.settings import ConfigManager
from engine.configure import configure_scenario
from scenarios.models import Project
from tests.helpers import make_synthetic_txtinout
from ui.project_window import ProjectWindowFrame


def _make_project_and_config(tmp_path: Path) -> tuple[Project, ConfigManager]:
    resources_dir = Path(__file__).resolve().parents[2] / "resources"
    config = ConfigManager(resources_dir=resources_dir, config_file=tmp_path / "config.json")
    config.load_all()
    config.paths.swat_executable = tmp_path / "swat2012.exe"
    config.paths.swat_executable.write_text("fake binary")
    config.paths.target_executable_name = "swatUser.exe"

    base_dir = tmp_path / "base" / "Buffalo_calibrated_annual"
    txtinout_dir = make_synthetic_txtinout(base_dir, {1: {"WET_FR": 0.2}})
    project_dir = tmp_path / "workspace" / "Buffalo"
    project_dir.mkdir(parents=True)
    project = Project(
        watershed="Buffalo", base_model_dir=base_dir, base_txtinout_dir=txtinout_dir, project_dir=project_dir
    )
    return project, config


def test_project_window_starts_with_configure_disabled(hidden_root, tmp_path: Path) -> None:
    project, config = _make_project_and_config(tmp_path)
    frame = ProjectWindowFrame(hidden_root, config, project)

    assert frame.configure_button.cget("state") == "disabled"


def test_project_window_setting_a_scenario_enables_configure_and_shows_form(hidden_root, tmp_path: Path) -> None:
    project, config = _make_project_and_config(tmp_path)
    frame = ProjectWindowFrame(hidden_root, config, project)

    frame._activate_scenario("Buffalo_WET_MS_annual")

    assert frame.configure_button.cget("state") == "normal"
    assert frame.scenario_label.cget("text") == "Buffalo_WET_MS_annual"
    assert len(frame.content.winfo_children()) == 1


def test_project_window_configure_scenario_materializes_and_disables_button(hidden_root, tmp_path: Path) -> None:
    project, config = _make_project_and_config(tmp_path)
    frame = ProjectWindowFrame(hidden_root, config, project)
    frame._activate_scenario("Buffalo_WET_MS_annual")

    frame._configure_scenario()

    assert (project.project_dir / "Buffalo_WET_MS_annual" / "TxtInOut" / "swatUser.exe").exists()
    assert frame.configure_button.cget("state") == "disabled"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda activate swat && pytest tests/ui/test_project_window.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui.project_window'`

- [ ] **Step 3: Implement ui/project_window.py**

```python
from __future__ import annotations

import customtkinter as ctk

from config.settings import ConfigManager
from engine.configure import configure_scenario
from scenarios.draft import draft_csv_path
from scenarios.models import WETLAND_ABBREVIATIONS, Project, build_scenario_name
from ui.dialogs import ask_choice, ask_text
from ui.parametrizacion_view import ParametrizacionView


class ProjectWindowFrame(ctk.CTkFrame):
    def __init__(self, master, config: ConfigManager, project: Project) -> None:
        super().__init__(master)
        self.config = config
        self.project = project
        self.active_scenario_name: str | None = None

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=12)
        ctk.CTkLabel(header, text=project.watershed).pack(anchor="w")
        self.scenario_label = ctk.CTkLabel(header, text=config.text("project.no_scenario"))
        self.scenario_label.pack(anchor="w")

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=12)
        ctk.CTkButton(
            toolbar, text=config.text("wetland.form.title"), command=self._open_parametrizacion
        ).pack(side="left", padx=(0, 8))
        self.configure_button = ctk.CTkButton(
            toolbar, text=config.text("action.configure_scenario"),
            command=self._configure_scenario, state="disabled",
        )
        self.configure_button.pack(side="left")

        self.status_label = ctk.CTkLabel(self, text="")
        self.status_label.pack(fill="x", padx=12, pady=(8, 0))

        self.content = ctk.CTkFrame(self)
        self.content.pack(fill="both", expand=True, padx=12, pady=12)

    def _open_parametrizacion(self) -> None:
        name = self.active_scenario_name or self._prompt_scenario_name()
        if name is None:
            return
        self._activate_scenario(name)

    def _activate_scenario(self, name: str) -> None:
        self.active_scenario_name = name
        self.scenario_label.configure(text=name)
        self.configure_button.configure(state="normal")
        for child in self.content.winfo_children():
            child.destroy()
        view = ParametrizacionView(self.content, self.config, self.project, name)
        view.pack(fill="both", expand=True)

    def _prompt_scenario_name(self) -> str | None:
        abbreviation = ask_choice(
            self, self.config.text("scenario.abbreviation"), list(WETLAND_ABBREVIATIONS),
            self.config.text("action.confirm"), self.config.text("action.cancel"),
        )
        if abbreviation is None:
            return None
        timestep = ask_text(
            self, self.config.text("scenario.timestep"),
            self.config.text("action.confirm"), self.config.text("action.cancel"), default="annual",
        )
        if not timestep:
            return None
        try:
            name = build_scenario_name(self.project.watershed, abbreviation, timestep)
        except ValueError as exc:
            self.status_label.configure(text=str(exc))
            return None
        already_exists = draft_csv_path(self.project, name).exists() or (self.project.project_dir / name).exists()
        if already_exists:
            self.status_label.configure(text=self.config.text("scenario.error.duplicate_name"))
            return None
        return name

    def _configure_scenario(self) -> None:
        if self.active_scenario_name is None:
            return
        try:
            result = configure_scenario(
                self.project, self.active_scenario_name,
                self.config.paths.swat_executable, self.config.paths.target_executable_name,
            )
        except (FileNotFoundError, FileExistsError) as exc:
            self.status_label.configure(text=str(exc))
            return
        self.status_label.configure(text=str(result.scenario_dir))
        self.configure_button.configure(state="disabled")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda activate swat && pytest tests/ui/test_project_window.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add ui/project_window.py tests/ui/test_project_window.py
git commit -m "feat: add project window toolbar wiring Parametrización and Configurar escenario"
```

---

## Task 17: App entry point — `ui/app.py`

**Files:**
- Create: `ui/app.py`
- Create: `main.py` (project root)
- Test: `tests/ui/test_app.py`

**Note:** needs a local display. This task also includes a manual run-through — automated tests only cover construction/wiring, not a full mainloop.

**Interfaces:**
- Consumes: everything from Tasks 4, 13, 14, 16.
- Produces: `ui.app.App` (a `ctk.CTk` subclass) and `main()` in `main.py` that runs it.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from config.settings import AppPaths
from ui.app import App


def test_app_shows_config_dialog_when_paths_incomplete(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("config.settings.DEFAULT_CONFIG_FILE", tmp_path / "config.json")
    opened = []
    monkeypatch.setattr(
        "ui.app.show_config_dialog",
        lambda parent, config, on_saved: opened.append(True),
    )

    app = App()
    try:
        assert opened == [True]
    finally:
        app.destroy()


def test_app_shows_initial_window_when_paths_already_complete(tmp_path: Path, monkeypatch) -> None:
    exe = tmp_path / "swat2012.exe"
    exe.write_text("fake binary")
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    monkeypatch.setattr("config.settings.DEFAULT_CONFIG_FILE", tmp_path / "config.json")

    from config.settings import ConfigManager

    seed = ConfigManager(config_file=tmp_path / "config.json")
    seed.save_paths(
        AppPaths(swat_executable=exe, base_models_root=models_dir, workspace_root=workspace_dir)
    )

    app = App()
    try:
        assert app._current_frame is not None
        assert app._current_frame.__class__.__name__ == "InitialWindowFrame"
    finally:
        app.destroy()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda activate swat && pytest tests/ui/test_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui.app'`

- [ ] **Step 3: Implement ui/app.py**

```python
from __future__ import annotations

import customtkinter as ctk

from config.settings import ConfigManager
from scenarios.models import Project
from ui.config_dialog import show_config_dialog
from ui.initial_window import InitialWindowFrame
from ui.project_window import ProjectWindowFrame


class App(ctk.CTk):
    def __init__(self) -> None:
        self.config_manager = ConfigManager()
        self.config_manager.load_all()
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme(str(self.config_manager.theme_path()))

        super().__init__()
        self.title(self.config_manager.text("app.title"))
        self.geometry("900x600")
        self._current_frame: ctk.CTkFrame | None = None

        if not self.config_manager.paths.is_complete():
            self.withdraw()
            show_config_dialog(self, self.config_manager, on_saved=self._start)
        else:
            self._start()

    def _start(self) -> None:
        self.deiconify()
        self.show_initial_window()

    def _set_frame(self, frame: ctk.CTkFrame) -> None:
        if self._current_frame is not None:
            self._current_frame.destroy()
        self._current_frame = frame
        frame.pack(fill="both", expand=True)

    def show_initial_window(self) -> None:
        self._set_frame(
            InitialWindowFrame(self, self.config_manager, on_project_selected=self.show_project_window)
        )

    def show_project_window(self, project: Project) -> None:
        self._set_frame(ProjectWindowFrame(self, self.config_manager, project))
```

- [ ] **Step 4: Write main.py**

```python
from __future__ import annotations

from ui.app import App


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `conda activate swat && pytest tests/ui/test_app.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Manual verification**

Run: `conda activate swat && python main.py`
Expected: the config dialog appears if `~/.swat_wetlands/config.json` is missing/incomplete; after saving valid paths (or if already configured), the centered initial window appears. Click "Abrir o crear proyecto" → "Crear proyecto nuevo" → pick a watershed → the project window appears with "Parametrización" and a disabled "Configurar escenario". Click "Parametrización", name a scenario, confirm the subbasin list + form appear and edits update the count badge live. Click "Configurar escenario" and confirm a new folder appears under the configured workspace root containing `TxtInOut/` with the renamed executable.

- [ ] **Step 7: Commit**

```bash
git add ui/app.py main.py tests/ui/test_app.py
git commit -m "feat: wire App entry point (config gate -> initial window -> project window)"
```

---

## Self-Review Notes

- **Spec coverage:** ventana inicial → Task 14; barra de herramientas del proyecto → Task 16; vista de Parametrización (lista+formulario, contador, importar CSV, guardado on-blur) → Tasks 12, 15; ciclo de vida del borrador CSV → Task 8; "Configurar escenario" (copiar + aplicar `.pnd` + colocar ejecutable, sin invocar el subproceso) → Task 9, wired in Task 16. The path-configuration screen (Task 13) wasn't an explicit section of the design doc but is a hard CLAUDE.md requirement the initial window depends on to function at all — included as necessary prerequisite plumbing, not a new UX decision.
- **Type consistency checked:** `Project` fields (`watershed`, `base_model_dir`, `base_txtinout_dir`, `project_dir`) match across Tasks 5, 6, 8, 9, 14, 15, 16. Draft field ids (`wet_fr`, `wet_nsa`, `wet_nvol`, `wet_mxsa`, `wet_mxvol`, `wet_vol`, `wet_k`) match between `wetland_pond.yaml`, Task 2's `_FIELD_TO_CODE`, Task 8's `_SUMMARY_TO_FIELD` values, and Task 15's usage.
- **No placeholders:** every step has complete code; no TODOs.
