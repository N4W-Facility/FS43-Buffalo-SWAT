# CLAUDE.md

Contexto de proyecto para Claude Code. Este documento es la fuente de verdad
sobre alcance, restricciones y convenciones. Ante cualquier ambigüedad,
las restricciones técnicas y los límites del asistente tienen prioridad
sobre la conveniencia de implementación.

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
- **Configuración base de solo lectura**: el `TxtInOut` calibrado y validado
  (`*_calibrated_*`) nunca se edita in situ. Cada escenario opera sobre una
  copia aislada (carpeta de trabajo propia). La app debe garantizar que no
  existe ninguna ruta de código que escriba sobre la carpeta base.
- **Aislamiento por escenario**: cada corrida vive en su propio directorio
  de trabajo, para permitir comparar múltiples escenarios entre sí y contra
  la línea base sin interferencia.

### Secuencia obligatoria antes de ejecutar

1. Copiar el `TxtInOut` base (calibrado/validado, de solo lectura) a una
   carpeta de escenario aislada.
2. Aplicar los cambios de parámetros de humedal en el `.pnd` de esa copia.
3. Colocar el ejecutable `rev670_64rel.exe` dentro de esa carpeta de
   escenario, **renombrado como `swatUser.exe`** (o el nombre que espere
   `file.cio` en esa instalación) — el nombre esperado por `file.cio` no
   debe asumirse fijo en el código; debe leerse o configurarse.
4. Invocar el ejecutable como subproceso desde esa carpeta de escenario
   (no desde una ruta global ni desde la carpeta base).
5. Leer `output.rch`, `output.sub`, `output.hru` y `output.mgt` como texto
   plano una vez termina la corrida.

Esta secuencia es el contrato entre la capa de orquestación (`engine/` o
`runner/`) y el resto de la app; ningún otro módulo debe invocar el
ejecutable ni copiar `TxtInOut` por fuera de ella.

## Archivos SWAT y su rol

| Archivo | Rol en la app |
|---|---|
| `.pnd` (por subcuenca) | Único archivo editable por el usuario. Expone los parámetros de humedal: `WET_FR` (fracción de subcuenca que drena al humedal), `WET_NSA` / `WET_NVOL` (área y volumen a nivel normal), `WET_MXSA` / `WET_MXVOL` (área y volumen máximos), `WET_VOL` (volumen inicial), `WET_K` (conductividad hidráulica del fondo), y parámetros de sedimento asociados al humedal. |
| `.sub` | Vincula la subcuenca con el HRU/área que drena al humedal. Se lee para construir la UI de selección de subcuencas con humedal; no se edita por escenario. |
| `.bsn` | Parámetros globales de cuenca. Fuera de alcance: nunca se modifica por escenario. |
| `.fig` / `.cio` | Topología del watershed y control maestro de la corrida (fechas, opciones de impresión). Se mantienen intactos entre escenarios salvo que el usuario cambie explícitamente el periodo simulado. |
| `output.rch` | Caudal y carga por tramo de río. Salida principal para comparación de caudal. |
| `output.sub` | Balance por subcuenca. |
| `output.hru` | Balance por unidad de respuesta hidrológica. |
| `output.mgt` | Operaciones de manejo por HRU; se lee como texto plano junto con las demás salidas. |
| `output.std` | Resumen general de la corrida. |

La app debe tratar el parseo de estos archivos como una capa propia y
aislada (lectura/escritura de `.pnd`, lectura de salidas), separada de la
lógica de UI y de la lógica de orquestación del subproceso, para poder
testear el parseo sin necesidad de ejecutar el binario.

## Flujo funcional esperado

1. El usuario selecciona una configuración SWAT base (`TxtInOut` calibrado).
2. Define un escenario modificando uno o más parámetros de humedal (`.pnd`)
   sobre una o varias subcuencas.
3. La app copia el `TxtInOut` base a un directorio de trabajo del escenario,
   aplica los cambios sobre los `.pnd` correspondientes, coloca el
   ejecutable (`rev670_64rel.exe` renombrado como `swatUser.exe`) en esa
   carpeta y lo ejecuta como subproceso.
4. La app lee las salidas (`output.rch`, `output.sub`, `output.hru`,
   `output.mgt`, `output.std`) del escenario y las compara contra la
   corrida de línea base (sin modificar), visualizando diferencias en
   caudal, sedimento y nutrientes.

La línea base debe ejecutarse (o reutilizarse si ya existe una corrida
cacheada) antes de poder mostrar comparaciones; la app no debe asumir
salidas de línea base preexistentes sin verificarlas.

## Convención de escenarios y multi-cuenca

- **Naming de escenario**: `{Watershed}_{ScenarioAbbreviation}_{timestep}`,
  extendiendo la convención ya usada en los datos (`Calibrated`, `LS`,
  `MS`, `HS`, `PS`, `GI`) con abreviaturas propias del módulo de humedales:
  `WET_LS`, `WET_MS`, `WET_HS` (degradación/mejora en distintos grados).
  Cualquier generación de nombres de carpeta o de escenario debe respetar
  este patrón, no inventar uno nuevo.
- **Origen único**: cada escenario de humedal se construye siempre a partir
  del `TxtInOut` `*_calibrated_*` de la cuenca correspondiente, nunca a
  partir de otro escenario ya modificado (no hay escenarios "en cadena").
- **Proyecto multi-cuenca**: el alcance cubre 9 cuencas — BigSister,
  Buffalo, Canadaway, Cattaraugus, Chautauqua, Crooked, Eighteenmile,
  SilverWalnut, Tonawanda. Cada una tiene un subbasin de salida (outlet)
  específico que debe usarse al extraer resultados de `output.rch`, por
  ejemplo Buffalo → subbasin 9, Tonawanda → subbasin 37. Este mapeo
  cuenca→outlet debe modelarse explícitamente (tabla/config), no
  hardcodearse disperso en el código de graficado.
- **Procesamiento cuenca por cuenca**: la UI y el flujo de ejecución deben
  permitir seleccionar y trabajar sobre una cuenca a la vez. Correr las 9
  cuencas en paralelo o en batch no es un requisito inicial; no diseñar
  para eso salvo que se pida explícitamente.

## Stack y convenciones de código

- **Lenguaje**: Python 3.x.
- **UI**: CustomTkinter sobre Tkinter.
- **Separación de capas** (obligatoria, no solo sugerida):
  - `io/` o `swat_io/`: parseo y escritura de archivos SWAT (`.pnd`, `.sub`,
    lectura de `output.*`). Sin dependencias de UI.
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

## Sistema de diseño

Estética minimalista tipo Notion, **tema claro** (no oscuro), sobre paleta
azul institucional SWAT adaptada a fondo claro.

- Definir la paleta y tipografía como **tokens de diseño reutilizables**
  (constantes centralizadas), nunca como valores de color sueltos
  hardcodeados por widget.
- Paleta funcional:
  - Azul oscuro SWAT (referencia: logo oficial, azul marino) → acento de
    marca: encabezados, botones primarios.
  - Azul medio → elementos interactivos secundarios (inputs activos, links,
    controles).
  - Azul muy claro → fondo de paneles/tarjetas.
  - Verde suave → color complementario para diferenciar escenarios
    (línea base vs. escenario modificado) en gráficas y estados.
  - Fondo general blanco / gris claro, sin dominancia del azul oscuro sobre
    grandes superficies.
- CustomTkinter para lograr aspecto flat/moderno sobre Tkinter (evitar el
  aspecto Tkinter clásico por defecto).
- En gráficas comparativas, mantener consistentemente el mismo color para
  "línea base" y otro para "escenario" a través de toda la app.

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
- Correr múltiples cuencas en paralelo/batch como funcionalidad base, ni
  construir escenarios encadenados a partir de otros escenarios (siempre
  desde `*_calibrated_*`).
- Modificar archivos fuera del alcance definido por el escenario activo
  (en particular: nunca escribir sobre el `TxtInOut` base, nunca tocar
  `.bsn`, nunca alterar `.fig`/`.cio` salvo cambio explícito de periodo
  simulado pedido por el usuario).
- Asumir rutas hardcodeadas al binario SWAT o a carpetas de datos del
  usuario; toda ruta sensible a la máquina debe ser configurable.
