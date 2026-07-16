# Diseño: panel de escenarios de referencia y ventana de Wetlands

Fecha: 2026-07-16
Estado: aprobado por el usuario, pendiente de plan de implementación

**Este documento reemplaza** `2026-07-15-ventana-inicial-parametrizacion-design.md`
en todo lo referente al flujo de apertura de proyecto y a la vista de
parametrización. El usuario probó la primera implementación y la consideró
deficiente; este diseño recoge el flujo corregido. Ver `CLAUDE.md` en la
raíz del proyecto para las restricciones técnicas no negociables.

## Vocabulario

- **Proyecto**: una carpeta cualquiera del disco elegida por el usuario
  (ej. `03-Models\Buffalo`) que contiene una o más subcarpetas de
  escenario. Ya no está atada a una cuenca específica ni a
  `workspace_root`; es simplemente `project_dir: Path`.
- **Escenario de referencia**: una subcarpeta de `project_dir` (ej.
  `Buffalo_calibrated_annual`, `Buffalo_GI_annual`) con la estructura
  `TablesIn/`, `TablesOut/`, `TxtInOut/` de SWAT. Es de solo lectura
  siempre — calibrado o no, da igual: la app nunca escribe sobre ella.
- **Escenario de trabajo**: la copia nueva que la app crea a partir de un
  escenario de referencia, con el nombre que el usuario define
  (`{Watershed}_{Abbrev}_{timestep}`, convención de CLAUDE.md). Todas las
  ediciones ocurren exclusivamente aquí.
- **Borrador (CSV)**: estado editable del escenario de trabajo, sembrado al
  cargar desde los `.pnd` de la copia recién creada. Vive en
  `project_dir/_borradores/{scenario_name}.csv`.

## 1. Flujo de navegación general

```
Ventana inicial
   └─ [Abrir proyecto] → selecciona una carpeta contenedora de escenarios
         └─ Ventana de proyecto
                ├─ Panel derecho: lista de escenarios de referencia (checks)
                ├─ Botón "Cargar" (bajo el panel) → nombra y crea el escenario de trabajo
                └─ Toolbar "Parametrización" → menú → "Wetlands" → ventana de tabla
```

No existe más la distinción crear/abrir proyecto ni la selección de cuenca
en este paso — se elige cualquier carpeta del sistema de archivos. Tampoco
existe ya un botón de "Configurar escenario"/ejecutar: colocar el
ejecutable y correr `swat2012.exe` quedan fuera de alcance de este
diseño.

## 2. Ventana inicial

- Un solo botón: **"Abrir proyecto"**. Abre el explorador de carpetas
  nativo del sistema operativo (`askdirectory`), sin restringir la carpeta
  inicial a `workspace_root` más que como sugerencia de directorio de
  partida.
- Debajo, un campo de solo lectura con la ruta seleccionada (placeholder
  "Ningún proyecto seleccionado").
- Al seleccionar una carpeta válida, la app navega a la ventana de
  proyecto con `Project(project_dir=<carpeta elegida>)`.
- Sin lista de proyectos recientes, sin validación de contenido en este
  paso (la validación de qué subcarpetas son escenarios válidos ocurre ya
  en la ventana de proyecto).

## 3. Ventana de proyecto

### 3.1 Panel derecho — escenarios de referencia

- Al entrar a la ventana, se listan de inmediato las subcarpetas directas
  de `project_dir` que contienen un `TxtInOut/` con al menos un archivo
  `.sub` válido (mismo criterio de `discover_subbasins`/`_SUB_FILENAME`
  aplicado a nivel de carpeta). Carpetas sin esa estructura no aparecen.
- Cada entrada se muestra con un control de selección única (`CTkRadioButton`
  compartiendo una variable) — visualmente son "checks", pero solo uno
  puede estar marcado a la vez. No se excluyen ni se marcan de forma
  especial las carpetas `*_calibrated_*`: son una opción más.
- Debajo del panel, botón **"Cargar"**, deshabilitado hasta que haya un
  escenario de referencia marcado.

### 3.2 Acción "Cargar"

Al presionar "Cargar" con un escenario de referencia marcado:

1. Se pide el nombre del nuevo escenario de trabajo (abreviación
   `WET_LS`/`WET_MS`/`WET_HS` + periodo, vía `build_scenario_name` ya
   existente). Si el nombre ya existe como carpeta o borrador, se rechaza
   con el mensaje de error ya definido (`scenario.error.duplicate_name`).
2. Se copia **la carpeta de referencia completa** (`TablesIn/`,
   `TablesOut/`, `TxtInOut/`, y cualquier otro contenido a ese nivel) a
   `project_dir/{scenario_name}/`. El escenario de referencia no se toca
   en ningún momento.
3. Se leen los `.pnd` de `project_dir/{scenario_name}/TxtInOut/` (vía
   `summarize_project`) para sembrar el borrador CSV en
   `project_dir/_borradores/{scenario_name}.csv` — este es el CSV que
   luego se puede reimportar en la ventana de Wetlands.
4. El panel derecho se bloquea (los radio buttons y el botón "Cargar" se
   deshabilitan): ya no se puede cambiar de escenario de referencia para
   este escenario de trabajo.
5. Se habilita el botón "Parametrización" del toolbar y se actualiza el
   encabezado con el nombre del escenario de trabajo activo.

### 3.3 Toolbar — "Parametrización"

- Botón deshabilitado hasta completar el paso 3.2. Al hacer clic despliega
  un menú desplegable; única entrada por ahora: **"Wetlands"**.
- Seleccionar "Wetlands" abre una ventana `Toplevel` independiente con la
  tabla de parámetros (sección 4). No es modal: el usuario puede volver a
  la ventana de proyecto sin cerrarla, pero no hay otra acción disponible
  ahí mientras tanto.

## 4. Ventana Wetlands

Reutiliza el layout de lista + formulario ya validado (panel de
subcuencas a la izquierda, formulario de campos a la derecha), pero ahora
vive en su propia ventana en vez de un panel embebido, y agrega una barra
de acciones.

- **Arriba a la derecha**: botón **"Cargar CSV"** — importa un CSV
  (mismo mecanismo de `import_draft_csv`: valida todas las filas y
  columnas contra `wetland_pond.yaml` antes de aplicar nada; si falla,
  rechazo completo con mensaje de fila/columna/valor). Reemplaza el
  borrador en memoria y en disco.
- **Lista + formulario**: igual que el diseño anterior — panel izquierdo
  con indicador de humedal activo por subcuenca, formulario derecho con
  los 7 campos de `wetland_pond.yaml`. Editar un campo (blur/Enter) valida
  contra el rango declarado y, si es válido, escribe de inmediato en el
  CSV borrador del escenario (comportamiento sin cambios respecto al
  diseño anterior).
- **Abajo a la derecha**: botones **"Guardar"** y **"Cancelar"**.
  - **"Guardar"**: toma el borrador CSV actual y escribe cada fila en el
    `.pnd` correspondiente de `project_dir/{scenario_name}/TxtInOut/` (la
    copia de trabajo, nunca la referencia). Puede presionarse varias
    veces; cada clic vuelve a aplicar el estado actual del borrador.
  - **"Cancelar"**: cierra la ventana sin escribir en los `.pnd`. El CSV
    borrador en disco puede haber quedado con las ediciones de campo ya
    hechas (esas sí se guardan al vuelo), pero el modelo real de la copia
    no se modifica hasta un "Guardar" posterior.

## 5. Cambios de arquitectura respecto al código actual

- `scenarios/models.py::Project` se reduce a `project_dir: Path`
  (se elimina `watershed`, `base_model_dir`, `base_txtinout_dir` como
  campos fijos del proyecto).
- Nueva función de descubrimiento (`swat_io/discovery.py` o similar):
  lista subcarpetas directas de `project_dir` con `TxtInOut/` válido, sin
  filtrar por convención de nombre.
- Nueva función de copia de carpeta completa (no solo `TxtInOut`) al
  confirmar el nombre del escenario de trabajo — vive en `engine/` junto a
  la materialización existente.
- `scenarios/draft.py` se mantiene casi intacto (`init_draft`, `read_draft`,
  `update_draft_value`, `import_draft_csv`), pero `init_draft` pasa a
  recibir explícitamente la ruta de la copia de trabajo en vez de derivarla
  de `Project.base_txtinout_dir`.
- `engine/configure.py::configure_scenario` se reduce a "aplicar borrador →
  `.pnd` reales de la copia" (lo que ejecuta "Guardar"). Se elimina de ahí
  la copia de `TxtInOut` (ya ocurre en "Cargar", sección 3.2) y se elimina
  por completo la colocación del ejecutable renombrado.
- `ui/initial_window.py`: un solo botón, sin diálogo de elección
  crear/abrir.
- `ui/project_window.py`: agrega el panel derecho de escenarios de
  referencia, el botón "Cargar" con su flujo de nombrado+copia+bloqueo, y
  el menú desplegable "Parametrización → Wetlands" en vez del botón
  "Configurar escenario".
- `ui/parametrizacion_view.py` pasa de ser un frame embebido a una ventana
  `Toplevel`, y agrega la barra de acciones "Cargar CSV" / "Guardar" /
  "Cancelar".

## 6. Manejo de errores

- Nombre de escenario duplicado al presionar "Cargar": mismo mensaje que
  hoy (`scenario.error.duplicate_name`), no se copia nada.
- Falla al copiar la carpeta de referencia (permisos, disco lleno, etc.):
  mensaje distinto y explícito de error de copia — no se deja el panel en
  estado "cargado" ni se genera el borrador.
- Importación de CSV inválida en Wetlands: rechazo completo (all-or-nothing)
  con fila/columna/valor señalados, sin aplicar nada — igual que hoy.
- "Guardar" que falla al escribir algún `.pnd` (ej. archivo bloqueado):
  se distingue explícitamente del error de validación, y se informa qué
  subcuenca falló sin dejar el resto a medio escribir de forma silenciosa.

## Fuera de alcance de este diseño

- Botón "Ejecutar" y colocación del ejecutable `swatUser.exe`.
- Vista de comparación línea base vs. escenario (`viz/`).
- Panel de proyectos recientes en la ventana inicial.
- Más entradas en el menú "Parametrización" además de "Wetlands".
- Edición o comparación simultánea de múltiples escenarios de trabajo.
- Bloqueo/lock de "Guardar" tras el primer uso (se permite repetir).
