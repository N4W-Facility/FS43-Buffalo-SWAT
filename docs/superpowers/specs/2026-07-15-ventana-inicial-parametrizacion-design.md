# Diseño: ventana inicial y vista de parametrización de humedales

Fecha: 2026-07-15
Estado: aprobado por el usuario, pendiente de plan de implementación

## Contexto

Primer diseño de interfaz para la app de escenarios de humedales sobre
SWAT2012 (ver `CLAUDE.md` en la raíz del proyecto para restricciones
técnicas y convenciones). Este documento cubre únicamente: la ventana
inicial de la app y la vista de "Parametrización" de un escenario, incluido
el ciclo de vida del CSV de trabajo que alimenta la materialización del
escenario. No cubre ejecución de SWAT ni visualización comparativa —
quedan para una siguiente iteración de diseño.

## Vocabulario

- **Proyecto**: contenedor de una cuenca (ej. Buffalo). Agrupa la línea
  base y todos los escenarios de humedal creados sobre esa cuenca. Vive en
  `workspace_root/{Watershed}/`.
- **Escenario**: una variación de parámetros de humedal sobre subcuencas de
  un proyecto, nombrada según la convención de CLAUDE.md
  (`{Watershed}_{ScenarioAbbreviation}_{timestep}`). Un proyecto puede
  contener varios escenarios, pero la vista de Parametrización siempre
  trabaja sobre uno a la vez.
- **Borrador de escenario**: el estado editable de un escenario antes de
  materializarse como carpeta de trabajo real (antes de "Configurar
  escenario").

## 1. Flujo de navegación general

```
Ventana inicial
   └─ [Abrir o crear proyecto] → selecciona/crea proyecto (cuenca)
         └─ Ventana de proyecto (barra de herramientas)
                ├─ Parametrización     → define/edita un escenario
                └─ Configurar escenario → materializa la carpeta de trabajo
```

"Nuevo escenario" no es una pantalla separada: al entrar a Parametrización
sin un borrador activo, la propia vista pide el nombre del escenario antes
de mostrar la tabla de subcuencas.

"Configurar escenario" ejecuta únicamente los pasos 1–3 de la secuencia
obligatoria de CLAUDE.md (copiar `TxtInOut`, aplicar `.pnd`, colocar el
ejecutable renombrado). No invoca el subproceso `swat2012.exe` — un botón
"Ejecutar" queda fuera de alcance de este diseño.

## 2. Ventana inicial

- Layout centrado y minimalista (validado visualmente frente a una
  alternativa con panel lateral de "recientes", descartada para esta
  iteración por simplicidad).
- Contenido: título de la app, un botón único **"Abrir o crear proyecto"**,
  y debajo un campo de solo lectura que muestra la ruta/nombre del proyecto
  seleccionado (placeholder: "Ningún proyecto seleccionado" cuando está
  vacío).
- El botón abre el diálogo nativo del sistema con dos caminos posibles:
  - **Crear proyecto nuevo**: el usuario elige una cuenca calibrada desde
    `base_models_root` (ruta ya configurada vía `ConfigManager`/`AppPaths`);
    la app crea `workspace_root/{Watershed}/` si no existe.
  - **Abrir proyecto existente**: el usuario navega directamente a una
    carpeta de proyecto ya creada dentro de `workspace_root`.
- Al seleccionar/crear un proyecto, la app navega a la ventana de proyecto
  y el campo de ruta se actualiza con el nombre de la carpeta del proyecto.
- Sin lista de proyectos recientes en esta iteración.

## 3. Ventana de proyecto (barra de herramientas)

- Encabezado fijo con el nombre del proyecto (cuenca) y, debajo, el nombre
  del escenario activo, o el texto "Sin escenario — define uno en
  Parametrización" si aún no existe un borrador.
- Barra de herramientas con dos acciones únicamente:
  1. **Parametrización** — abre la vista de edición de parámetros de
     humedal (sección 4).
  2. **Configurar escenario** — deshabilitado hasta que exista un borrador
     de escenario con nombre válido. Al activarse, ejecuta la
     materialización (sección 5) y reporta éxito/error en un panel de
     estado simple junto al encabezado.
- No hay pestañas ni menús adicionales en esta iteración.

## 4. Vista de Parametrización

Validada visualmente: panel de lista fijo a la izquierda + formulario fijo
a la derecha (alternativa de "editor emergente" por subcuenca, descartada:
exige abrir/cerrar un modal por cada una de las 7 campos por subcuenca,
más fricción para ediciones seguidas).

- **Encabezado de la vista**: si no hay escenario activo, un campo para
  nombrarlo, con el patrón `{Watershed}_{Abbrev}_{timestep}` pre-sugerido
  (cuenca ya conocida por el proyecto abierto; el usuario completa
  abreviación y periodo). Se valida contra la convención antes de aceptar
  y de habilitar el resto de la vista.
- **Barra superior**: contador "X de N subcuencas con humedal" (calculado
  sobre `summarize_project()`, ya implementado en `swat_io/summary.py`) +
  botón "Importar CSV".
- **Panel izquierdo (lista, ~40% del ancho)**: una fila por subcuenca —
  indicador (lleno/vacío) de si tiene humedal activo (`WET_FR > 0`), ID de
  subcuenca, y el valor actual de `WET_FR` como referencia rápida. Click
  selecciona la fila.
- **Panel derecho (formulario, ~60% del ancho)**: los 7 campos declarados
  en `resources/layout/wetland_pond.yaml` (`WET_FR`, `WET_NSA`, `WET_NVOL`,
  `WET_MXSA`, `WET_MXVOL`, `WET_VOL`, `WET_K`) para la subcuenca
  seleccionada, generados por el form builder genérico ya previsto en la
  arquitectura (sin campos hardcodeados en Python). Si la subcuenca no
  tiene humedal (`WET_FR = 0`), el mismo formulario permite definir uno
  desde cero.
- **Guardado**: al salir de un campo (blur) o Enter, se valida contra el
  rango declarado en el YAML. Si es válido, se actualiza la fila
  correspondiente en la lista y se reescribe el CSV de trabajo del
  escenario en ese instante. Si no es válido, el campo se marca en error y
  no se escribe nada (ni en pantalla ni en disco).
- **Importar CSV**: reemplaza valores de una o varias subcuencas de una
  sola vez. Se valida columna por columna contra el esquema de
  `wetland_pond.yaml` antes de aplicar cualquier cambio; si hay columnas
  faltantes o valores fuera de rango, se rechaza el importe completo
  (all-or-nothing) y se muestra un mensaje claro indicando fila, columna y
  valor problemático.

## 5. Ciclo de vida del CSV y materialización del escenario

- Al nombrar un escenario en Parametrización, la app crea un borrador en
  `workspace_root/{Watershed}/_borradores/{scenario_name}.csv` — una fila
  por subcuenca, columnas = parámetros de humedal. Se inicializa copiando
  los valores del `TxtInOut` base (vía `summarize_project()`), de forma
  que el usuario edita partiendo del estado calibrado real, no de valores
  vacíos.
- Este borrador es un archivo distinto de `tool_outputs/wetland_summary.csv`
  (el resumen de solo lectura del modelo base, ya implementado): el
  borrador es propio del escenario en construcción y es editable.
- **Configurar escenario** lee este CSV y ejecuta la secuencia obligatoria
  de CLAUDE.md:
  1. Copia el `TxtInOut` base a `workspace_root/{Watershed}/{scenario_name}/`.
  2. Para cada fila del CSV, escribe los valores en el `.pnd`
     correspondiente de la copia.
  3. Coloca el ejecutable configurado por el usuario, renombrado según lo
     que espere `file.cio` en esa instalación.
  4. Mueve el CSV del borrador a
     `{scenario_name}/tool_outputs/scenario_params.csv` (registro de qué
     se configuró) y elimina el borrador de `_borradores/`.
- Errores en este paso se distinguen explícitamente, como exige CLAUDE.md:
  "no se pudo copiar/escribir la carpeta de trabajo" vs. errores de
  validación del CSV detectados antes de escribir nada. La ejecución de
  `swat2012.exe` en sí queda fuera de alcance de este documento.

## Fuera de alcance de este diseño

- Botón "Ejecutar" y manejo de estado de la corrida (pendiente/en
  ejecución/completado/error).
- Vista de comparación línea base vs. escenario (`viz/`).
- Panel de proyectos recientes en la ventana inicial.
- Edición o comparación simultánea de múltiples escenarios en una misma
  tabla.
- Verificación de los outlets pendientes de las 7 cuencas restantes
  (no relacionado con esta interfaz).
