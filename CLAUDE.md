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
  los botones ya no entra en una ventana de pantalla chica (ahora siete,
  con HRU Results), y sin scroll las
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

  Exporta dos formas de CSV, según lo pedido explícitamente por el
  usuario: la serie de un único HRU+variable ("Export this series"), o una
  variable para todas las HRU de una subcuenca en formato ancho — fecha +
  una columna `hru_<id>` por cada HRU ("Export variable for all HRUs in
  subbasin"). No toca ningún archivo de `TxtInOut`, igual que Results/.rch,
  así que "Organize .hru output" no pide confirmación. Deshabilitada hasta
  que haya un proyecto abierto; igual que Results/.rch, queda habilitada
  aunque `output.hru` todavía no exista (el botón Organize queda
  deshabilitado con un hint en ese caso).
- **`viz/`**: `land_use_chart.py` (coberturas por subcuenca, Summary),
  `rch_chart.py` (serie de tiempo por reach, Results — reutilizada tal
  cual, sin cambios, por HRU Results: la función de render ya era genérica,
  sin acoplamiento a reach/rch, así que no se creó un módulo `hru_chart.py`
  duplicado),
  `shapefile_reader.py` + `shapefile_map.py` (mapa estático de
  subcuencas/reach, Results). Sin empezar: gráficas comparativas línea
  base vs. escenario superpuestas (dos corridas a la vez) — el motivo
  original del paquete; hoy Results grafica una sola corrida por vez.

**Aviso importante — deuda técnica aceptada explícitamente:** la
restricción "Aislamiento por escenario" de la sección siguiente **no está
enforced por código todavía**. Las pestañas Wetlands y HRUs escriben sobre
`<proyecto abierto>/TxtInOut/*.pnd` y `*.hru` respectivamente sin verificar
si esa carpeta es una copia de escenario o el modelo de referencia
calibrado; la pestaña Run corre `swat2012.exe` sobre ese mismo
`TxtInOut` sin esa verificación tampoco, con el mismo aviso. Decisión
explícita del usuario (2026-07-31, reafirmada al
construir la pestaña HRUs): no bloquear esto en código por ahora — quedará
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
| `output.sub` | Balance por subcuenca. |
| `output.hru` | Balance por unidad de respuesta hidrológica. Organizado en base SQLite (no CSV, ver pestaña HRU Results) y explorado por subcuenca/HRU/variable (gráfica + export CSV) desde la pestaña HRU Results — ver "Estado actual". |
| `output.mgt` | Operaciones de manejo por HRU; se lee como texto plano junto con las demás salidas. |
| `output.std` | Resumen general de la corrida. |
| `.hru` (por HRU) | Parámetros físicos/agronómicos de cada HRU (`HRU_FR`, `SLSUBBSN`, `OV_N`, `CANMX`, `ESCO`, `EPCO`, etc.). Hoy se usa en modo lectura para inventario e informes de cobertura (ver "Módulo swat_io.hru" más abajo); la librería sí soporta escritura controlada para uso técnico/mantenimiento, pero la UI de escenarios todavía no edita `.hru`. |

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
