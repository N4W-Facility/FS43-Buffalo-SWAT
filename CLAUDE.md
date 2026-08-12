# CLAUDE.md

## Reglas de colaboración obligatorias (no negociables)

- **Cero código sin autorización explícita**: el asistente no debe escribir
  ni una sola línea de código (ni crear/editar archivos de código) sin que
  el usuario lo autorice explícitamente para esa tarea puntual. Discutir,
  proponer y diseñar sí; implementar no, hasta recibir luz verde.
- **Optimizar uso de tokens**: respuestas breves y directas, sin exploración
  de archivos ni tool calls innecesarios, sin resúmenes largos ni
  reexplicar contexto ya conocido.

## Resumen del proyecto

Aplicación de escritorio en Python (CustomTkinter sobre Tkinter) para
configurar, ejecutar y visualizar **escenarios de degradación o mejora de
humedales** sobre un modelo hidrológico SWAT ya calibrado y validado.

La app es una capa de orquestación alrededor de un motor de cómputo externo
(`swat2012.exe`): no simula, no recalibra, no reimplementa hidrología. Su
trabajo es tres cosas:

1. Permitir al usuario definir un escenario modificando parámetros de
   humedal sobre una copia aislada de la configuración base.
2. Ejecutar `swat2012.exe` como subproceso local sobre esa copia.
3. Leer las salidas del modelo y visualizar la comparación entre el
   escenario modificado y la línea base (caudal, sedimento, nutrientes).

El valor del producto está en la usabilidad de la orquestación y la calidad
de la visualización comparativa, no en el cómputo hidrológico en sí.

## Estado actual de la implementación

La interfaz (`ui/`) fue reconstruida desde cero (agosto 2026) y `main.py`
arranca una app funcional de siete pestañas. Dependencias nuevas (env conda
`swat`): **matplotlib**, usada por `viz/land_use_chart.py`, `viz/rch_chart.py`
y `viz/shapefile_map.py`, sin `pyplot` (se construye `Figure` directo y se
embebe con `FigureCanvasTkAgg`, para no arrastrar el estado global de
pyplot en una app de escritorio); **pyshp** (`shapefile`), usada solo por
`viz/shapefile_reader.py` para leer los `.shp` de subcuencas/reach del
mapa de la pestaña Results — sin GDAL/Fiona (decisión explícita del
usuario, 2026-08-03: instalación más liviana en Windows que geopandas para
el único uso que necesita, dibujar polígonos/polilíneas estáticos); y
**sqlite3** (librería estándar, cero instalación nueva) usada por
`swat_io/hru_output_parser.py` como destino de la pestaña HRU Results en
vez de CSV — ver esa pestaña más abajo.

- **`ui/app.py`**: ventana raíz, tema `resources/theme/swat_light.json`,
  `TabBar` propia (`ui/tabs.py`, no `CTkTabview`) con soporte de
  pestañas deshabilitadas hasta que haya un proyecto abierto. La barra en
  sí es una `CTkScrollableFrame` horizontal (no un `CTkFrame` con
  `pack(side="left")` plano): desde seis pestañas el ancho requerido por
  los botones ya no entra en una ventana de pantalla chica (ahora diez,
  con Results (.sub), HRU Results, Batch Scenarios y NbS), y sin scroll las
  últimas pestañas quedaban fuera del área visible sin forma de
  alcanzarlas (bug real, detectado 2026-08-03 al agregar la pestaña
  Results — ver más abajo). `_WINDOW_SIZE` en `ui/app.py` sigue en
  `980x800` a propósito (amigable con pantallas chicas): la barra scrollea
  su propio contenido en vez de depender de agrandar la ventana para que
  quepan más pestañas a futuro.
- **Pestaña Project** (`ui/tab_project.py`): abrir/cambiar carpeta de
  proyecto (cualquier carpeta con `TxtInOut/` directo — hoy la app **no
  distingue** entre modelo de referencia calibrado y copia de escenario,
  ver aviso de aislamiento más abajo), editar metadata (`project.json`).
  También aloja, en una tarjeta aparte ("Shapefiles"), las rutas a los
  `.shp` de subcuencas y reach que usa el mapa de la pestaña Results
  (`ProjectMetadata.subbasin_shp_path` / `.reach_shp_path`, nuevos campos
  en `project.json` — a diferencia del ejecutable SWAT en
  `config.settings.AppPaths`, una ruta por máquina, estas son por
  proyecto/cuenca). Mismo patrón campo de solo lectura + botón "Browse..."
  que la ruta del ejecutable en Run, validado con
  `scenarios.project.validate_shapefile_path` (solo existencia + extensión
  `.shp`; pyshp resuelve `.dbf`/`.shx` junto a él).
- **Pestaña Summary** (`ui/tab_summary.py`): corre en hilo de fondo
  (patrón obligatorio de la sección siguiente) los resúmenes de wetlands
  (`swat_io.summary.summarize_project`) y HRU/land-use
  (`generar_resumen_coberturas.build_land_use_summary`), cachea resultados
  en `project.json`, y agrega un tercer bloque "Gráficas": barra de
  coberturas por subcuenca (o total de cuenca) con selector, construida
  sobre `land_use_by_subbasin.csv`.
- **Pestaña Wetlands (.pnd)** (`ui/tab_wetlands.py` + `ui/wetland_editor_window.py`):
  tabla de solo lectura (`ttk.Treeview`, no CTk — necesario para scroll
  nativo en ambos ejes con muchas subcuencas) con los 20 parámetros de
  "Wetland inputs" como filas y las subcuencas como columnas, leída en
  vivo de los `.pnd` reales. El encabezado de cada columna abre
  `WetlandEditorWindow` preseleccionada en esa subcuenca: campos de solo
  lectura → botón Edit los habilita → Save pide confirmación (diálogo
  Guardar/Cancelar) antes de escribir. Al guardar escribe **directo sobre
  el `.pnd` real** (vía `swat_io.pnd_parser.write_wetland_params`, todavía
  con los 20 campos) y además reescribe
  `tool_outputs/wetland_params_draft.csv` (`scenarios/wetland_draft.py`)
  como respaldo — ese CSV se reconstruye desde los `.pnd` reales cada vez
  que se abre la ventana, nunca es una segunda fuente de verdad.
  La pestaña Wetlands también soporta modificación masiva: "Load CSV" lee
  un CSV con la misma estructura que `wetland_summary.csv` (columnas con
  sufijo de unidad, ver `swat_io/summary.py`), permite carga parcial
  (subconjunto de subcuencas/parámetros), valida columnas/subcuencas/rangos
  de una sola vez (`scenarios/wetland_import.py`, sin dependencias de UI) y,
  si es válido, puebla un staging **en memoria** (nunca toca ningún
  `.pnd`) mostrado con un marcador `*` sobre la tabla de solo lectura. El
  botón "Materialize to SWAT" es el único paso que escribe de verdad —
  vuelve a llamar a `write_wetland_params` por subcuenca y refresca el
  draft CSV — y pide su propia confirmación por ser irreversible. El
  staging se pierde si se cambia de proyecto o se cierra la app sin
  materializar; deliberadamente no se persiste a disco para no crear una
  segunda fuente de verdad además del draft ya existente.
- **Pestaña HRUs (.hru)** (`ui/tab_hru.py` + `ui/hru_editor_window.py` +
  `scenarios/hru_draft.py`): a diferencia de Wetlands, una subcuenca tiene
  N archivos `.hru` (uno por HRU), no uno solo, así que la tabla está
  acotada a la subcuenca elegida en un selector: filas = HRU, columnas =
  cada parámetro reconocido en esos archivos (`ttk.Treeview`, mismo motivo
  que Wetlands). No hay lista curada de campos ni rangos por parámetro —
  decisión explícita del usuario (2026-07-31): se expone todo lo que
  `swat_io.hru.parser` reconoce en cada `.hru`, en vez de una lista fija
  como los 20 campos de `wetland_params.yaml`. Doble clic sobre el id de
  HRU abre `HRUEditorWindow` (selectores encadenados subcuenca → HRU,
  campos de solo lectura → Edit los habilita → Save pide confirmación).
  Sin rangos declarados, la validación antes de guardar corre
  `HRUFile.validate()` (ya existente en `swat_io/hru/validation.py`, p. ej.
  `HRU_FR` fuera de `[0, 1]`) sobre una copia con los cambios aplicados, y
  bloquea el guardado si hay algún issue de severidad `ERROR`. Al guardar
  escribe **directo sobre el `.hru` real** vía
  `scenarios.hru_draft.write_hru_values`, que deliberadamente no usa
  `swat_io.hru.writer.write_hru_file` (esa función exige un destino
  distinto al origen, pensada para escritura aislada por escenario) sino
  que reescribe el archivo en el mismo lugar — mismo aviso de aislamiento
  que Wetlands, ver más abajo. Como no hay lista curada de parámetros
  (a diferencia de Wetlands, con los 20 campos fijos y documentados de
  `wetland_params.yaml`), el usuario no tiene forma de saber de antemano
  qué columnas/subcuenca/HRU son válidas para armar un CSV de import —
  por eso "Export CSV" (`scenarios.hru_draft.export_hru_table_csv`) vuelca
  la tabla de la subcuenca visible (`subbasin`, `hru`, y cada parámetro
  real) a un CSV con exactamente el formato que espera el import, listo
  para editar y reimportar. No es un respaldo tipo
  `wetland_params_draft.csv` (que se reescribe en cada guardado): es una
  plantilla de referencia bajo demanda, sin estado propio. También soporta
  modificación masiva: "Load CSV" (`scenarios/hru_import.py`) lee un CSV
  indexado por columnas `subbasin`/`hru` (una fila = una HRU, a diferencia
  del CSV de Wetlands que es una fila = una subcuenca) más una columna por
  parámetro; sin lista curada de columnas válidas, solo valida que la
  subcuenca/HRU exista (por nombre de archivo, sin parsear contenido —
  `scenarios.hru_draft.list_subbasin_hru_ids`) y que el valor sea
  numérico — un nombre de parámetro que no existe en esa HRU puntual
  recién se rechaza en Materialize (`HRUFile.set_value` levanta
  `HRUModificationError`, "no se crean parámetros nuevos"). El resultado
  puebla un staging en memoria (`dict[(subbasin_id, hru_id), dict]`)
  marcado con `*` sobre la tabla, igual que Wetlands. Diferencia
  importante de diseño: el Materialize de Wetlands es síncrono (a lo sumo
  una escritura por subcuenca); el de HRUs corre en hilo de fondo
  (`ui.tasks.run_in_background`) y bloquea navegación
  (`App._on_hru_run_state_changed`, mismo mecanismo que el Run de
  Summary) porque un CSV de HRUs puede tocar muchas más filas que uno de
  Wetlands — CLAUDE.md exige hilo de fondo para cualquier operación que
  pueda escalar a "miles de .hru". Cada HRU se escribe todo-o-nada (si un
  parámetro de esa HRU falla, no se escribe ningún cambio de esa HRU,
  pero las demás HRU del lote sí siguen). También soporta edición inline
  de celdas, igual que Wetlands (decisión explícita del usuario,
  2026-08-03): doble clic sobre el id de HRU (columna `#0`) sigue abriendo
  `HRUEditorWindow` (equivalente al botón "Edit in .hru"), pero doble clic
  sobre cualquier otra celda (un parámetro puntual) superpone un `Entry`
  sobre la celda para editar ese valor ahí mismo — sin rango declarado
  (a diferencia de la edición inline de Wetlands, que valida contra
  `wetland_params.yaml`), solo valida que sea numérico, igual que "Load
  CSV". El resultado va al mismo staging en memoria `dict[(subbasin_id,
  hru_id), dict]` marcado con `*`, así que también espera a Materialize
  para escribirse de verdad.

  **Aviso indicativo de suma de HRU_FR** (`scenarios.hru_draft.effective_hru_fr_sum`
  / `subbasin_hru_fr_sum`, `HRU_FR_TARGET_SUM` = 1.0, `HRU_FR_SUM_TOLERANCE` =
  0.01, 2026-08-04): pedido explícito del usuario — HRU_FR sumado entre las
  HRU de una subcuenca debería dar ~1.0, pero la app nunca lo fuerza ni
  bloquea el guardado por eso, solo informa. Una etiqueta fija sobre la
  tabla (`_hru_fr_sum_label`) muestra la suma de la subcuenca visible,
  recalculada en cada `_refresh_table` (edición inline, Load CSV,
  Materialize, cambio de subcuenca) usando el staging en memoria cuando
  hay una celda editada — en ámbar (`AppPalette.warning`, nuevo en
  `resources/theme/swat_light.json`) si se aleja de 1.0 más que la
  tolerancia, en gris neutral si no. Deliberadamente no se calcula en el
  diálogo de confirmación de Load CSV/Materialize (podría implicar leer
  los `.hru` de muchas subcuencas de forma síncrona antes de confirmar,
  el mismo riesgo de freeze que ya evitó que Materialize corra en hilo de
  fondo) sino después: Load CSV no lee contenido `.hru` (solo valida
  existencia por nombre de archivo, sin cambios), y Materialize —ya en
  hilo de fondo— calcula la suma real post-escritura de cada subcuenca
  tocada y la reporta en el mensaje de resultado si queda fuera de
  tolerancia.
- **`engine/configure.py`**: copia `TxtInOut` y escribe `.pnd`.
- **Pestaña Run** (`ui/tab_run.py` + `engine/run.py`): quinta pestaña,
  habilitada al abrir proyecto igual que Wetlands/HRUs/Summary. Cubre el
  paso 2 del resumen del proyecto (ejecutar `swat2012.exe` como
  subproceso), que hasta ahora no existía en ningún lugar del código.
  También aloja la única configuración de ruta que la app usa hoy
  (`config.settings.AppPaths.swat_executable`, existente en el modelo de
  datos desde antes pero sin ninguna pantalla que la seteara): campo de
  solo lectura con la ruta configurada + botón "Browse..." que valida
  (`config.settings.validate_swat_executable`) y persiste vía
  `ConfigManager.save_paths`. Sin pestaña Settings separada — decisión
  explícita para no crear una pantalla de configuración dedicada mientras
  sea una sola ruta; si a futuro se agregan más rutas configurables ahí sí
  valdría la pena separarlo. El botón Run (deshabilitado sin proyecto
  abierto o sin ejecutable válido) pide confirmación y corre
  `engine.run.run_scenario` en hilo de fondo
  (`ui.tasks.run_in_background`, mismo patrón obligatorio que Summary/HRU)
  — una corrida real de SWAT puede tomar del orden de minutos. Esa función
  copia el ejecutable configurado a `TxtInOut/<target_executable_name>`
  (nunca renombra ni modifica el archivo original en su ubicación) y lo
  ejecuta con `cwd` en `TxtInOut`. El log de la pestaña se llena en tiempo
  real (decisión explícita del usuario, 2026-08-03: antes se leía todo de
  una sola vez al terminar el proceso) — `run_scenario` usa `Popen` en vez
  de `run`, con un hilo por stream (`stdout`/`stderr`) leyendo línea por
  línea (un único hilo síncrono arriesga bloquear el proceso hijo si el
  otro pipe se llena primero) y reportando el acumulado hasta el momento
  vía el mismo `report_progress` que ya usa `ui.tasks.run_in_background`
  — la UI conecta `on_progress` directo a `_set_log` en vez de al
  `status_label`. Éxito/error se determina únicamente por el exit code del
  proceso (0 = éxito) — decisión explícita del usuario (2026-07-31): no se
  intenta inferir éxito a partir de la presencia o contenido de
  `output.std`, y eso no cambió con el streaming.
  Bloquea navegación mientras corre (`App._on_run_tab_run_state_changed`,
  mismo mecanismo que las demás operaciones de fondo). Sin parseo de
  `output.*` — eso queda para la pieza de `viz/` de comparación línea
  base/escenario, que sigue sin empezar.

  También expone, en una tarjeta aparte dentro de la misma pestaña, los
  parámetros de `file.cio` más relevantes para una corrida puntual: año de
  inicio/fin (`NBYR`/`IYR`), años de warm-up excluidos del output
  (`NYSKIP`), y frecuencia de impresión (`IPRINT`: Daily/Monthly/Yearly).
  Decisión explícita del usuario (2026-07-31): CLAUDE.md ya traía una
  excepción para tocar `.fig`/`.cio` ante "cambio explícito de periodo
  simulado pedido por el usuario"; NYSKIP e IPRINT se suman a esa misma
  excepción porque son configuración de la corrida, no física del modelo
  — a diferencia de `.bsn`, que sigue sin ninguna excepción. Implementado
  en `swat_io.cio_parser` (`parse_run_settings`/`write_run_settings`,
  nuevo — el módulo antes solo leía) sobre el mismo grammar
  "valor | CODIGO : descripción" de `.pnd`/`.sub`
  (`swat_io.text_format.write_value_code_file`, ahora con un parámetro
  `decimals` — 0 para enteros como los de `file.cio`, en vez de los 3
  decimales que usan los parámetros físicos de humedal). Mismo patrón
  Edit/Cancel/Save con confirmación que `WetlandEditorWindow`/
  `HRUEditorWindow`, pero inline en la tarjeta en vez de una ventana
  aparte. Validación antes de escribir (año fin ≥ año inicio, `NYSKIP` en
  `[0, NBYR)`) tanto en la UI como en `write_run_settings` (no se llega a
  tocar el archivo si algún valor es inconsistente). Verificado además
  contra un `file.cio` real (`03-Models/Buffalo/Buffalo_calibrated_annual`)
  para confirmar que el ancho de columna se preserva y el resto del
  archivo queda byte a byte intacto.
- **Pestaña Results (`output.rch`)** (`ui/tab_results.py` +
  `swat_io/rch_parser.py` + `viz/rch_chart.py` + `viz/shapefile_map.py` +
  `viz/shapefile_reader.py`): sexta pestaña, cubre el paso 3 del resumen
  del proyecto para `output.rch` específicamente (caudal y cargas por
  tramo) — el resto de `output.*` sigue sin empezar. A diferencia de
  Wetlands/HRUs/Run, queda habilitada con el proyecto abierto aunque
  `output.rch` todavía no exista (el usuario puede no haber corrido SWAT
  todavía): en ese caso el botón "Organize .rch" queda deshabilitado con
  un hint, sin bloquear la pestaña.

  `output.rch` es texto de ancho fijo, pero su línea de encabezado (nombres
  de columna + unidad, ej. `FLOW_OUTcms`) no se puede separar de forma
  confiable por espacios: cuando el nombre+unidad excede el ancho
  reservado para esa columna, queda pegado al siguiente sin espacio (ej.
  `SETTLPSTmgRESUSP_PSTmgDIFFUSEPSTmgREACBEDPSTmg`, cuatro nombres
  seguidos). En vez de parsear ese encabezado roto,
  `swat_io.rch_parser.RCH_VARIABLE_COLUMNS` fija las 47 variables en su
  orden estable de SWAT2012 rev670 (verificado contando valores numéricos
  por fila de datos contra un `output.rch` real de
  `03-Models/Buffalo/Buffalo_calibrated_annual`, confirmado con el
  usuario). `parse_rch_file` devuelve un DataFrame crudo (una fila por
  reach y paso de tiempo); `build_rch_timeseries` le agrega una columna
  `date` real usando el periodo/frecuencia de `file.cio`
  (`swat_io.cio_parser.parse_run_settings`) y descarta las filas de
  resumen que SWAT agrega y que NO son una fecha real (confirmado
  explícitamente con el usuario contra el archivo real, no asumido):
  en salida *Yearly* hay una fila extra por reach al final con
  `MON` = años promediados en vez de un año calendario
  (`_YEARLY_SUMMARY_MON_THRESHOLD` la distingue por magnitud); en salida *Monthly*
  hay una 13ª fila por año con `MON` = año en vez de mes 1-12. En *Daily*
  el año de cada bloque se detecta por wrap-around de `MON` (día juliano
  que vuelve a 1), sin asumir bisiestos porque el archivo ya trae el
  conteo correcto de filas por año. "Organize .rch" corre esto en hilo de
  fondo (`ui.tasks.run_in_background`, `App._on_results_tab_run_state_changed`
  bloquea navegación igual que Summary/HRU/Run — parsear un `output.rch`
  Daily de muchos años puede no ser instantáneo) y escribe un CSV por
  reach en `tool_outputs/rch_timeseries/` (`export_rch_timeseries_csvs`):
  una fila por fecha, todas las variables como columna — sin lista curada
  (decisión explícita del usuario, mismo criterio que HRUs). No toca
  ningún archivo de `TxtInOut`, así que a diferencia de Materialize en
  Wetlands/HRUs no pide confirmación. Al reabrir el proyecto, si esos CSV
  ya existen de una corrida anterior se releen directo
  (`read_rch_timeseries_dir`) sin volver a parsear el `.rch` — mismo
  patrón de caché que Summary con `land_use_by_subbasin.csv`.

  Selector de reach + selector de variable (las 47 de
  `RCH_VARIABLE_COLUMNS`, por defecto `FLOW_OUT`) grafican la serie de
  tiempo (`viz/rch_chart.py`, mismo patrón sin-pyplot que
  `land_use_chart.py`). El mapa chico (`viz/shapefile_map.py`, geometría de
  `viz/shapefile_reader.py`) es puramente estático — sin click-to-select,
  pedido explícito del usuario —: dibuja las subcuencas (relleno) y los
  reach (línea) de los `.shp` configurados en Project, y solo resalta el
  elemento cuyo id coincide con la selección de reach/subcuenca actual. El
  campo de id **no se llama igual en los dos shapefiles** pese a
  identificar el mismo tramo/subcuenca (confirmado explícitamente por el
  usuario contra shapefiles reales, no asumido): `GRIDCODE` en el shp de
  subcuencas, `ARCID` en el shp de reach — `SUBBASIN_ID_FIELD` /
  `REACH_ID_FIELD` en `shapefile_reader.py`. La geometría se lee una sola
  vez por `set_project` (no en cada cambio de selector) y se cachea en
  memoria; solo el resaltado cambia al redibujar.
- **Pestaña Results (`output.sub`)** (`ui/tab_sub_results.py` +
  `swat_io/sub_output_parser.py`, 2026-08-11): misma estructura que
  Results/.rch de arriba (selector + variable, gráfica, mapa, "Organize"
  en hilo de fondo sin confirmación porque no toca `TxtInOut`, caché de
  CSVs en `tool_outputs/sub_timeseries/`), pero para el balance por
  subcuenca de `output.sub` en vez de caudal por reach. El mapa solo
  necesita el shapefile de subcuencas (no hay noción de reach en este
  archivo) — `viz/shapefile_map.build_shapefile_map_figure` se reutiliza
  tal cual pasándole una lista de reach vacía.

  **`output.sub` NO es como `output.rch`** (separado por espacios de forma
  confiable) — tiene el mismo problema estructural que `output.hru`
  (ancho fijo), pero con una variante propia no documentada hasta ahora:
  el campo `MON` se imprime **siempre pegado sin separador** al campo
  `AREA` que le sigue, para cualquier cantidad de dígitos de `MON`
  (incluido un solo dígito, ej. `"1.31340E+00"` en vez de
  `"1 0.31340E+00"`) — no es un caso de desborde ocasional como en
  `output.hru`, es así en el 100% de las filas. Encontrado al notar que
  el valor que debía ser el área constante de una subcuenca cambiaba fila
  a fila; confirmado verificando que, para cada subcuenca, los últimos 10
  caracteres del campo combinado son idénticos en todas sus filas
  (`AREA`), mientras que el prefijo variable coincide exactamente con la
  secuencia esperada de día/mes/año. `swat_io/sub_output_parser.py` usa
  slicing de ancho fijo para ese campo (`SUB_VARIABLE_COLUMNS`, offsets
  derivados y validados programáticamente contra los 32 `output.sub`
  reales del workspace, ~102 mil filas combinadas, 0 errores de parseo —
  mismo rigor que `output.hru`); los 24 campos de variable restantes SÍ
  están separados por espacios de forma confiable en ese mismo dataset.
- **Pestaña HRU Results (`output.hru`)** (`ui/tab_hru_results.py` +
  `swat_io/hru_output_parser.py`): séptima pestaña, cubre el paso 3 del
  resumen del proyecto para `output.hru` (balance por HRU) — pedido
  explícito del usuario (2026-08-03): serie de tiempo por subcuenca, por
  HRU y por variable, **sin nada espacial** (a diferencia de Results/.rch,
  esta pestaña no tiene mapa). A diferencia de todas las pestañas
  anteriores, el destino de "Organize" no es CSV sino una única base
  **SQLite** (`tool_outputs/hru_timeseries.db`, tabla ancha `date, sub,
  hru` + 80 columnas de variable): `output.hru` puede tener miles de HRU
  (una subcuenca tiene N HRU, a diferencia de un reach por subcuenca en
  `output.rch`) y en salida Daily puede pesar más de 1GB — un CSV por HRU
  degrada en cantidad de archivos, y cargar el archivo completo a un
  DataFrame antes de escribir no entra cómodamente en memoria. `sqlite3` es
  librería estándar de Python (cero dependencias nuevas, misma filosofía
  liviana que ya llevó a elegir pyshp en vez de geopandas) y permite
  consultar una sola serie (un HRU, una variable) sin cargar el resto —
  tanto `swat_io/hru_output_parser.py` como `ui/tab_hru_results.py` son
  streaming de punta a punta: nunca hay un DataFrame con el archivo
  completo en memoria, ni siquiera del lado de la UI post-procesamiento
  (los selectores subcuenca → HRU consultan SQLite bajo demanda, no un
  DataFrame ya cargado). Probado de punta a punta contra un `output.hru`
  Daily real de 1.47M filas / 1350 HRU (Crooked_daily): ~130s en hilo de
  fondo, sin congelar la ventana.

  `output.hru` es texto de ancho fijo con el mismo problema estructural que
  `output.rch` (header con nombres pegados, no parseable) más uno propio:
  a diferencia de `output.rch`, donde las 47 variables SÍ vienen separadas
  por espacios de forma confiable, en `output.hru` las 80 variables
  numéricas (tras un prefijo identificador `LULC/HRU/GIS/SUB/MGT/MON` de
  34 caracteres que sí tokeniza bien por espacios) NO tienen separador
  confiable entre columnas adyacentes cuando un valor llena todo su ancho
  fijo (ej. año `MON=2017` pegado directo al valor de `AREA` siguiente,
  sin espacio) o cuando un valor negativo en un campo normalmente positivo
  angosta el margen que en el resto de las filas separaba dos columnas.
  `HRU_OUTPUT_VARIABLE_COLUMNS`/`_VARIABLE_COLSPECS` (offsets de carácter
  exactos por columna, no por header) se derivaron y validaron
  programáticamente contra el contenido **completo** de los 31 `output.hru`
  reales disponibles en el workspace (~4.95M filas combinadas, 0 errores de
  parseo) — una muestra más chica resultó insuficiente: casos de signo
  negativo poco frecuentes en algunos proyectos rompían límites inferidos
  de una muestra parcial, descubierto iterativamente contra los archivos
  reales, no asumido de antemano. Campos que desbordan su ancho fijo se
  imprimen como `**********` (relleno de asteriscos, visto en un archivo
  real) y se guardan como `NaN` en vez de descartar la fila entera.

  La reconstrucción de fecha reutiliza la misma lógica que
  `build_rch_timeseries` (wraparound de MON, umbral de fila-resumen
  "average annual" en Yearly) pero **en streaming** — un diccionario por
  HRU con el último MON visto, en vez de `groupby` sobre un DataFrame ya
  completo — verificada contra un `output.hru` Yearly real (con fila de
  resumen "average annual", MON no-calendario) y un `output.hru` Daily
  real (sin fila de resumen, wraparound confirmado por HRU). Monthly no se
  pudo verificar contra un archivo real (ningún proyecto disponible usa
  `IPRINT=0`) — reutiliza el criterio ya confirmado por el usuario para
  `output.rch` (13ª fila de resumen con MON = año), sin verificación
  independiente para `output.hru`.

  Exporta cuatro formas de CSV. Las dos originales, por variable: la serie
  de un único HRU+variable ("Export this series"), o una variable para
  todas las HRU de una subcuenca en formato ancho — fecha + una columna
  `hru_<id>` por cada HRU ("Export variable for all HRUs in subbasin"). Y
  dos más agregadas el 2026-08-04, pedido explícito del usuario para no
  tener que repetir "Export this series" variable por variable cuando
  quiere varias de una misma HRU: "Export all variables for this HRU"
  (fecha + las 80 columnas, sin selección) y "Export selected
  variables..." (abre `ui/variable_selection_window.py`, una ventana modal
  con un checkbox por variable — `ui/variable_checklist.py`, reutilizada
  también por el modo RCH/HRU de la ventana de comparación de Batch
  Scenarios, ver más abajo — más "Select all"/"Clear"; al confirmar, la
  pestaña hace su propio filedialog + export, igual que los otros tres
  botones). Las cuatro comparten `swat_io.hru_output_parser.read_hru_variables`
  (una única query parametrizada por lista de columnas) en vez de cuatro
  funciones de lectura separadas. No toca ningún archivo de `TxtInOut`,
  igual que Results/.rch, así que "Organize .hru output" no pide
  confirmación. Deshabilitada hasta que haya un proyecto abierto; igual que
  Results/.rch, queda habilitada aunque `output.hru` todavía no exista (el
  botón Organize queda deshabilitado con un hint en ese caso).
- **`viz/`**: `land_use_chart.py` (coberturas por subcuenca, Summary),
  `rch_chart.py` (serie de tiempo por reach, Results — reutilizada tal
  cual, sin cambios, por HRU Results: la función de render ya era genérica,
  sin acoplamiento a reach/rch, así que no se creó un módulo `hru_chart.py`
  duplicado),
  `shapefile_reader.py` + `shapefile_map.py` (mapa estático de
  subcuencas/reach, Results). Sin empezar: gráficas comparativas línea
  base vs. escenario superpuestas (dos corridas a la vez) — el motivo
  original del paquete; hoy Results grafica una sola corrida por vez.

- **Pestaña Batch Scenarios** (`ui/tab_batch.py` + `engine/batch_run.py` +
  `scenarios/land_cover_config.py` + `scenarios/land_cover_reallocation.py`):
  octava pestaña, para correr en batch una serie de escenarios de cambio de
  cobertura (ej. "aumentar bosque a 10%, 20%, 30% del área de cada
  subcuenca", tipo reforestación/deforestación) tomando el proyecto
  abierto como referencia fija — pedido explícito del usuario
  (2026-08-03), tras varias rondas de precisar la regla de negocio antes
  de escribir código.

  El % objetivo es relativo al área total de cada subcuenca (no al área de
  la propia HRU) y se evalúa subcuenca por subcuenca de forma
  independiente. Único parámetro que se toca: `HRU_FR` — nunca ningún otro
  parámetro de la HRU, para no afectar la calibración
  (`scenarios/land_cover_reallocation.py`, algoritmo puro, sin
  dependencias de UI ni de disco). Reglas acordadas explícitamente con el
  usuario:
  - Si una subcuenca no tiene ninguna HRU con la cobertura objetivo, se
    omite (crear una HRU nueva implicaría definir manejo/vegetación desde
    cero, equivalente a recalibrar — fuera de alcance).
  - Si el % actual de la cobertura objetivo ya es ≥ el % pedido, también
    se omite: forzar una reducción sería deforestar, no reforestar, y no
    tiene sentido para este caso de uso.
  - El área que se quita a las coberturas donantes sigue una prioridad en
    cascada configurable: cobertura (obligatoria) > pendiente (opcional) >
    suelo (opcional). Sin un nivel de prioridad dado, ese nivel no
    desempata y el reparto ahí es proporcional al peso actual; coberturas/
    pendientes/suelos no listados en su nivel quedan en el último grupo de
    ese nivel (empatan entre sí, después de todos los nombrados).
  - El área que se agrega a la cobertura objetivo sigue la misma cascada
    de pendiente/suelo (no hay nivel de cobertura, ya está fija en el
    target). A diferencia de los donantes, el crecimiento no tiene un tope
    natural por grupo, así que toda el área nueva va al primer grupo no
    vacío en orden de prioridad (proporcional al peso actual dentro de ese
    grupo), en vez de repartirse entre varios grupos.
  - Cada porcentaje de la serie incremental (ej. 10/20/30%) se calcula
    siempre de forma independiente desde el proyecto de referencia, nunca
    encadenado (decisión explícita del usuario: evita arrastre de error de
    redondeo y hace los escenarios directamente comparables entre sí).

  La configuración (`scenarios/land_cover_config.py`,
  `parse_land_cover_batch_csv`) viene de un CSV con columnas
  `target_lulc`, `target_pct_series` (lista separada por comas, ej.
  "10,20,30"), `donor_priority` (coberturas separadas por ">", ej.
  "PAST>RNGB>AGRR"), y `slope_priority`/`soil_priority` opcionales (mismo
  separador). v1 exige exactamente una fila (una sola cobertura objetivo
  por batch; combinar varias en un mismo batch queda para una extensión
  futura si hace falta).

  La orquestación (`engine/batch_run.py`, `run_land_cover_batch`) toma el
  proyecto abierto como referencia fija (nunca se modifica) y, por cada
  paso de la serie: copia la carpeta completa del proyecto a
  `<destino>/scenario_<pct>pct/` (reutiliza
  `engine.configure.create_working_scenario`, así la copia queda con
  `TxtInOut/` directo, lista para abrirse como proyecto en la app sin
  pasos manuales — pedido explícito del usuario); calcula el plan de
  reasignación y lo escribe en los `.hru` reales de esa copia
  (`scenarios.hru_draft.write_hru_values`, reutilizado tal cual); ejecuta
  swat2012.exe sobre la copia (`engine.run.run_scenario`, reutilizado tal
  cual); y corre automáticamente el mismo post-procesamiento que hoy el
  usuario dispara a mano desde Summary/Results/HRU Results
  (`generar_resumen_coberturas`, `generar_resumen_humedales`, organizar
  `output.rch` y `output.hru` — cada uno reutilizado sin cambios, y solo
  si el archivo de salida correspondiente existe). Escribe además un
  reporte por escenario (`tool_outputs/batch_report.json`: qué subcuencas
  se modificaron y cuáles se omitieron y por qué). Un fallo puntual (copia,
  cálculo, SWAT, o post-procesamiento) en un paso de la serie no aborta el
  batch completo — queda registrado como error en ese paso y el batch
  sigue con el siguiente.

  Sin una lista curada de coberturas/pendientes/suelos válidos (a
  diferencia de Wetlands y sus 20 campos fijos), el usuario no tiene forma
  de saber de antemano qué escribir en el CSV — mismo problema que ya
  resolvió "Export CSV" en HRUs. Por eso `scenarios/land_cover_config.py`
  también expone `write_land_cover_batch_template_csv`
  (+ `discover_land_cover_options`), que escanea el proyecto abierto y
  genera un CSV de ejemplo ya válido con las coberturas/pendientes/suelos
  que realmente existen ahí (no un blanco genérico) — botón "Download
  template" de la pestaña, junto a "Load CSV".

  La pestaña (`ui/tab_batch.py`) pide una carpeta destino y un CSV de
  configuración, muestra una vista previa de los escenarios a correr, y
  "Run batch" pide confirmación (copia carpetas y corre SWAT N veces) antes
  de correr en hilo de fondo (`ui.tasks.run_in_background`, mismo patrón
  obligatorio que Run/Results/HRU Results) con log en tiempo real.
  Deshabilitada hasta que haya un proyecto abierto; bloquea navegación
  mientras corre (`App._on_batch_tab_run_state_changed`, mismo mecanismo
  que las demás operaciones de fondo).

  **Exportación comparativa entre escenarios** (`scenarios/comparison_export.py`
  + `ui/scenario_comparison_window.py`, botón "Compare scenarios..." de la
  pestaña, 2026-08-04): pedido explícito del usuario tras evaluar y
  descartar los dos botones puntuales de HRU Results (ver más arriba) como
  suficientes para el caso real — un usuario que corrió un batch de N
  escenarios quiere comparar el mismo reach/HRU/variable entre todos ellos
  sin abrir cada `scenario_<pct>pct/` como proyecto y exportar uno por uno.
  Es de solo lectura (nunca escribe en ningún `TxtInOut`, solo lee lo que
  Organize ya dejó en cada escenario) y opera sobre **cualquier** carpeta
  de batch vía su propio "Browse" — desacoplado de si el batch se acaba de
  correr en esta sesión o es uno anterior; si ya hay una carpeta destino
  elegida en la pestaña, la ventana arranca con esa carpeta precargada
  (`initial_batch_dir`), pero se puede apuntar a otra.

  Tres modos, todos produciendo **un archivo por variable** con una
  columna por escenario (el eje que se quiere comparar) — pedido explícito
  del usuario, para no tener que pegar CSVs a mano:
  - **RCH**: siempre todos los reach de la cuenca juntos (columnas `date,
    reach, <escenario...>`) — un reach ya es su propia unidad espacial, sin
    agregación.
  - **HRU puntual**: una única subcuenca+HRU (columnas `date,
    <escenario...>`).
  - **HRU agrupado** (ej. "todas las HRU de bosque"): filtro por
    cobertura/pendiente/suelo (cada campo opcional, AND entre campos, OR
    dentro de un campo si se marca más de un valor) con alcance "cuenca
    completa" (una sola serie agregada) o "subcuencas específicas"
    (columnas `date, sub, <escenario...>`, una serie por subcuenca). La
    clasificación de cada HRU se lee de un único escenario del batch (el
    primero encontrado), no de todos — el batch solo modifica `HRU_FR`
    (ver reglas arriba), nunca la identidad/cobertura/pendiente/suelo de
    una HRU, así que es la misma en todos los escenarios de un mismo
    batch.

  La agregación del modo agrupado usa `sum` o `weighted_mean` (ponderado
  por la columna `AREA` real de `output.hru`, no `HRU_FR`) según
  **`config/hru_variable_aggregation.json`** — deliberadamente en JSON y
  no hardcodeado en código (pedido explícito del usuario): casi todas las
  variables de `output.hru` están expresadas por unidad de área (mm, kg/ha,
  t/ha, o un índice como `DAILYCN`/`LAI`/días de estrés), así que promedio
  ponderado es lo correcto ahí; una variable que ya sea un total/flujo
  másico (no una tasa por área) necesitaría `sum` en cambio. La
  clasificación inicial del asistente pobló casi todo en `weighted_mean`
  (la única excepción es `AREA`, que se suma para dar el área total del
  grupo) a partir de la semántica estándar SWAT2012, sin verificación
  variable por variable contra el proyecto del usuario — el archivo está
  para que se corrija ahí, sin tocar código, si alguna clasificación no
  queda bien (`scenarios.comparison_export.load_hru_variable_aggregation`).

  El botón "Export selected variables..." de HRU Results y los dos
  checklists (RCH/HRU) de esta ventana comparten el mismo widget
  (`ui/variable_checklist.py`, checkboxes con scroll + Select all/Clear).

  Corre en hilo de fondo (`ui.tasks.run_in_background`) por si implica leer
  varias bases `hru_timeseries.db` completas; al ser una ventana modal
  (`grab_set()`) no hace falta bloquear navegación del resto de la app por
  separado, ya queda bloqueada por el propio modal. Escribe los CSV
  resultantes en `<carpeta de batch>/comparison_exports/`.

  **Lección de esta feature, para cualquier uso futuro de
  `CTkScrollableFrame` en la app:** un bug real (crash) apareció al abrir
  la ventana con `initial_batch_dir` ya seteado — el código reconstruía
  los checklists de cobertura/pendiente/suelo/subcuencas dentro de
  `__init__`, y usaba `checklist.master` para encontrar dónde volver a
  empaquetar el widget nuevo. `CTkScrollableFrame` redirige
  `pack()`/`grid()`/`destroy()` a un `_parent_frame` interno y el propio
  widget vive con `master=` apuntando a un canvas interno propio, no al
  contenedor real donde se llamó `.pack(...)` — `checklist.master` daba
  ese canvas (a veces ya en proceso de destruirse), no el contenedor
  verdadero, y reventaba con `TclError`. Corregido guardando el contenedor
  real aparte (`self._land_use_holder`, etc.) en vez de inferirlo del
  widget — atrapado por un test end-to-end con un root de Tk real
  (`tests/ui/test_scenario_comparison_export_e2e.py`), no por
  `py_compile` ni por tests que solo verifican lógica pura sin construir
  widgets.

  **NbS area batch (percentage series)** (`scenarios/nbs_area_batch.py` +
  `engine/nbs_area_batch_run.py`, tarjeta nueva al final de la misma
  pestaña Batch, 2026-08-12): pedido explícito del usuario — quería el
  mismo patrón de serie incremental que ya tiene esta pestaña para cambio
  de cobertura simple (10%, 20%, 30%, ... hasta 100%, una corrida real de
  SWAT por paso, salidas organizadas automáticamente), pero aplicando una
  NbS completa (`scenarios.nbs_apply.apply_nbs`: plant.dat/.hru/.mgt) en
  vez de solo reasignar `HRU_FR`. Vive en esta pestaña y no en NbS porque
  acá ya está toda la orquestación "copiar proyecto → correr SWAT →
  organizar salidas"; NbS sigue siendo dueña de la definición/aplicación
  puntual de una NbS, esta tarjeta solo la referencia por nombre
  (`scenarios.nbs.load_library`, releído de disco al correr, mismo
  criterio que Apply/Apply by area de la pestaña NbS).

  El usuario configura el área NbS "al 100%" con el mismo CSV matriz que
  ya usa "Apply an NbS by area (all subbasins)" (`subbasin, area_ha,
  <coberturas>...`, `scenarios.nbs_mass_apply.parse_mass_allocation_csv` y
  `write_mass_allocation_template_csv` reutilizados tal cual, con el mismo
  requisito de tener una NbS seleccionada antes de bajar el template). La
  serie de porcentajes vive en un campo de texto aparte (`"10,20,30,...,100"`,
  `scenarios.nbs_area_batch.parse_pct_series_text`, mismo separador y rango
  (0,100] que `target_pct_series` de Batch) en vez de una columna del CSV:
  la matriz ya tiene una forma fija (subcuenca × cobertura) sin lugar
  natural para una lista de porcentajes. Cada paso escala `area_ha` de cada
  subcuenca a ese % (`scale_allocations` — los % de cobertura entre sí no
  cambian, siguen siendo % de la misma área ya escalada) y se calcula
  siempre desde el proyecto de referencia, nunca encadenado — mismo
  criterio que el batch de cobertura.

  **Decisión de diseño clave, distinta de "Apply an NbS by area (all
  subbasins)":** esa sección bloquea el botón Apply si hay algún déficit
  (pedido explícito del usuario para forzar corrección antes de escribir
  nada — ver `ui.tab_nbs._block_mass_apply_if_skipped`). Acá el usuario
  pidió lo contrario ("aplique lo que pueda aplicar pero que me informe"):
  cada paso de la serie aplica lo alcanzable con las coberturas asignadas y
  corre SWAT igual, documentando el faltante en vez de bloquear —
  `engine.nbs_area_batch_run` llama a
  `scenarios.nbs_mass_apply.plan_mass_area_allocation` con `strict=False`
  (parámetro nuevo en esa función, default `True` preserva el
  comportamiento de bloqueo existente de la sección interactiva sin
  tocarla): con `strict=False` una subcuenca con déficit igual queda en
  `result.plans` con lo que sí se pudo seleccionar, en vez de moverse a
  `result.skipped`. El déficit de cada paso queda documentado en dos
  lugares: el log en tiempo real (una línea por subcuenca con déficit) y un
  reporte CSV por paso (`scenarios.nbs_area_batch.write_area_batch_step_report_csv`,
  en `tool_outputs/nbs_area_batch_report.csv` de esa copia de escenario —
  una fila por subcuenca/cobertura fuente con área pedida/aplicada/déficit,
  más una fila por subcuenca omitida por motivo estructural — sin `.sub` o
  sin ninguna HRU, eso sí sigue sin aplicarse nunca). El reporte por HRU de
  siempre (`scenarios.nbs_apply.write_apply_report_csv`) también se escribe
  en cada paso, igual que cualquier otro Apply de NbS.

  Salidas a organizar seleccionables (`scenarios.nbs_area_batch.OutputOrganizeOptions`,
  tres checkboxes output.rch/.sub/.hru, los tres tildados por default —
  pedido explícito del usuario: a diferencia del batch de cobertura, que
  siempre organiza todo lo que exista sin preguntar, acá organizar
  `output.hru` puede tardar minutos por paso y multiplicarse por cada % de
  la serie, así que el usuario puede desmarcarlo). `_organize_outputs` de
  `engine/nbs_area_batch_run.py` extiende el patrón ya usado por
  `engine.batch_run` (mismo resumen de coberturas/humedales siempre, sin
  checkbox) sumando `output.sub` (que el batch de cobertura simple todavía
  no organiza) y respetando qué casillas están tildadas.

  Reutiliza `engine.batch_run.scenario_folder_name` tal cual (mismo nombre
  de carpeta `scenario_<pct>pct` que el batch de cobertura) para que ambas
  features de batch sean consistentes — ojo: si el usuario apunta las dos
  al mismo destino con series de % solapadas, la segunda choca con
  `FileExistsError` en esos pasos puntuales (se reporta como error de ese
  paso, no aborta el resto — mismo criterio de tolerancia a fallos
  puntuales de siempre), por eso la UI usa un campo de destino separado del
  batch de cobertura, no el mismo. Un fallo puntual en un paso (copia,
  cálculo, SWAT, o post-procesamiento) no aborta la serie — mismo criterio
  que el resto de esta pestaña.

  La tarjeta entera vive dentro de un `CTkScrollableFrame` nuevo para esta
  pestaña (antes `_build_enabled_state` usaba un `CTkFrame` plano con el
  log expandiendo vía `rowconfigure(weight=1)`, que ya no entraba junto con
  esta tarjeta nueva en una ventana de pantalla chica — mismo motivo y
  mismo patrón ya usado en `ui/tab_nbs.py`, ver CLAUDE.md general sobre
  `TabBar`/`CTkScrollableFrame`). El log de cobertura simple pasó a altura
  fija (`height=200`) en vez de expandirse, ya que dentro de un scroll no
  tiene sentido pedirle a una fila que "llene el espacio restante".

- **Pestaña NbS** (`ui/tab_nbs.py` + `ui/nbs_wizard_window.py` +
  `ui/nbs_operation_dialog.py` + `scenarios/nbs.py` + `scenarios/nbs_analysis.py`
  + `scenarios/nbs_apply.py`, 2026-08-11): novena pestaña, asistente para
  construir y aplicar masivamente "Soluciones basadas en la Naturaleza"
  (NbS) — cambios de cobertura vegetal reutilizables (ej. "restauración de
  bosque") sobre las HRU que el usuario elija. Pedido explícito del
  usuario, con una decisión de diseño previa clave: la guía técnica que
  trajo el usuario
  (`SWAT2012_rev670_guia_general_cambio_creacion_coberturas.md`) deja
  claro que una cobertura SWAT nunca es solo un `PLANT_ID` — es
  fisiología vegetal (`plant.dat`, solo si la cobertura es nueva) +
  superficie/dosel/residuos (`.hru`) + condición inicial y manejo
  (`.mgt`, cabecera **y** calendario completo de operaciones). Por eso una
  NbS agrupa los cuatro a la vez (`scenarios.nbs.NbSDefinition`), no un
  set de parámetros sueltos.

  **Módulos nuevos de `swat_io` que esto requirió** (no existían antes de
  esta feature): `swat_io/mgt/` (parser/writer round-trip de `.mgt` —
  cabecera con la misma gramática `valor | CODIGO : descripción` que
  `.pnd`/`.hru` reutilizada vía `swat_io.text_format`, y una sección
  "Operation Schedule" de **ancho fijo sin nombres de columna en el
  archivo**, cuyas columnas exactas se sacaron de la documentación oficial
  SWAT2012 I/O File Documentation cap. 20 y se verificaron programáticamente
  byte a byte contra los ~6500 `.mgt` reales de Buffalo_calibrated_annual y
  Crooked_daily — 0 discrepancias, cubriendo 11 de los 17 tipos de
  operación reales del proyecto); `swat_io/plant/` (parser/writer de
  `plant.dat`/`crop.dat`, registros de 5 líneas en formato libre —
  **hallazgo verificado contra tres modelos reales del proyecto**: la
  línea 5 de este `plant.dat` real de rev670 solo tiene 5 campos
  `BIO_LEAF MAT_YRS BMX_TREES EXT_COEF BMDIEOFF`, no los 7 que trae la
  documentación oficial más reciente de SWAT2012 IO — `RSR1C`/`RSR2C` no
  existen en el archivo real y por eso no se exponen en el catálogo de
  parámetros, para no inventar campos inexistentes); `swat_io/sol_parser.py`
  (lectura de solo lectura de `Soil Hydrologic Group` en `.sol`, único uso
  que esta feature necesita de `.sol` — el resto del archivo sigue sin
  tocarse, coherente con que un cambio de cobertura nunca modifica el
  suelo). También se extrajo `swat_io/common/field_formatting.py`
  (formateo de campo preservando ancho/decimales del valor original) como
  utilidad compartida nueva, sin tocar la copia histórica ya probada de
  `swat_io/hru/models.py` — mismo criterio de `swat_io/common/` que ya
  documenta este archivo.

  **El wizard de creación** (`NbSWizardWindow`, ventana modal con pasos
  Next/Back — decisión explícita del usuario dado el número de bifurcaciones
  del flujo) recorre: nombre → cobertura objetivo (existente del `plant.dat`
  real del proyecto, o nueva) → si es nueva, fisiología completa (copiando
  de una cobertura existente como base, o desde cero — sin rellenar
  ningún campo en silencio, coherente con la "regla de no invención" de la
  guía) → **copiar de una configuración existente** (paso opcional:
  `scenarios.nbs_analysis.scan_existing_parameter_combinations` escanea las
  HRU reales que hoy tienen la cobertura elegida y agrupa sus parámetros
  `.hru`/`.mgt`/calendario en combinaciones exactas — con tolerancia de
  redondeo, y **CN2 desagregado por HYDROLOGIC_SOIL_GROUP** en vez de un
  único valor, porque la guía es explícita en que CN2 depende del grupo
  hidrológico de suelo y una misma NbS se aplicará sobre HRU con distinto
  suelo; corre en hilo de fondo, `ui.tasks.run_in_background`, puede tardar
  sobre un TxtInOut real) → parámetros `.hru` (`CANMX`/`OV_N`/`RSDIN`) →
  condición inicial `.mgt` (`IGRO`/`LAI_INIT`/`BIO_INIT`/`PHU_PLT`) + CN2 por
  HSG → calendario de manejo completo (`ui/nbs_operation_dialog.py`, un
  diálogo por operación; los campos mostrados dependen del `MGT_OP`
  elegido vía `swat_io.mgt.operation_specs.OPERATION_FIELD_SPECS` — el
  campo `PLANT_ID` de una operación "plant" se omite del formulario a
  propósito, ver más abajo) → revisión y guardado. Todo texto de parámetro
  usa nombre legible (`config/nbs_parameter_labels.py`, sin rangos
  curados — mismo criterio que `.hru` en general) en vez del acrónimo SWAT
  crudo, y los códigos de cobertura (`CPNM`) se etiquetan con su nombre
  descriptivo estándar (`config/cpnm_names.py`, 127 entradas de la base
  vegetal estándar de referencia del proyecto — solo para mostrar, nunca
  fuente de verdad de qué coberturas existen realmente en el `plant.dat`
  del proyecto). El wizard siempre escribe la biblioteca JSON de NbS del
  proyecto (`tool_outputs/nbs_library.json`, `scenarios/nbs.py`); el
  usuario puede crear varias NbS antes de aplicar ninguna a ningún HRU
  (pedido explícito del usuario). Si la cobertura es nueva, además
  sincroniza de inmediato el registro correspondiente en el `plant.dat`
  real del proyecto al terminar el wizard (crear o editar) — pedido
  explícito del usuario, 2026-08-11: antes esto se resolvía recién al
  aplicar la NbS a un HRU (ver "Aplicar una NbS" más abajo). Pide
  confirmación aparte (distinta de la de Aplicar) porque, a diferencia
  del resto del wizard, sí toca `TxtInOut` en ese momento
  (`scenarios.nbs_apply.sync_new_coverage_to_plant_dat`): crea el
  registro la primera vez, o lo actualiza in-place en ediciones
  posteriores (identificado por `NbSNewCoverage.icnum`, no por CPNM, para
  seguir encontrando el mismo registro aunque el usuario renombre el
  CPNM al editar) — nunca duplica ni borra un registro por esta vía,
  ni siquiera si la NbS misma se borra de la biblioteca después.

  **Aplicar una NbS** (`scenarios/nbs_apply.py`, sección aparte de la misma
  pestaña: selector de subcuenca + lista de HRU con selección múltiple para
  construir la lista de HRU objetivo) sí escribe de verdad, directo sobre
  el proyecto abierto — mismo patrón in-place ya aceptado para
  Wetlands/HRUs (ver aviso de deuda técnica más abajo). La NbS a aplicar
  se relee de `nbs_library.json` justo antes de aplicar
  (`ui.tab_nbs.NbSTab._on_apply_clicked`, `scenarios.nbs.load_library`),
  no de `self._library` (la copia en memoria que solo se refresca al abrir
  el proyecto o crear/editar/borrar una NbS desde la UI) — pedido
  explícito del usuario, 2026-08-11: si el usuario edita
  `nbs_library.json` a mano mientras el proyecto está abierto, Apply debe
  usar el archivo tal como quedó, no una copia desactualizada. El ICNUM de
  una cobertura nueva normalmente ya está resuelto desde que se guardó la
  NbS (ver "sincroniza de inmediato" más arriba); `_resolve_plant_id`
  sigue como red de seguridad para NbS creadas antes de ese cambio o con
  la biblioteca editada a mano sin ICNUM (`max(ICNUM)+1` sobre el
  `plant.dat` real, o reutilizando un registro existente con el mismo
  CPNM en vez de duplicarlo). El campo `PLANT_ID` interno de una operación
  "plant" (`MGT_OP=1`, distinto del `PLANT_ID` de cabecera) se inyecta
  automáticamente con el ICNUM resuelto — por eso el wizard no lo pide: la
  NbS no puede conocerlo de antemano. Cada HRU objetivo se escribe
  todo-o-nada (HYDGRP sin CN2 definido en la NbS, o `HRUFile.validate()`
  con algún issue `ERROR`, cancela solo esa HRU) y un fallo puntual no
  aborta el resto del lote — mismo criterio que Materialize de HRUs y el
  batch de cobertura. El calendario de operaciones se **reemplaza entero**,
  nunca se parchea (guía del proyecto, sección 12-13: manejo heredado de
  la cobertura anterior — pastoreo, fertilización — mezclado con la nueva
  cobertura produce una HRU inconsistente). Como puede tocar
  `plant.dat` (compartido por toda la cuenca, no por HRU/subcuenca como el
  resto de lo que la app toca hoy) y muchas HRU a la vez, corre en hilo de
  fondo (`ui.tasks.run_in_background`) y pide confirmación antes de
  correr (`App._on_nbs_tab_run_state_changed` bloquea navegación, mismo
  mecanismo que las demás operaciones de fondo). También actualiza el
  texto `Luse:<CPNM>` de la línea de título de `.hru` y `.mgt` (reportado
  por el usuario, 2026-08-11: `swat_io.hru.parser`/`swat_io.mgt.parser`
  leen ese texto como `metadata.land_use`, y `scenarios.nbs_analysis` lo
  usa para decidir qué HRU "tienen" una cobertura al escanear
  combinaciones existentes — sin este fix, una HRU recién convertida
  seguía apareciendo bajo su cobertura vieja en cualquier escaneo
  futuro). `.sol` deliberadamente se excluye de este fix aunque también
  trae `Luse:` en su título: la guía del proyecto lo marca sin
  excepciones como archivo que un cambio de cobertura nunca modifica
  (sección 3.3), y ninguna función de escaneo de esta app lee ese texto
  de `.sol` — solo `swat_io.sol_parser.read_hydrologic_group`, que no
  depende de él.

  **Edición de una NbS ya creada** (`NbSWizardWindow(..., existing=...)`,
  botón "Edit..." o doble clic en la biblioteca, 2026-08-11): mismo
  wizard de creación, pre-poblado desde la `NbSDefinition` existente —
  cada paso ya leía sus valores iniciales de `self._state`, así que
  precargar `self._state` en `__init__` alcanzó sin tocar los pasos
  individuales. Guardar con el mismo nombre actualiza en el lugar
  (`add_or_replace` ya hace upsert por nombre); el único ajuste fue
  excluir el nombre original del chequeo de "nombre ya usado". La
  pestaña también expone "Open NbS folder" (abre `tool_outputs/`, donde
  vive `nbs_library.json`) junto a Edit/Delete.

  **Aplicar una NbS por área** (`scenarios/nbs_area_apply.py`, tarjeta
  "Apply an NbS by area" de la misma pestaña, 2026-08-11): pedido explícito
  del usuario — alternativa a elegir HRU una por una a mano (sección
  "Aplicar una NbS" de arriba) cuando lo que se quiere es "convertir 100 ha
  de esta subcuenca a esta NbS, 40% viniendo de bosque y 60% de pastos".
  Alcance: una subcuenca a la vez, igual que la sección manual. El usuario
  arma una tabla de `(cobertura fuente, % del área total)` que debe sumar
  100% (`validate_source_allocations`), más prioridad opcional de pendiente
  y suelo (mismo separador `">"` que `donor_priority`/`slope_priority` de
  Batch, `parse_priority_text`). `plan_area_allocation` calcula, cobertura
  por cobertura, cuántas HRU completas de esa cobertura hay que convertir
  para cubrir su porción del área objetivo: nunca se parte una HRU en dos
  coberturas para calzar el área exacta (mismo criterio ya aceptado en
  `scenarios.land_cover_reallocation` — partir/crear una HRU equivaldría a
  recalibrar), así que dentro de cada grupo de prioridad se toman HRU
  completas de menor a mayor área hasta igualar o superar el objetivo
  (heurística simple para minimizar el sobrante, no una solución óptima de
  empaquetado). Si una cobertura fuente no tiene HRU disponibles en la
  subcuenca se omite; si tiene menos área de la pedida, se aplica toda la
  disponible y se reporta el déficit sin abortar el resto (mismo criterio
  que Batch). El área de cada HRU sale de `HRU_FR * área real de la
  subcuenca` (`swat_io.sub_parser.parse_sub_file`, `SUB_KM * 100`), nunca
  de un valor inventado. El resultado (`AreaAllocationPlan.targets`, lista
  de `(subbasin, hru)`) se pasa tal cual al mismo motor de escritura ya
  existente (`scenarios.nbs_apply.apply_nbs`): este módulo nuevo solo
  decide *cuáles* HRU entran, nunca escribe ningún archivo. "Preview"
  muestra el desglose (ha pedidas/seleccionadas/HRU por cobertura, y
  cualquier déficit) sin tocar disco; "Apply by area" recalcula el mismo
  plan, pide confirmación (mismo texto de advertencia que el Apply manual:
  escribe directo sobre `.hru`/`.mgt`/`plant.dat` reales) y corre en hilo
  de fondo. Ambos botones de aplicar (manual y por área) se deshabilitan
  mutuamente mientras cualquiera de los dos corre, para no arriesgar
  escrituras concurrentes sobre el mismo `TxtInOut`.

  **Aplicar una NbS por área en todas las subcuencas**
  (`scenarios/nbs_mass_apply.py`, tarjeta "Apply an NbS by area (all
  subbasins)" de la misma pestaña, 2026-08-12): pedido explícito del
  usuario — extensión de "Aplicar una NbS por área" de arriba para no
  repetirla subcuenca por subcuenca. Entrada: un CSV en forma de matriz
  (fila = subcuenca, columna `area_ha` + una columna por cobertura fuente,
  celda de cobertura = % de `area_ha` — no del área total de la subcuenca
  — a convertir desde esa cobertura); celda de cobertura vacía = esa
  cobertura no participa en esa subcuenca, `area_ha` vacía = esa subcuenca
  no participa del batch (se omite sin error). Diseño revisado 2026-08-12
  (pedido explícito del usuario, reemplazando la v1 de esta misma
  feature): la v1 no tenía columna de área separada — cada celda ya era,
  directamente, el % del área TOTAL de la subcuenca, lo que obligaba a
  razonar al revés ("¿qué % de mi subcuenca es esta NbS de 50 ha que
  quiero plantar?") en vez de partir del área que se quiere. Ahora
  `area_ha` es el área NbS objetivo de esa subcuenca (en hectáreas) y las
  celdas de cobertura vuelven a ser % de esa área — mismo criterio que
  `total_area_ha` + `source_allocations` de la sección manual
  (`nbs_area_apply.plan_area_allocation`) — así que ahora SÍ tienen que
  sumar 100 (`parse_mass_allocation_csv`, misma tolerancia que
  `validate_source_allocations`), a diferencia de la v1 donde alcanzaba
  con "≤100". `plan_mass_area_allocation` valida además que el `area_ha`
  pedido se pueda cubrir de verdad con las coberturas fuente que el
  usuario asignó en esa fila — no contra el área total de la subcuenca
  (revisado 2026-08-12, pedido explícito del usuario: comparar solo contra
  el área total daba un límite demasiado optimista si el usuario no
  asignó todas las coberturas disponibles de esa subcuenca, y el mensaje
  de error no le decía cuánta área SÍ era alcanzable con lo que había
  asignado), sino contra `AreaAllocationPlan.total_deficit_ha` que ya
  calcula `plan_area_allocation` recorriendo las HRU reales de esas
  coberturas puntuales. Si hay déficit, la subcuenca entera se omite y se
  reporta (`result.skipped`) con un mensaje que da el área máxima
  alcanzable desglosada por cobertura fuente (ej. "área disponible ... —
  FRST: 50.00 ha disponibles") — a diferencia de la sección manual de
  "Apply by area", donde un déficit no bloquea nada y el plan se aplica
  parcial con una nota en el preview (`area_preview_deficit_line`), acá el
  usuario explícitamente prefirió que cualquier déficit fuerce corregir el
  CSV antes de aplicar, ver más abajo el bloqueo del botón Apply. Mismo
  criterio de tolerancia a fallos puntuales que ya tenía la v1 para
  cualquier otra fila puntual inválida (`parse_mass_allocation_csv`: valor
  no numérico, suma ≠ 100, subcuenca repetida, sin abortar el resto del
  CSV — mismo criterio que Batch). Con `total_area_ha` ahora
  `allocation.area_ha` (no el área real de la subcuenca),
  `plan_mass_area_allocation` sigue reutilizando `plan_area_allocation`
  sin ningún cambio al algoritmo de selección de HRU, subcuenca por
  subcuenca (una subcuenca sin `.sub` localizable o sin ninguna HRU
  también se omite y se reporta, no aborta el batch). Prioridad de
  pendiente/suelo: una sola configuración global para todo el batch (mismo
  criterio que `donor_priority` en Batch Scenarios), no una columna por
  subcuenca — evita una matriz todavía más ancha sin un caso de uso real
  detrás. Una sola NbS objetivo para todo el batch, elegida en la UI (no en
  el CSV): los planes de todas las subcuencas se calculan por separado pero
  se aplican en un único llamado a `scenarios.nbs_apply.apply_nbs` con los
  targets de todas juntas (esa función ya soportaba targets de más de una
  subcuenca). "Download template" (`write_mass_allocation_template_csv`,
  mismo criterio que el template de Batch y "Export CSV" de HRUs) escanea
  el proyecto y arma una fila por subcuenca real, una columna `area_ha` en
  blanco (a completar por el usuario — como ninguna fila del template
  participa hasta que se llene `area_ha`, sus ceros de cobertura no
  necesitan sumar 100 de entrada) y una columna por cobertura real — pero,
  a diferencia de esos otros templates, es específico de la NbS elegida en
  el selector (`_mass_nbs_selector`, exige
  una NbS seleccionada antes de generar el archivo, mismo chequeo que
  Preview/Apply): `target_lulc` de la NbS ni siquiera aparece como columna
  (no puede ser su propia fuente) y cada celda que sí es una cobertura
  fuente válida en esa subcuenca se puebla con `0` en vez de un valor de
  ejemplo — pedido explícito del usuario, 2026-08-12: antes solo la
  primera cobertura de cada fila traía un ejemplo (10%) y el resto quedaba
  en blanco sin que el usuario pudiera distinguir "esta cobertura no
  existe en esta subcuenca" de "esta cobertura no aplica para esta NbS
  pero sí existe" — con `0` en toda celda aplicable, blanco pasa a
  significar únicamente lo primero, y el usuario ve de un vistazo qué
  celdas puede editar sin arriesgarse a convertir una cobertura hacia sí
  misma. Los tres botones de aplicar (manual, por área, y por área en
  todas las subcuencas) se deshabilitan mutuamente mientras cualquiera
  corre, mismo motivo que ya llevó a esa regla entre los primeros dos.

  **Bloqueo de Apply cuando hay subcuencas SKIPPED** (`_block_mass_apply_if_skipped`
  en `ui/tab_nbs.py`, 2026-08-12): a diferencia de Batch y del resto de esta
  misma tarjeta (donde un fallo puntual no aborta el resto del lote), acá
  el usuario pidió explícitamente lo contrario — si el plan calculado
  tiene aunque sea una subcuenca en `result.skipped` (sin importar el
  motivo: no encontrada, sin HRU, o coberturas fuente insuficientes), el
  botón "Apply to all subbasins" se deshabilita y no se abre el diálogo de
  confirmación ni se escribe nada, hasta que el usuario corrija el CSV y
  lo vuelva a cargar (`_on_mass_load_csv_clicked` es lo único que
  rehabilita el botón vía `_update_mass_apply_button_state`). Se llama
  tanto desde Preview como desde el propio Apply (por si el usuario le da
  a Apply sin haber previsualizado antes) — en ambos casos primero
  renderiza el log con el detalle de cada SKIPPED
  (`_render_mass_plan_preview`) y después bloquea, para que el mensaje de
  error quede acompañado del desglose de área alcanzable por subcuenca.

  Las tres operaciones largas de esta tarjeta (Download template, Preview,
  Apply to all subbasins) muestran una barra de progreso "vaivén" mientras
  corren en hilo de fondo -- pedido explícito del usuario, 2026-08-12: sin
  ninguna señal visual además del texto gris estático, un escaneo largo
  contra un modelo real (miles de `.hru`) parece que la app se congeló y
  tienta a cerrarla. Reutiliza tal cual el patrón ya resuelto en
  `ui/tab_summary.py` (constantes `_PROGRESS_MIN/MAX/STEP/INTERVAL_MS`,
  `CTkProgressBar` movida a mano en vez de su modo `indeterminate` nativo):
  ese modo nativo corre su propio bucle `after()` muy corto que, medido
  contra un modelo real, compite por el GIL con el hilo de fondo y
  multiplica el tiempo total de la corrida (~5x más lento, con cortes de
  hasta 2s) -- el vaivén en cambio está atado al mismo intervalo de sondeo
  (150ms) que ya usa `ui.tasks.run_in_background`, sin agregar ningún bucle
  nuevo. Una sola barra alcanza para las tres operaciones porque ya se
  deshabilitan mutuamente (nunca corren dos a la vez).

**Aviso importante — deuda técnica aceptada explícitamente:** la
restricción "Aislamiento por escenario" de la sección siguiente **no está
enforced por código todavía**. Las pestañas Wetlands y HRUs escriben sobre
`<proyecto abierto>/TxtInOut/*.pnd` y `*.hru` respectivamente sin verificar
si esa carpeta es una copia de escenario o el modelo de referencia
calibrado; la pestaña Run corre `swat2012.exe` sobre ese mismo
`TxtInOut` sin esa verificación tampoco, con el mismo aviso. Aplicar una
NbS (`scenarios/nbs_apply.py`) hereda el mismo aviso, con un radio de
impacto mayor cuando crea una cobertura nueva: escribe sobre
`plant.dat`, compartido por **toda la cuenca** (no por HRU/subcuenca como
el resto de lo que la app toca hoy). Decisión
explícita del usuario (2026-07-31, reafirmada al
construir la pestaña HRUs, y otra vez al construir NbS el 2026-08-11):
no bloquear esto en código por ahora — quedará
documentado en un futuro manual de usuario que abrir la carpeta calibrada
directamente es bajo su propio riesgo. No "arreglar" esto de oficio sin
que el usuario lo pida — es una elección consciente, no un olvido.

Actualizar este bloque a medida que la interfaz siga creciendo.

## Restricciones técnicas (no negociables)

- **Motor fijo**: el motor de cómputo es SWAT2012 revisión 670, distribuido
  como el ejecutable `rev670_64rel.exe`. No se sustituye por SWAT+, no se
  reimplementa la física en Python, no se actualiza de versión bajo ninguna
  circunstancia. Cualquier sugerencia de "migrar a SWAT+" o "reescribir el
  módulo hidrológico en Python" está fuera de alcance y debe rechazarse.
- **Ejecución exclusivamente por línea de comandos**: la app NO usa ni
  automatiza SWAT Editor, y no lee ni escribe ninguna base `.mdb`
  (SWATGDB, MasterProgress, SWAT2012.mdb, SSURGO). Toda la orquestación
  (copiar `TxtInOut`, colocar el ejecutable, correr el modelo, leer
  salidas) se hace directamente sobre archivos de texto plano. Cualquier
  ruta de código que abra o dependa de un `.mdb` está fuera de alcance.
- **Aislamiento por escenario**: cada corrida vive en su propio directorio
  de trabajo, para permitir comparar múltiples escenarios entre sí y contra
  la línea base sin interferencia.

## Archivos SWAT y su rol

| Archivo | Rol en la app |
|---|---|
| `.pnd` (por subcuenca) | Único archivo editable por el usuario. Expone los 20 parámetros de la sección "Wetland inputs": `WET_FR` (fracción de subcuenca que drena al humedal), `WET_NSA` / `WET_NVOL` (área y volumen a nivel normal), `WET_MXSA` / `WET_MXVOL` (área y volumen máximos), `WET_VOL` (volumen inicial), `WET_K` (conductividad hidráulica del fondo), sedimento (`WET_SED`, `WET_NSED`), settling de N/P (`PSETLW1/2`, `NSETLW1/2`), y nutrientes/calidad de agua (`CHLAW`, `SECCIW`, `WET_NO3`, `WET_SOLP`, `WET_ORGN`, `WET_ORGP`, `WETEVCOEFF`). Editable hoy vía la pestaña Wetlands (.pnd) — ver "Estado actual". |
| `.sub` | Vincula la subcuenca con el HRU/área que drena al humedal. Se lee para construir la UI de selección de subcuencas con humedal; no se edita por escenario. |
| `.bsn` | Parámetros globales de cuenca. Fuera de alcance: nunca se modifica por escenario. |
| `.fig` / `.cio` | Topología del watershed y control maestro de la corrida (fechas, opciones de impresión). Se mantienen intactos entre escenarios salvo que el usuario cambie explícitamente el periodo simulado. |
| `output.rch` | Caudal y carga por tramo de río. Salida principal para comparación de caudal. Organizada en serie de tiempo por reach (CSV + gráfica + mapa) desde la pestaña Results — ver "Estado actual". |
| `output.sub` | Balance por subcuenca. Organizado en serie de tiempo por subcuenca (CSV + gráfica + mapa) desde la pestaña Results (.sub) — ver "Estado actual". |
| `output.hru` | Balance por unidad de respuesta hidrológica. Organizado en base SQLite (no CSV, ver pestaña HRU Results) y explorado por subcuenca/HRU/variable (gráfica + export CSV) desde la pestaña HRU Results — ver "Estado actual". |
| `output.mgt` | Operaciones de manejo por HRU; se lee como texto plano junto con las demás salidas. |
| `output.std` | Resumen general de la corrida. |
| `.hru` (por HRU) | Parámetros físicos/agronómicos de cada HRU (`HRU_FR`, `SLSUBBSN`, `OV_N`, `CANMX`, `ESCO`, `EPCO`, etc.). Editable hoy vía la pestaña HRUs (`swat_io.hru`) y, para `CANMX`/`OV_N`/`RSDIN`, vía Aplicar NbS (`swat_io.mgt`... ver pestaña NbS más arriba). |
| `.mgt` (por HRU) | Cabecera de condición inicial/manejo general (`IGRO`, `PLANT_ID`, `CN2`, etc., misma gramática `valor \| CODIGO : descripción` que `.pnd`) más el calendario completo de operaciones de manejo (siembra, cosecha, pastoreo, fertilización...), texto de ancho fijo sin nombres de columna en el archivo. Antes solo se leía como parte de `output.mgt`; editable hoy vía Aplicar NbS (`swat_io.mgt`, ver pestaña NbS más arriba) — nunca por la UI de HRUs. |
| `plant.dat` / `crop.dat` | Base vegetal: fisiología de cada `PLANT_ID` (registros de 5 líneas, ver `swat_io.plant`). El nombre real lo indica `PLANTDB` en `file.cio` — nunca se asume. Editable hoy solo cuando una NbS crea una cobertura nueva (Aplicar NbS agrega un registro nuevo con `ICNUM = max(ICNUM)+1`; nunca modifica un registro existente). Compartido por **toda la cuenca**, no por HRU/subcuenca. |

La app debe tratar el parseo de estos archivos como una capa propia y
aislada (lectura/escritura de `.pnd`, lectura de salidas), separada de la
lógica de UI y de la lógica de orquestación del subproceso, para poder
testear el parseo sin necesidad de ejecutar el binario.

## Módulo swat_io.hru (inventario y edición técnica de HRUs)

Ya implementado y con 92 pruebas (`tests/swat_io/hru/`, todas pasando junto
con el resto del repo). Es una librería de `swat_io`, sin dependencias de UI
ni del subproceso SWAT. Su parte de solo lectura (inventario y resumen de
coberturas) se expone vía `generar_resumen_coberturas.py`, invocado en
hilo de fondo desde la pestaña Summary de la UI (ver "Estado actual").
Su edición de un solo parámetro/HRU (`get_value`/`set_value`) sí está
conectada a la UI desde la pestaña HRUs (`ui/hru_editor_window.py`, ver
"Estado actual"). Su API de modificación masiva (`HRUSelection`/
`HRUModificationRule`, ver más abajo) sigue sin conectarse a ningún flujo
de la interfaz — queda lista para un futuro flujo de edición masiva de
HRU, equivalente al CSV import/Materialize que sí tiene Wetlands.

**Qué resuelve:**

- Lee cualquier `.hru`, preservando su estructura byte a byte en un
  round-trip sin cambios (encabezados, comentarios, líneas desconocidas,
  espacios, separador `|`, salto de línea original, codificación
  UTF-8/UTF-8 con BOM/`cp1252`).
- Permite consultar y modificar parámetros por nombre
  (`hru.get_value("CANMX")`, `hru.set_value("CANMX", 12.5)`), cambiando
  únicamente el campo de valor de la línea modificada; todo lo demás queda
  intacto.
- Escanea recursivamente un `TxtInOut` y arma un inventario tabular
  (pandas) con una fila por HRU, más un resumen de coberturas por
  subcuenca (`fraction_sum`, `percentage_of_subbasin`) exportable a CSV.
- Expone una API de modificación masiva controlada (`HRUSelection` +
  `HRUModificationRule` → `preview_modifications` / `apply_modifications`
  / `write_modified_hru_files`), pensada para escribir siempre sobre una
  copia de escenario, nunca sobre la carpeta base.

**Ubicación:**

```text
swat_io/common/   # encoding.py, atomic_write.py, line_parser.py (genéricos, reutilizables por otros parsers)
swat_io/hru/      # models.py, parser.py, writer.py, scanner.py, summary.py, modifiers.py, validation.py, exceptions.py
```

**Puntos de entrada:** dos scripts en la raíz del proyecto, funcionales de
forma independiente a la UI; la interfaz nueva deberá invocarlos en hilo de
fondo (ver "Operaciones largas y UI no bloqueante") sin bloquear la
ventana:

- `generar_resumen_coberturas.py` — dado un escenario (carpeta con
  `TxtInOut/`), genera `land_use_by_subbasin.csv` en su `tool_outputs/`.
- `generar_resumen_humedales.py` — genera `wetland_summary.csv` (parámetros
  de humedal por subcuenca, leídos de `.pnd`) en la misma carpeta
  `tool_outputs/`, vía `swat_io.summary.summarize_project` +
  `swat_io.tool_outputs.save_wetland_summary`.

**Distinción importante que cualquier feature futura debe respetar:**
`HRU_FR` (`.hru`, fracción de la subcuenca que ocupa esa HRU) y `WET_FR`
(`.pnd`, fracción de la subcuenca que drena al humedal) son variables
independientes y nunca deben combinarse automáticamente.

Documentación técnica completa (decisiones de diseño, supuestos, y qué
falta validar contra un `.hru` real de rev. 670): `docs/hru_module.md`.

## Stack y convenciones de código

- **Lenguaje**: Python 3.x.
- **UI**: CustomTkinter sobre Tkinter.
- **Separación de capas** (obligatoria, no solo sugerida):
  - `io/` o `swat_io/`: parseo y escritura de archivos SWAT (`.pnd`, `.sub`,
    `.hru`, lectura de `output.*`). Sin dependencias de UI. Los parsers
    simples de un solo archivo (`.pnd`, `.sub`) viven como módulo plano en
    `swat_io/`; un parser con round-trip completo, escáner e inventario
    (como `.hru`) se organiza en su propio subpaquete (`swat_io/hru/`),
    con las utilidades genéricas (codificación, escritura atómica, split
    de líneas) en `swat_io/common/` para que otros parsers futuros las
    reutilicen en vez de reimplementarlas.
  - `engine/` o `runner/`: gestión de copias de `TxtInOut`, invocación del
    subproceso `swat2012.exe`, captura de stdout/stderr y códigos de salida.
  - `scenarios/`: modelo de datos de un escenario (parámetros modificados,
    ruta de trabajo, estado de ejecución, resultados asociados).
  - `ui/`: vistas y widgets CustomTkinter. No debe contener lógica de
    parseo de archivos SWAT ni de invocación de subproceso directamente;
    consume las capas anteriores.
  - `viz/` o `charts/`: generación de gráficas comparativas (línea base vs.
    escenario).
- Los parámetros de humedal y sus rangos válidos deben modelarse
  explícitamente (no como diccionarios sueltos de strings), de forma que la
  UI pueda validar entradas antes de escribir el `.pnd`.
- Toda escritura de archivos SWAT debe hacerse sobre la copia de trabajo del
  escenario, nunca sobre la carpeta base. Preferir que la función de
  escritura reciba explícitamente la ruta destino en vez de inferirla.
- Manejo de errores del subproceso: la app debe distinguir entre "SWAT
  terminó con error" (código de salida, contenido de log) y "no se pudo
  parsear la salida", y comunicar cuál ocurrió al usuario.

### Operaciones largas y UI no bloqueante

Cualquier operación que pueda tardar más que unos milisegundos sobre un
modelo real (copiar `TxtInOut`, parsear miles de `.hru`/`.pnd`, y en el
futuro correr `swat2012.exe`) **debe** correr en un hilo de fondo
(`threading.Thread(daemon=True)`) que nunca toca widgets directamente. Este
proyecto ya se congeló dos veces por saltarse esto — con datos sintéticos
de prueba una operación de segundos parece instantánea, pero contra un
modelo real (35k+ archivos) puede tardar 45s+ y congelar toda la ventana.

Patrón obligatorio para cualquier operación larga que la nueva UI dispare:

1. El hilo de fondo nunca llama a `self.after(...)` ni toca ningún widget;
   solo empuja mensajes a una `queue.Queue`.
2. El hilo principal sondea la cola con `self.after(intervalo_ms, ...)`.
3. Cada ciclo de sondeo aplica **solo el último** mensaje de progreso
   encontrado, descartando los anteriores sin redibujar por cada uno: con
   archivos reales el hilo de fondo puede encolar mensajes más rápido de lo
   que la UI alcanza a procesarlos, y redibujar uno por uno hace que el
   respaldo crezca sin control hasta congelar la ventana igual (el mismo
   bug, dos capas más abajo).

### CTkLabel.bind("<Configure>", ...) y bucles de resize (wraplength responsive)

`ui/widgets.py` expone `bind_responsive_wraplength(label)`, usada por los
textos de ayuda/estado de las tablas compiladas (`_status_label` e
`instructions_label` en `ui/tab_wetlands.py` y `ui/tab_hru.py`) para que el
`wraplength` siga el ancho real del contenedor en vez de un valor fijo en
pixeles, y el texto se reajuste solo al redimensionar la ventana.

**Nunca enganchar `<Configure>` directo sobre un `CTkLabel` para leer su
propio ancho** — otro freeze total real (esta vez apenas se abre un
proyecto, ni siquiera hace falta una operación larga) aparecido al hacerlo
así. `CTkLabel.bind()` (customtkinter) no engancha el evento al frame
compuesto, sino a sus dos widgets internos (`_canvas` y el `tkinter.Label`
real que dibuja el texto) — y el tamaño de esos widgets internos cambia
*como consecuencia* de `wraplength`. Enganchado ahí se arma un bucle de
retroalimentación (`<Configure>` → cambia `wraplength` → cambia el tamaño
interno → nuevo `<Configure>`) que nunca se estabiliza y consume la
ventana. La corrección fue enganchar `label.master` (el contenedor real
del grid, con `columnconfigure(weight=1)`) en vez del label mismo: su
ancho cambia solo por el layout externo (redimensionar la ventana), nunca
por el contenido del label, así que no hay ciclo. Cualquier `CTkLabel`
futuro que necesite `wraplength` responsive debe usar
`bind_responsive_wraplength`, nunca un `bind("<Configure>", ...)` manual
sobre el label.

## Empaquetado y distribución

- Compilación a ejecutable con PyInstaller (o equivalente).
- Distribución mediante instalador (ej. Inno Setup si el target es
  Windows).
- La ruta al ejecutable `rev670_64rel.exe` debe ser **configurable por el
  usuario**, nunca hardcodeada. Documentar en el propio proyecto (README o
  pantalla de configuración) cómo la app localiza el binario en la máquina
  del usuario: configuración persistida (archivo de config / registro de
  ajustes de usuario), con validación de que la ruta apunta a un ejecutable
  válido antes de permitir ejecutar escenarios.
- El renombrado a `swatUser.exe` (o el nombre que `file.cio` espere) ocurre
  al copiarlo dentro de cada carpeta de escenario; el archivo configurado
  por el usuario nunca se renombra en su ubicación original.

## Límites del asistente

Al trabajar en este proyecto, el asistente NO debe:

- Recalibrar el modelo por escenario: los parámetros hidrológicos y de
  suelo fuera del módulo de humedales permanecen fijos entre escenarios.
- Cambiar la versión de SWAT, proponer SWAT+, ni introducir dependencias
  que reemplacen o envuelvan el motor de cómputo `rev670_64rel.exe`.
- Reimplementar en Python cualquier parte de la física hidrológica que hoy
  resuelve el binario.
- Automatizar SWAT Editor, ni leer/escribir bases `.mdb` (SWATGDB,
  MasterProgress, SWAT2012.mdb, SSURGO). Toda la interacción con datos SWAT
  pasa por archivos de texto plano (`TxtInOut`, `output.*`).
- Correr múltiples cuencas en paralelo/batch como funcionalidad base.
- Modificar archivos fuera del alcance definido por el escenario activo
  (en particular: nunca escribir sobre la carpeta de referencia elegida —
  calibrada o no —, nunca tocar `.bsn`, nunca alterar `.fig`/`.cio` salvo
  cambio explícito de periodo simulado pedido por el usuario).
- Asumir rutas hardcodeadas al binario SWAT o a carpetas de datos del
  usuario; toda ruta sensible a la máquina debe ser configurable.
