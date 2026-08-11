# SWAT2012 rev. 670 — Guía general para modificar o crear coberturas desde `TxtInOut`

## 0. Propósito

Este documento define un **protocolo general y reutilizable** para modificar una cobertura existente o cree una cobertura nueva en cualquier modelo **SWAT2012 revisión 670** ejecutado directamente desde los archivos de texto de `TxtInOut`.

No asume que el modelo esté calibrado, no depende de una cuenca particular y no usa valores específicos de ningún proyecto.

El objetivo es que el agente sepa:

1. qué archivos debe leer;
2. qué archivos puede modificar;
3. qué parámetros están directamente vinculados con la cobertura;
4. qué parámetros deben revisarse de forma condicional;
5. qué parámetros y archivos no deben modificarse por un cambio puro de cobertura;
6. cómo crear correctamente un nuevo `PLANT_ID`/`ICNUM`;
7. cómo validar la consistencia del escenario antes de ejecutar SWAT.

---

# 1. Supuestos de trabajo

Esta guía asume que:

- el modelo es **SWAT2012 rev. 670**;
- el modelo ya existe y contiene una carpeta `TxtInOut` funcional;
- SWAT se ejecuta directamente desde línea de comandos;
- la base `.mdb` de ArcSWAT/SWAT Editor **no participa en la ejecución**;
- la modificación se realiza sobre HRU existentes;
- el cambio de cobertura **no implica redelinear HRU, cambiar su área, suelo, pendiente o ubicación**;
- el cambio principal corresponde a una cobertura vegetal estándar representada mediante la base vegetal indicada por `PLANTDB` en `file.cio`.

Si el escenario cambia físicamente el suelo, la geometría, la red de drenaje, el acuífero, un humedal como objeto de almacenamiento, un cuerpo de agua, un sistema urbano o un sistema séptico, deben aplicarse reglas adicionales fuera del cambio vegetal estándar.

---

# 2. Principio fundamental

En SWAT2012 una cobertura de una HRU **no está definida por una sola etiqueta**.

El comportamiento de una cobertura vegetal resulta de la combinación de tres componentes principales:

```text
                         COBERTURA DE LA HRU
                                |
              +-----------------+-----------------+
              |                                   |
              v                                   v
          plant.dat /                         archivo .mgt
          crop.dat                            de la HRU
              |                                   |
              |                                   +-- PLANT_ID
              |                                   +-- IGRO
              |                                   +-- LAI_INIT
              |                                   +-- BIO_INIT
              |                                   +-- PHU_PLT
              |                                   +-- CN2
              |                                   +-- manejo
              |
              +-------------------+
                                  |
                                  v
                             archivo .hru
                                  |
                                  +-- CANMX
                                  +-- OV_N
                                  +-- RSDIN
```

Por tanto:

> **Cambiar solamente el texto `Luse:XXXX` del encabezado del `.hru` no cambia el comportamiento de la HRU.**

La primera línea de `.hru` y `.mgt` es un `TITLE` descriptivo y no controla los cálculos del modelo.

---

# 3. Archivos que intervienen

## 3.1 Cambio hacia una cobertura vegetal que YA existe

Si la cobertura objetivo ya está definida en la base vegetal activa:

```text
Modificar:
    xxxx.hru
    xxxx.mgt

Leer/verificar:
    file.cio
    plant.dat o crop.dat indicado por PLANTDB
```

No se debe modificar la base vegetal si el `PLANT_ID` objetivo ya existe.

---

## 3.2 Creación de una cobertura vegetal NUEVA

Si se necesita una nueva parametrización fisiológica vegetal:

```text
Modificar:
    plant.dat / crop.dat indicado por PLANTDB
    xxxx.hru
    xxxx.mgt

Leer/verificar:
    file.cio
```

La nueva cobertura debe recibir un nuevo `ICNUM`, y los `.mgt` que la utilicen deben usar ese mismo número como `PLANT_ID`.

---

## 3.3 Archivos que NO se modifican en un cambio puro de cobertura vegetal

Por defecto, el agente no debe escribir en:

```text
*.sol
*.chm
*.gw
*.sub
*.rte
*.bsn
*.swq
*.wwq
*.pnd
*.res
file.cio
SWAT2012.mdb
TablesIn/*
TablesOut/*
```

La razón es que un cambio de cobertura no modifica automáticamente:

- el tipo o las propiedades físicas del suelo;
- la química inicial del suelo;
- la pendiente física de la HRU;
- el área de la HRU;
- la subcuenca a la que pertenece;
- la geometría del canal;
- las propiedades del acuífero;
- los parámetros globales de cuenca.

Estos archivos pueden **leerse** para obtener contexto, pero no deben alterarse salvo que el escenario incluya explícitamente un cambio físico adicional.

---

# 4. `file.cio`: función en este flujo

`file.cio` debe considerarse **solo de lectura** para un cambio de cobertura normal.

El agente debe localizar el campo:

```text
PLANTDB
```

Ese campo indica qué archivo vegetal usa realmente la simulación.

Dependiendo del modelo, puede aparecer un nombre como:

```text
plant.dat
crop.dat
```

La regla es:

> **No asumir el nombre de la base vegetal. Usar siempre el archivo indicado por `PLANTDB` en el `file.cio` real del modelo.**

---

# 5. Regla de decisión: nueva cobertura vs. nuevo `PLANT_ID`

No toda nueva categoría conceptual requiere un nuevo `PLANT_ID`.

## 5.1 Mantener el mismo `PLANT_ID`

Usar el mismo `PLANT_ID` cuando la vegetación fisiológica sigue siendo la misma y únicamente cambia su condición o manejo.

Ejemplos conceptuales:

```text
Bosque -> bosque degradado
Pastura bien manejada -> pastura degradada
Bosque joven -> bosque maduro
```

En estos casos pueden cambiar parámetros de `.hru`, `.mgt`, condiciones iniciales y manejo, pero no necesariamente la fisiología de `plant.dat`.

---

## 5.2 Crear un nuevo `PLANT_ID`

Crear una nueva entrada en la base vegetal cuando se requiere representar una vegetación con parámetros fisiológicos propios, por ejemplo porque deben cambiar de forma explícita valores como:

```text
BIO_E
BLAI
CHTMX
RDMX
T_OPT
T_BASE
USLE_C
RSDCO_PL
MAT_YRS
BMX_TREES
EXT_COEF
...
```

Regla:

```text
¿La nueva cobertura necesita una fisiología vegetal diferente?

        NO  -> reutilizar PLANT_ID existente

        SI  -> crear nuevo ICNUM/PLANT_ID
```

---

# 6. Archivo `.hru`: parámetros relacionados con cobertura

El archivo `.hru` contiene parámetros de topografía, flujo, cobertura y erosión.

Para un cambio de cobertura es importante distinguir tres grupos.

---

## 6.1 Parámetros que forman directamente el perfil de cobertura superficial

### `CANMX`

**Maximum canopy storage [mm H2O].**

Representa el almacenamiento máximo de agua en el dosel cuando la vegetación está completamente desarrollada.

Está directamente relacionado con:

- densidad del dosel;
- morfología de la vegetación;
- intercepción de lluvia;
- evapotranspiración;
- generación de escorrentía.

### Regla

```text
CAMBIO DE COBERTURA -> REDEFINIR / VALIDAR CANMX
```

El valor debe provenir del perfil objetivo de cobertura.

---

### `OV_N`

**Manning's n for overland flow.**

Representa la rugosidad de la superficie para el flujo superficial.

Está directamente relacionada con:

- estructura superficial;
- vegetación;
- residuos;
- tipo de manejo de la superficie.

### Regla

```text
CAMBIO DE COBERTURA -> REDEFINIR / VALIDAR OV_N
```

---

### `RSDIN`

**Initial residue cover [kg/ha].**

Representa la cantidad inicial de residuo vegetal sobre la superficie.

### Regla

```text
CAMBIO DE COBERTURA -> REVISAR RSDIN
```

Debe modificarse cuando la cobertura objetivo tenga una condición inicial de residuos distinta.

Si no existe una justificación para cambiar el residuo inicial, no debe inventarse un valor.

---

# 7. Parámetros `.hru` que interactúan con la cobertura pero NO se sustituyen automáticamente

Estos parámetros pueden interactuar con la vegetación, pero no son por sí mismos identificadores de cobertura.

## `SLSUBBSN`

Longitud media de pendiente para flujo superficial.

Puede variar en algunos esquemas por cobertura o prácticas físicas, pero un simple cambio de vegetación no cambia automáticamente la longitud física de pendiente.

```text
Por defecto: CONSERVAR
```

Cambiar únicamente si la intervención modifica físicamente la longitud efectiva de flujo, por ejemplo mediante terrazas.

---

## `SLSOIL`

Longitud de pendiente para flujo lateral subsuperficial.

```text
Por defecto: CONSERVAR
```

---

## `HRU_SLP`

Pendiente media de la HRU.

```text
Por defecto: CONSERVAR
```

Una cobertura nueva no cambia la topografía.

---

## `EPCO`

**Plant uptake compensation factor.**

Controla la capacidad de la planta para compensar la absorción de agua entre capas del suelo.

Interactúa con la demanda de transpiración y el sistema radicular.

```text
Por defecto: CONSERVAR
```

Solo modificar si el perfil de cobertura objetivo define explícitamente un valor diferente.

---

## `ESCO`

**Soil evaporation compensation factor.**

Controla cómo se distribuye con la profundidad la evaporación del suelo.

```text
Por defecto: CONSERVAR
```

No debe modificarse únicamente porque cambie `PLANT_ID`.

---

## Parámetros `.hru` que no son parámetros de cobertura

No deben cambiarse por defecto:

```text
HRU_FR
LAT_TTIME
LAT_SED
ERORGN
ERORGP
POT_FR
FLD_FR
RIP_FR
POT_TILE
POT_VOLX
POT_VOL
POT_NSED
POT_NO3L
DEP_IMP
EV_POT
DIS_STREAM
CF
CFH
CFDEC
SED_CON
ORGN_CON
ORGP_CON
SOLN_CON
SOLP_CON
POT_SOLP
POT_K
```

Si alguno cambia, debe existir una razón de proceso diferente al simple cambio de cobertura vegetal.

---

# 8. Archivo `.mgt`: estructura relevante

El `.mgt` contiene dos secciones conceptuales:

```text
1. Condiciones iniciales y parámetros generales
2. Calendario de operaciones de manejo
```

Ambas deben revisarse cuando cambia la cobertura.

---

# 9. `.mgt` — parámetros iniciales de la vegetación

## `IGRO`

Código que indica si existe una cobertura creciendo al inicio de la simulación.

```text
0 = no hay cobertura creciendo al inicio
1 = existe cobertura creciendo al inicio
```

### Regla

Debe ser coherente con la condición inicial de la cobertura objetivo.

---

## `PLANT_ID`

Identificador numérico de la vegetación.

Debe cumplir:

```text
PLANT_ID (.mgt) == ICNUM (plant.dat/crop.dat)
```

Es el vínculo principal entre la HRU y el registro fisiológico de la planta.

### Regla

```text
CAMBIO DE TIPO VEGETAL -> ACTUALIZAR PLANT_ID
```

---

## `LAI_INIT`

Índice de área foliar inicial.

Se usa cuando:

```text
IGRO = 1
```

### Regla

Debe representar el estado inicial de la cobertura objetivo.

---

## `BIO_INIT`

Biomasa seca inicial [kg/ha].

Se usa cuando:

```text
IGRO = 1
```

### Regla

Debe representar la biomasa inicial de la cobertura objetivo.

---

## `PHU_PLT`

Unidades de calor totales necesarias para llevar la planta a madurez.

Se requiere cuando existe vegetación creciendo al inicio.

### Regla

Debe ser coherente con la planta y la condición inicial seleccionadas.

---

# 10. `.mgt` — parámetros generales relacionados con uso/cobertura y manejo

## `CN2`

**Initial SCS runoff curve number for moisture condition II.**

Es uno de los parámetros más importantes al cambiar cobertura.

El Curve Number depende de:

```text
uso/cobertura
+
grupo hidrológico del suelo
+
condición hidrológica
+
práctica o tratamiento
```

### Regla obligatoria

```text
CAMBIO DE COBERTURA -> REDEFINIR / VALIDAR CN2
```

No copiar un `CN2` de otra HRU sin comprobar que corresponde al mismo grupo hidrológico del suelo y a la condición de cobertura que se quiere representar.

### Recomendación para una biblioteca de coberturas

No guardar un único `CN2` por cobertura si la cobertura puede existir sobre distintos grupos hidrológicos.

Preferir una estructura como:

```text
CN2:
    HSG_A: ...
    HSG_B: ...
    HSG_C: ...
    HSG_D: ...
```

---

## `BIOMIX`

**Biological mixing efficiency.**

Representa mezcla biológica del suelo.

Está más relacionada con el sistema de manejo/disturbio que con la identidad de la planta.

```text
CAMBIO DE COBERTURA -> REVISAR SI CAMBIA EL SISTEMA DE MANEJO
```

No cambiar automáticamente.

---

## `USLE_P`

Factor de prácticas de conservación de USLE.

No debe confundirse con `USLE_C`.

```text
USLE_C -> base vegetal -> cobertura vegetal
USLE_P -> .mgt         -> práctica de conservación
```

### Regla

```text
CAMBIO DE COBERTURA -> REVISAR
```

Cambiar únicamente si la cobertura objetivo implica una práctica de conservación distinta.

---

## `BIO_MIN`

Biomasa mínima requerida para permitir pastoreo.

```text
RELEVANTE SOLO SI HAY GRAZING
```

Si la nueva cobertura no se pastorea, revisar/eliminar el manejo asociado.

---

## `FILTERW`

Ancho de franja filtrante en borde de campo [m].

No es una propiedad intrínseca de la planta.

```text
CAMBIO DE COBERTURA -> CONSERVAR SALVO QUE EL ESCENARIO CAMBIE LA FRANJA FILTRANTE
```

---

# 11. `.mgt` — parámetros de manejo especial

Estos parámetros no deben cambiarse automáticamente con toda cobertura, pero deben revisarse si la nueva cobertura cambia el sistema de manejo.

## Urbanización

```text
IURBAN
URBLU
```

Una conversión vegetal -> urbana o urbana -> vegetal requiere una rama específica.

No basta con cambiar `PLANT_ID`.

---

## Irrigación

```text
IRRSC
IRRNO
FLOWMIN
DIVMAX
FLOWFR
```

Revisar si el cambio de cobertura introduce, elimina o modifica irrigación.

---

## Drenaje subsuperficial

```text
DDRAIN
TDRAIN
GDRAIN
```

Revisar solo si la intervención cambia físicamente el drenaje subsuperficial.

---

# 12. Calendario de manejo: regla fundamental

El cambio de cobertura no termina con los parámetros de la cabecera del `.mgt`.

El agente debe inspeccionar **todas las operaciones programadas**.

Una HRU puede ser inconsistente si se cambia el `PLANT_ID` pero se mantienen operaciones heredadas de la cobertura anterior.

Ejemplo conceptual incorrecto:

```text
PLANT_ID = bosque
+
pastoreo de la pastura anterior
+
fertilización de la cobertura anterior
+
corte/cosecha de la cobertura anterior
```

SWAT puede ejecutar una combinación de este tipo sin que represente correctamente la cobertura deseada.

---

# 13. Operaciones `.mgt` que el agente debe revisar

Cada operación incluye una programación por fecha (`MONTH`, `DAY`) o por fracción de unidades de calor (`HUSC`) y un código `MGT_OP`.

## Planting / Beginning of growing season

Campos que pueden ser relevantes:

```text
MONTH
DAY
HUSC
MGT_OP
PLANT_ID
CURYR_MAT
HEAT_UNITS
LAI_INIT
BIO_INIT
HI_TARG
BIO_TARG
CNOP
```

### `CURYR_MAT`

Edad actual de una cobertura arbórea.

Relevante cuando la nueva cobertura es un árbol/bosque.

### `CNOP`

Curve Number asignado por una operación.

Es crítico porque puede reemplazar el efecto del `CN2` inicial.

---

## Irrigation operation

Revisar si la cobertura objetivo utiliza irrigación.

---

## Fertilizer application

Campos principales:

```text
FERT_ID
FRT_KG
FRT_SURFACE
```

Eliminar o reemplazar si el manejo de la nueva cobertura es diferente.

---

## Pesticide application

Campos principales:

```text
PEST_ID
PST_KG
PST_DEP
```

Eliminar o reemplazar si no corresponde al nuevo manejo.

---

## Harvest & Kill

Puede incluir:

```text
CNOP
HI_OVR
FRAC_HARVK
```

Debe revisarse cuando una cobertura anual, cultivo o pastura se convierte a perenne o bosque.

---

## Tillage

Campos principales:

```text
TILL_ID
CNOP
```

Eliminar si la nueva cobertura no está sometida a labranza.

---

## Harvest only

Puede utilizar parámetros como:

```text
HI_OVR
HARVEFF
```

Revisar cuando se eliminan cortes de heno u otras cosechas periódicas.

---

## Kill / end growing season

Finaliza el crecimiento y transfiere biomasa a residuos.

Debe ser coherente con la fenología y manejo de la nueva cobertura.

---

## Grazing

Campos principales:

```text
GRZ_DAYS
MANURE_ID
BIO_EAT
BIO_TRMP
MANURE_KG
```

Eliminar si la cobertura objetivo no tiene pastoreo.

---

## Auto irrigation

Revisar parámetros de activación, fuente y cantidad si la nueva cobertura usa o deja de usar irrigación automática.

---

## Auto fertilization

Campos relevantes pueden incluir:

```text
AFERT_ID
AUTO_NSTRS
AUTO_NAPP
AUTO_NYR
AUTO_EFF
AFRT_SURFACE
```

Revisar si el manejo objetivo usa o no autofertilización.

---

## Street sweeping

Solo corresponde a manejo urbano.

---

## Release / impound

Relacionado con manejo de almacenamiento/impoundment.

No debe trasladarse automáticamente entre coberturas.

---

## Continuous fertilizer

Campos principales:

```text
FERT_DAYS
CFRT_ID
IFRT_FREQ
CFRT_KG
```

---

## Continuous pesticide

Campos principales:

```text
CPST_ID
PEST_DAYS
IPEST_FREQ
CPST_KG
```

---

## Burn

Campo principal:

```text
BURN_FRLB
```

Mantener únicamente si la quema forma parte del manejo objetivo.

---

## Skip a year

Se utiliza en rotaciones multianuales y puede ser relevante para manejo forestal.

Debe conservarse o reconstruirse según la secuencia objetivo.

---

# 14. Regla de `CN2` y `CNOP`

El agente debe tratar `CN2` y `CNOP` como un sistema.

```text
CN2 = Curve Number inicial
CNOP = Curve Number impuesto por una operación posterior
```

Si nunca aparece un `CNOP`, `CN2` puede permanecer como referencia durante la simulación.

Si existen operaciones con `CNOP`, el agente debe revisar **todos** los `CNOP` del calendario.

Por tanto:

> **No basta con actualizar `CN2` si el calendario de manejo posteriormente vuelve a imponer un Curve Number de la cobertura anterior mediante `CNOP`.**

---

# 15. Base vegetal `plant.dat` / `crop.dat`

La base vegetal contiene la fisiología y los parámetros de crecimiento de cada cobertura/planta.

La relación es:

```text
.mgt
PLANT_ID = X
      |
      v
plant.dat / crop.dat
ICNUM = X
```

Cuando una cobertura ya existe:

```text
NO modificar su registro global
```

porque todas las HRU que utilicen ese `PLANT_ID` comparten la misma definición fisiológica.

---

# 16. Estructura completa de una entrada de `plant.dat`

Una entrada vegetal de SWAT2012 utiliza cinco líneas de parámetros.

```text
LINEA 1
ICNUM CPNM IDC

LINEA 2
BIO_E HVSTI BLAI FRGRW1 LAIMX1 FRGRW2 LAIMX2 DLAI CHTMX RDMX

LINEA 3
T_OPT T_BASE CNYLD CPYLD PLTNFR(1) PLTNFR(2) PLTNFR(3) PLTPFR(1) PLTPFR(2) PLTPFR(3)

LINEA 4
WSYF USLE_C GSI VPDFR FRGMAX WAVP CO2HI BIOEHI RSDCO_PL ALAI_MIN

LINEA 5
BIO_LEAF MAT_YRS BMX_TREES EXT_COEF BMDIEOFF RSR1C RSR2C
```

Cuando el agente crea una nueva cobertura fisiológica, debe definir **el registro completo**, no solo algunos parámetros.

---

# 17. Inventario completo de parámetros de la base vegetal

## Línea 1 — Identidad y clase funcional

| Parámetro | Función |
|---|---|
| `ICNUM` | Identificador numérico único. Es el valor utilizado como `PLANT_ID` en `.mgt`. |
| `CPNM` | Código corto único de cuatro caracteres para la cobertura/planta. |
| `IDC` | Clase funcional de la planta. |

### Valores de `IDC`

```text
1 = warm season annual legume
2 = cold season annual legume
3 = perennial legume
4 = warm season annual
5 = cold season annual
6 = perennial
7 = tree
```

---

## Línea 2 — Biomasa, desarrollo foliar, altura y raíces

| Parámetro | Función |
|---|---|
| `BIO_E` | Eficiencia de uso de radiación / biomass-energy ratio. |
| `HVSTI` | Harvest index bajo condiciones óptimas. |
| `BLAI` | Máximo índice de área foliar potencial. |
| `FRGRW1` | Primera fracción de la temporada/unidades de calor para la curva de LAI. |
| `LAIMX1` | Fracción de LAI máximo correspondiente a `FRGRW1`. |
| `FRGRW2` | Segunda fracción de la temporada/unidades de calor para la curva de LAI. |
| `LAIMX2` | Fracción de LAI máximo correspondiente a `FRGRW2`. |
| `DLAI` | Fracción de la temporada a partir de la cual comienza a disminuir el LAI. |
| `CHTMX` | Altura máxima del dosel [m]. |
| `RDMX` | Profundidad máxima de raíces [m]. |

---

## Línea 3 — Temperatura y nutrientes

| Parámetro | Función |
|---|---|
| `T_OPT` | Temperatura óptima para crecimiento. |
| `T_BASE` | Temperatura base mínima para crecimiento. |
| `CNYLD` | Fracción normal de N en el rendimiento. |
| `CPYLD` | Fracción normal de P en el rendimiento. |
| `PLTNFR(1)` | Fracción normal de N en biomasa al inicio/emergencia. |
| `PLTNFR(2)` | Fracción normal de N en biomasa alrededor de 50% de madurez. |
| `PLTNFR(3)` | Fracción normal de N en biomasa a madurez. |
| `PLTPFR(1)` | Fracción normal de P en biomasa al inicio/emergencia. |
| `PLTPFR(2)` | Fracción normal de P en biomasa alrededor de 50% de madurez. |
| `PLTPFR(3)` | Fracción normal de P en biomasa a madurez. |

---

## Línea 4 — Estrés, erosión, estomas, CO2, residuos y dormancia

| Parámetro | Función |
|---|---|
| `WSYF` | Límite inferior del harvest index bajo estrés. |
| `USLE_C` | Valor mínimo del factor C de USLE asociado a la cobertura/planta. |
| `GSI` | Conductancia estomática máxima. |
| `VPDFR` | Déficit de presión de vapor usado en la curva de respuesta estomática. |
| `FRGMAX` | Fracción de conductancia estomática máxima asociada a `VPDFR`. |
| `WAVP` | Respuesta de la eficiencia de uso de radiación al déficit de presión de vapor. |
| `CO2HI` | Segundo punto de concentración de CO2 para la curva de respuesta. |
| `BIOEHI` | Biomass-energy ratio correspondiente a `CO2HI`. |
| `RSDCO_PL` | Coeficiente de descomposición de residuos de la planta. |
| `ALAI_MIN` | LAI mínimo durante dormancia para perennes/árboles. |

---

## Línea 5 — Parámetros arbóreos, dosel y raíces

| Parámetro | Función |
|---|---|
| `BIO_LEAF` | Fracción de biomasa arbórea convertida a residuo foliar durante dormancia. |
| `MAT_YRS` | Años necesarios para que una especie arbórea alcance desarrollo completo. |
| `BMX_TREES` | Biomasa máxima de un bosque maduro. |
| `EXT_COEF` | Coeficiente de extinción de luz del dosel. |
| `BMDIEOFF` | Fracción de biomasa aérea que muere durante dormancia. |
| `RSR1C` | Relación raíz/parte aérea al inicio de la temporada. |
| `RSR2C` | Relación raíz/parte aérea al final de la temporada. |

---

# 18. `USLE_C` y `USLE_P`: no confundir

Esta diferencia debe estar codificada explícitamente en el agente.

```text
USLE_C
    -> base vegetal
    -> propiedad de cobertura/planta

USLE_P
    -> .mgt
    -> práctica de conservación
```

Por tanto:

- al cambiar `PLANT_ID`, la HRU pasa a utilizar el `USLE_C` del nuevo registro vegetal;
- `USLE_P` no debe cambiar automáticamente salvo que también cambie la práctica de conservación.

---

# 19. Reglas para crear un nuevo `ICNUM` / `PLANT_ID`

## 19.1 Debe ser entero positivo

```text
ICNUM > 0
```

---

## 19.2 Debe ser único

No pueden existir dos registros con el mismo `ICNUM`.

---

## 19.3 `CPNM` debe ser único

`CPNM` es un código de cuatro caracteres.

Ejemplos:

```text
FRST   válido
RSTF   válido
FOREST no válido como CPNM de cuatro caracteres
```

El nombre descriptivo largo debe mantenerse en la aplicación, no en sustitución del código SWAT.

---

## 19.4 Política de numeración para SWAT2012 rev. 670

Para evitar problemas con la implementación Fortran y mantener la base compacta, el agente debe usar siempre:

```text
new_plant_id = max(ICNUM existentes) + 1
```

Ejemplo:

```text
...
127
128
129
130
131 <- nueva cobertura
```

No usar identificadores altos arbitrarios dejando grandes huecos, por ejemplo:

```text
...
130
1500
```

si los identificadores intermedios no existen.

### Regla operacional

```text
ICNUM únicos
+
ordenados
+
compactos
+
consecutivos
```

---

# 20. Qué parámetros deben cambiar al convertir una cobertura vegetal existente

El agente debe trabajar con un **perfil objetivo de cobertura**.

## 20.1 Parámetros que deben definirse o validarse siempre

### `.hru`

```text
CANMX
OV_N
RSDIN  <- según condición inicial
```

### `.mgt`

```text
IGRO
PLANT_ID
LAI_INIT   <- si IGRO = 1
BIO_INIT   <- si IGRO = 1
PHU_PLT    <- si IGRO = 1
CN2
```

### Calendario `.mgt`

```text
PLANT_ID de operaciones de plantación
CURYR_MAT cuando aplique
CNOP donde exista
operaciones de manejo completas
```

---

## 20.2 Parámetros que deben revisarse según manejo

```text
BIOMIX
USLE_P
BIO_MIN
FILTERW
IURBAN
URBLU
IRRSC
IRRNO
FLOWMIN
DIVMAX
FLOWFR
DDRAIN
TDRAIN
GDRAIN
```

Además de todas las operaciones programadas de:

```text
planting
growing season
irrigation
fertilizer
pesticide
harvest & kill
tillage
harvest
kill
grazing
auto irrigation
auto fertilization
street sweeping
release/impound
continuous fertilizer
continuous pesticide
burn
skip year
```

---

## 20.3 Parámetros que normalmente se conservan

En `.hru`:

```text
HRU_FR
SLSUBBSN
SLSOIL
HRU_SLP
LAT_TTIME
LAT_SED
ESCO
EPCO
ERORGN
ERORGP
```

salvo que el escenario defina explícitamente una razón física para modificarlos.

---

# 21. Flujo del agente — cambiar hacia una cobertura existente

```text
INPUT:
    HRU objetivo
    cobertura objetivo

1. Localizar .hru y .mgt de la HRU.

2. Leer file.cio y determinar PLANTDB.

3. Buscar la cobertura objetivo en la base vegetal.

4. Obtener su ICNUM -> será el PLANT_ID objetivo.

5. Actualizar .hru:
       CANMX
       OV_N
       RSDIN si corresponde

6. Actualizar .mgt:
       IGRO
       PLANT_ID
       LAI_INIT si corresponde
       BIO_INIT si corresponde
       PHU_PLT si corresponde
       CN2

7. Revisar todo el calendario de operaciones.

8. Reemplazar/eliminar operaciones incompatibles con la nueva cobertura.

9. Revisar todos los CNOP.

10. NO modificar plant.dat/crop.dat.

11. NO modificar suelo, groundwater, canales, subcuenca o geometría.

12. Validar archivos antes de ejecutar SWAT.
```

---

# 22. Flujo del agente — crear una cobertura nueva

```text
INPUT:
    definición de nueva cobertura
    parámetros fisiológicos
    parámetros de superficie
    parámetros de manejo

1. Leer file.cio y localizar PLANTDB.

2. Leer todos los ICNUM existentes.

3. Crear:
       new_id = max(ICNUM) + 1

4. Crear CPNM único de cuatro caracteres.

5. Definir IDC correcto.

6. Escribir el registro completo de cinco líneas en plant.dat/crop.dat:
       línea 1
       línea 2
       línea 3
       línea 4
       línea 5

7. No inventar parámetros faltantes.

8. Definir perfil .hru:
       CANMX
       OV_N
       RSDIN

9. Definir perfil .mgt:
       IGRO
       PLANT_ID = new_id
       LAI_INIT
       BIO_INIT
       PHU_PLT
       CN2
       parámetros de manejo que correspondan

10. Construir o actualizar el calendario de operaciones.

11. Revisar CNOP.

12. Aplicar el perfil únicamente a las HRU seleccionadas.

13. Validar referencias y formatos.
```

---

# 23. Validaciones obligatorias antes de ejecutar SWAT

El agente debe fallar antes de ejecutar si detecta una inconsistencia estructural.

## 23.1 Referencias de planta

Para cada `PLANT_ID` utilizado:

```text
PLANT_ID debe existir como ICNUM
```

Esto aplica tanto al encabezado del `.mgt` como a operaciones de plantación.

---

## 23.2 Unicidad

Verificar:

```text
ICNUM sin duplicados
CPNM sin duplicados
```

---

## 23.3 Secuencia de IDs

Si el agente crea nuevos registros:

```text
new_id = max + 1
```

No introducir huecos arbitrarios.

---

## 23.4 Integridad de `plant.dat`

Cada nueva planta debe contener las cinco líneas completas y el número correcto de valores por línea.

No desplazar columnas o registros existentes.

---

## 23.5 Coherencia fisiológica

Verificar compatibilidad entre:

```text
IDC
parámetros fisiológicos
MAT_YRS
BMX_TREES
BIO_LEAF
ALAI_MIN
```

Por ejemplo, una cobertura arbórea debe usar una clase funcional y parámetros arbóreos coherentes.

---

## 23.6 Coherencia entre archivos

Verificar como conjunto:

```text
PLANT_ID
IGRO
LAI_INIT
BIO_INIT
PHU_PLT
CN2
CNOP
CANMX
OV_N
RSDIN
manejo
```

No validar cada parámetro de forma aislada.

---

## 23.7 Manejo incompatible

El agente debe detectar y marcar operaciones heredadas que no correspondan a la nueva cobertura, especialmente:

```text
grazing
harvest
harvest & kill
tillage
fertilization
pesticide
irrigation
burn
```

---

## 23.8 `CN2` / `CNOP`

Verificar que:

```text
CN2 corresponde a la cobertura objetivo y al grupo hidrológico del suelo
```

Y, si existen `CNOP`:

```text
ningún CNOP reintroduce accidentalmente la condición de la cobertura anterior
```

---

# 24. Regla de no invención

El agente no debe inventar silenciosamente parámetros de una nueva cobertura.

Si falta cualquier valor requerido para:

```text
plant.dat/crop.dat
.hru
.mgt
manejo
```

se debe:

```text
1. buscar una fuente o cobertura análoga explícitamente autorizada;
2. solicitar el valor al usuario; o
3. detener la creación de la cobertura y reportar el parámetro faltante.
```

No rellenar valores arbitrarios únicamente para conseguir que SWAT ejecute.

---

# 25. Casos especiales que NO deben resolverse únicamente con `PLANT_ID`

El protocolo vegetal estándar no es suficiente cuando la cobertura objetivo implica alguno de estos sistemas:

## Cobertura urbana

Puede requerir:

```text
IURBAN
URBLU
urban.dat
```

## Sistema séptico

Puede requerir archivos y parámetros específicos de septic.

## Cuerpo de agua

No debe tratarse automáticamente como una planta.

## Humedal como objeto de almacenamiento

No es equivalente a una HRU vegetal con código de humedal.

## Pothole / impoundment

Requiere parámetros específicos de almacenamiento.

## Cambio de suelo

Requiere modificar el componente de suelo y queda fuera de un cambio puro de cobertura.

## Cambio de drenaje subsuperficial

Requiere modificar explícitamente los parámetros de drenaje.

### Regla

```text
Si el nuevo uso cambia el tipo de objeto funcional de SWAT,
NO aplicar automáticamente el flujo estándar plant.dat + .hru + .mgt.
```

---

# 26. Contrato de escritura recomendado para el agente

## Cambio de cobertura vegetal existente

```text
WRITE:
    HRU_target.hru
    HRU_target.mgt

READ ONLY:
    file.cio
    PLANTDB
    *.sol u otros archivos necesarios para contexto
```

## Nueva cobertura fisiológica

```text
WRITE:
    PLANTDB
    HRU_target.hru
    HRU_target.mgt

READ ONLY:
    file.cio
    archivos de contexto
```

## Nunca por defecto

```text
WRITE *.sol
WRITE *.gw
WRITE *.sub
WRITE *.rte
WRITE *.bsn
```

---

# 27. Esquema de datos recomendado para una aplicación

Para evitar que una cobertura se reduzca únicamente a un `PLANT_ID`, cada cobertura debería representarse como un perfil.

Ejemplo conceptual:

```yaml
land_cover:
  code: XXXX
  name: Nombre descriptivo

  plant:
    plant_id: 123

  hru:
    CANMX: ...
    OV_N: ...
    RSDIN: ...

  mgt_initial:
    IGRO: ...
    LAI_INIT: ...
    BIO_INIT: ...
    PHU_PLT: ...

  curve_number:
    HSG_A: ...
    HSG_B: ...
    HSG_C: ...
    HSG_D: ...

  management:
    BIOMIX: ...
    USLE_P: ...
    operations:
      - ...
```

Si la cobertura crea una nueva planta, añadir:

```yaml
  plant_database_record:
    ICNUM: ...
    CPNM: ...
    IDC: ...
    BIO_E: ...
    HVSTI: ...
    BLAI: ...
    FRGRW1: ...
    LAIMX1: ...
    FRGRW2: ...
    LAIMX2: ...
    DLAI: ...
    CHTMX: ...
    RDMX: ...
    T_OPT: ...
    T_BASE: ...
    CNYLD: ...
    CPYLD: ...
    PLTNFR1: ...
    PLTNFR2: ...
    PLTNFR3: ...
    PLTPFR1: ...
    PLTPFR2: ...
    PLTPFR3: ...
    WSYF: ...
    USLE_C: ...
    GSI: ...
    VPDFR: ...
    FRGMAX: ...
    WAVP: ...
    CO2HI: ...
    BIOEHI: ...
    RSDCO_PL: ...
    ALAI_MIN: ...
    BIO_LEAF: ...
    MAT_YRS: ...
    BMX_TREES: ...
    EXT_COEF: ...
    BMDIEOFF: ...
    RSR1C: ...
    RSR2C: ...
```

---

# 28. Resumen operativo

## Para cambiar una cobertura existente

```text
1. Identificar HRU.
2. Localizar .hru y .mgt.
3. Leer PLANTDB desde file.cio.
4. Obtener ICNUM de la cobertura objetivo.
5. Cambiar/validar CANMX, OV_N y RSDIN.
6. Cambiar/validar IGRO, PLANT_ID, LAI_INIT, BIO_INIT, PHU_PLT y CN2.
7. Revisar todo el manejo.
8. Revisar todos los CNOP.
9. No modificar plant.dat si la planta ya existe.
10. No modificar suelo, acuífero, canal, subcuenca o geometría.
11. Validar y ejecutar.
```

## Para crear una cobertura nueva

```text
1. Confirmar que realmente necesita una nueva fisiología vegetal.
2. Leer PLANTDB.
3. Crear ICNUM = max + 1.
4. Crear CPNM único de cuatro caracteres.
5. Definir IDC.
6. Definir TODOS los parámetros del registro vegetal.
7. Añadir las cinco líneas completas a PLANTDB.
8. Definir CANMX, OV_N y RSDIN.
9. Definir IGRO, PLANT_ID, LAI_INIT, BIO_INIT, PHU_PLT y CN2.
10. Definir manejo y operaciones.
11. Revisar CNOP.
12. Validar referencias.
13. Ejecutar.
```

---

# 29. Regla final

El agente debe interpretar una cobertura como:

```text
COBERTURA SWAT
=
FISIOLOGIA VEGETAL
+
CONDICION INICIAL
+
RESPUESTA HIDROLOGICA SUPERFICIAL
+
MANEJO
```

No como:

```text
COBERTURA SWAT = etiqueta Luse
```

ni como:

```text
COBERTURA SWAT = solamente PLANT_ID
```

Para una cobertura vegetal estándar, los archivos que controlan estos componentes son principalmente:

```text
plant.dat / crop.dat  -> fisiología vegetal
.hru                   -> superficie/dosel/residuos
.mgt                   -> planta activa, CN y manejo
```

Ese conjunto debe mantenerse internamente coherente en toda modificación.

---

# 30. Referencias técnicas base

Este protocolo se basa en la estructura estándar documentada para SWAT2012 y en la lógica de SWAT2012 rev. 670. Para validación técnica, consultar principalmente:

- **SWAT2012 Input/Output Documentation — Chapter 3: `file.cio`**.
- **SWAT2012 Input/Output Documentation — Chapter 14: plant/crop database**.
- **SWAT2012 Input/Output Documentation — Chapter 19: `.hru`**.
- **SWAT2012 Input/Output Documentation — Chapter 20: `.mgt`**.
- **SWAT2012 Fortran source code, revision 670**, para reglas de lectura e indexación de la base vegetal.

