# Investigación de desviaciones en mediciones UWB — 2026-09-10

> **Propósito:** documentar la investigación de dos problemas reales
> encontrados en mediciones contra hardware (desviación estándar alta y
> mediciones incorrectas), qué se descartó con evidencia, qué causa se
> confirmó y arregló, y qué queda pendiente.
> **Alcance:** sesión de trabajo del 2026-09-10 sobre
> `environments/sala_20.toml` (5 nodos reales). Punto de partida para
> continuar la investigación del problema aún abierto (§4).

---

## 1. Resumen ejecutivo

Se reportaron tres síntomas en corridas reales de `imop-measure run`:

1. **Iniciador "pegado" al primer destino**: un nodo usado como iniciador
   contra varios respondedores (dentro de una misma campaña) reportaba
   casi el mismo valor sin importar el respondedor real. **Causa
   confirmada.** Un primer intento de fix (`power_cycle()` del módulo
   Qorvo sobre la conexión reusada) resultó insuficiente — el fix real
   fue dejar de reusar la conexión BLE del iniciador entre direcciones
   (ver §3, en particular §3.2 vs §3.3).
2. **Desviación estándar alta** en algunas direcciones (hasta ~56 cm),
   apareciendo solo dentro de campañas completas, nunca en pruebas
   aisladas de un solo par. **Sigue sin causa confirmada** (§4) — es el
   punto de partida para continuar esta investigación.
3. **Fallas de conexión BLE** intermitentes contra distintos nodos.
   Descriptas en §5, sin causa de fondo identificada (parece
   inestabilidad genérica del stack BLE de Windows).

## 2. Hipótesis descartadas (con evidencia)

Todas verificadas contra hardware real (`environments/sala_20.toml`, 5
nodos: `UWB-Node-4/6/8/10/11`):

| Hipótesis | Método de verificación | Resultado |
|---|---|---|
| Crosstalk de notificaciones entre sesiones | Se capturó el `mac_address` crudo de cada muestra `SESSION_INFO_NTF` y se comparó contra el respondedor esperado | Descartada — el `mac_address` fue siempre el correcto en las direcciones con desviación alta |
| Interferencia WiFi / problema de scheduling del protocolo | Se activó `DIAG 1` y se capturó `RANGE_DIAGNOSTICS_NTF` (nuevo, ver §6) en los eventos de salto | Descartada — `WIFI_COEX` y `GRANT_DURATION_EXCEEDED` dieron `False` en todos los casos capturados |
| Desincronización de reloj entre chips | Mismo `RANGE_DIAGNOSTICS_NTF`, campo `cfo_ppm` | Descartada — valores normales (0.1–0.9 ppm) en todos los casos |
| Multipath/NLOS fijo por la posición física de un par puntual | +200 muestras aisladas contra el mismo par (N8↔N10) en 10 conexiones separadas | Descartada — nunca se reprodujo el salto en aislamiento, solo en campañas completas |
| El `STAT` periódico de keepalive al respondedor (`_keep_responder_alive`) interrumpe la sesión | Prueba A/B controlada: 16 corridas, keepalive ON vs OFF alternado, mismas 4 direcciones | Descartada — sin diferencia medible (std promedio 3.08cm ON vs 3.68cm OFF), 0/16 con salto en cualquiera de las dos condiciones |
| Calibración de antena (`ant0.ch9.ant_delay`) distinta/rota en algún nodo | Lectura real (`LISTCAL`) de los 5 nodos | Descartada — todos en un rango de 53 unidades (16362–16415), consistente entre sí |
| ID de sesión (`-ID=`) fijo causando que el firmware "continúe" la sesión anterior | Se varió `-ID=` (42, 43, 44) entre destinos con el iniciador reusado | Descartada — el problema persistió igual con IDs distintos |

> **Nota histórica importante:** la verificación original de que el
> keepalive era inofensivo (documentada en
> [protocolo-ble-qorvo.md](protocolo-ble-qorvo.md) §3.1, fechada
> 2026-09-08) se hizo **un día antes** de que existiera el canal BLE
> dedicado de streaming (`I-mop-nrf52840-fw` v0.3.0, 2026-09-09) — con
> otra arquitectura de lectura de notificaciones. Se corrigió el doc y se
> repitió la verificación contra el firmware actual (ver tabla arriba).
> Moraleja para quien retome esto: **revisar siempre la fecha de una
> verificación contra la fecha del firmware/arquitectura vigente** antes
> de confiar en ella.

## 3. Causa confirmada y arreglada: iniciador sin power-cycle entre respondedores

### 3.1 Reproducción

`ranging.campaign.run_campaign` reusa la conexión BLE del iniciador entre
todos los respondedores de su grupo (por costo de reconexión, ver
`ranging/campaign.py`). Entre una dirección y la siguiente, solo se manda
`STOP` + un `INITF` nuevo con `-PADDR=` distinto — **nunca se apaga el
módulo Qorvo**.

Prueba mínima (UWB-Node-11 como iniciador, contra N4, N6, N8 en la misma
conexión, sin apagar entre medio):

```
N11 -> N4 (esperado 0x0004): mac_address vistos = {'0x0004'}   OK
N11 -> N6 (esperado 0x0006): mac_address vistos = {'0x0004'}   MAL (30/30)
N11 -> N8 (esperado 0x0008): mac_address vistos = {'0x0004'}   MAL (30/30)
```

Una vez que el iniciador mide contra el primer respondedor, se queda
"pegado" ahí indefinidamente: todas las direcciones siguientes del mismo
grupo reportan el `mac_address` y la distancia del primer respondedor, sin
importar el `-PADDR=` nuevo que se le mande. Se confirmó con logging
`DEBUG` que el comando `INITF` enviado por software es **correcto** en las
3 llamadas (`-PADDR=4`, `-PADDR=6`, `-PADDR=8` respectivamente) — el bug
es del lado del firmware del Qorvo, no del código de este proyecto.
También se descartó que fuera un buffer/cola de Python con datos viejos:
cada conexión nueva crea un `BleTransport` con colas (`_rx_queue`,
`_stream_queue`) recién instanciadas (`queue.Queue()` en `__init__`, ver
[ble_link.py](../src/imop_measure/transport/ble_link.py)).

### 3.2 Primer intento de fix — insuficiente (v0.1.0)

Apagar y volver a prender el módulo Qorvo (`qorvo off` + 2s + `qorvo on`,
`BleTransport.power_cycle()`) antes de cada dirección, **sobre la misma
conexión BLE ya abierta** del iniciador reusado, pareció arreglarlo: una
campaña completa (20 direcciones, 5 nodos) dio medias distintas por cada
destino en todos los iniciadores:

```
Node-4  (iniciador) contra 4 destinos: medias=[168.2, 164.2, 166.8, 180.0]  rango=15.8cm
Node-6  (iniciador) contra 4 destinos: medias=[169.3, 169.8, 148.2, 247.7]  rango=99.5cm
Node-8  (iniciador) contra 4 destinos: medias=[351.6, 350.5, 350.5, 315.2]  rango=36.3cm
Node-10 (iniciador) contra 4 destinos: medias=[267.7, 268.2, 250.9, 269.1]  rango=18.2cm
Node-11 (iniciador) contra 4 destinos: medias=[200.3, 201.6, 200.1, 226.3]  rango=26.2cm
```

> **[2026-09-10, corregido] Esta verificación fue una falsa alarma
> positiva**: solo miraba que las *medias* fueran distintas entre
> destinos, nunca volvió a chequear el `mac_address` crudo de las
> muestras dentro de un grupo con conexión reusada después de agregar
> `power_cycle()`. Al usar la app real (GUI) se siguieron viendo
> asimetrías imposibles entre direcciones del mismo par físico (ej.
> `N4→N8` daba 1.674 m pero `N8→N4` daba 3.510 m). Reproducido de forma
> controlada con `mac_address` (grupo completo de Node-4, conexión
> reusada, `power_cycle()` incluido antes de cada dirección):
>
> ```
> N4 -> N6:  mac_address={'0x0006'}                      OK (primera del grupo)
> N4 -> N8:  mac_address={'0x0006'}  30/30 MAL            <- pegado en N6
> N4 -> N10: mac_address={'0x0006'}  30/30 MAL            <- pegado en N6
> N4 -> N11: mac_address={'0x0011','0x0006'} 28/30 MAL    <- casi todo pegado en N6
> ```
>
> Conclusión: **apagar/prender el módulo Qorvo sobre una conexión BLE que
> se mantiene abierta no alcanza.** El estado "pegado" no vive solo en el
> chip Qorvo — algo del lado de la sesión BLE/puente tampoco se resetea
> con un power-cycle del módulo. Ver §3.3 para el fix real.

### 3.3 Fix real (v0.1.1): dejar de reusar la conexión del iniciador

`ranging.campaign.run_campaign` dejó de agrupar direcciones por iniciador
y de reusar su conexión (`open_initiator`/`close_initiator` una vez por
grupo, ver versión anterior de `campaign.py`). Ahora llama
`ranging.pair_runner.run_pair` una vez por cada dirección — conecta y
desconecta el iniciador **por completo** (reconexión BLE real, no solo
`power_cycle()` del módulo) en cada una, igual que ya hacía con el
respondedor.

Verificado con `mac_address`: repitiendo la misma prueba aislada
(conexión nueva de punta a punta por dirección, sin reusar nada) da
resultados simétricos y correctos —
`N8→N4` y `N4→N8` dieron ambas ~349cm, `mac_address` correcto en el
100% de las 60 muestras.

- Costo: la conexión BLE del iniciador (~10-20s) se paga en cada
  dirección en vez de una vez por nodo — una campaña de 5 nodos tarda
  sensiblemente más. Deliberado (pedido explícito del usuario: preferir
  una campaña más lenta a mediciones contaminadas).
- Se mantiene además el `power_cycle()` de §3.2 como capa extra
  (se hace un fresh-connect *y* un power-cycle explícito antes de medir).
- `ranging.pair_runner.open_initiator`/`close_initiator`/
  `run_directed_measurement` siguen existiendo (`run_pair` los usa
  internamente para una sola dirección) — lo que cambió es que
  `campaign.py` ya no comparte un mismo `InitiatorHandle` entre varias
  llamadas.

> **Pendiente de verificar con una campaña completa real tras este
> cambio** (ver §4 más abajo si esta sección todavía no se actualizó con
> ese resultado).

## 4. Problema abierto: desviación estándar alta (sin causa confirmada)

**Este es el punto de partida para continuar la investigación.**

En la misma campaña de verificación del fix (§3.3, ya con el power-cycle
aplicado), **7 de 20 direcciones (35%) siguen mostrando std > 10cm**:

| Dirección | mean (cm) | std (cm) |
|---|---|---|
| N4 → N11 | 180.0 | 16.89 |
| N6 → N10 | 148.2 | 11.24 |
| N8 → N11 | 315.2 | **48.41** |
| N10 → N4 | 267.7 | 17.80 |
| N10 → N6 | 268.2 | 19.22 |
| N10 → N8 | 250.9 | 12.91 |
| N11 → N10 | 226.3 | 32.18 |

### 4.1 Lo que ya se sabe de este problema

- **Solo aparece en campañas completas** (varias direcciones corridas
  seguidas), nunca en pruebas aisladas de un par — ni siquiera con +200
  muestras acumuladas contra el mismo par (N8↔N10) en 10 conexiones
  separadas.
- Las muestras "malas" dentro de una dirección afectada no son ruido
  disperso: forman un **bloque de valores estables y cercanos entre sí**
  (ej. 6-9 muestras seguidas saltando a un valor ~100cm distinto del
  resto), como si el radio enganchara brevemente un valor equivocado
  pero consistente, no ruido aleatorio.
- Con diagnóstico `RANGE_DIAGNOSTICS_NTF` activo en los eventos
  capturados: `mac_address` correcto, `WIFI_COEX`/`GRANT_DURATION_EXCEEDED`
  en `False`, `cfo_ppm` normal, RSSI similar entre muestras "buenas" y
  "malas" — es decir, **no hay ninguna señal de diagnóstico del propio
  firmware que explique el salto** (ver tabla de descartes §2).
  Importante: estos diagnósticos se capturaron en corridas *previas* al
  fix del power-cycle (§3) — no se repitió esa captura específica después
  del fix; sería un buen primer paso al retomar esto (ver §4.2).
- Los dispositivos están en línea de vista directa, sin obstáculos físicos
  (confirmado por el usuario) — pesa en contra de un NLOS/multipath
  "clásico" por bloqueo geométrico, aunque no lo descarta del todo (un
  reflector fuerte en la sala podría competir con el camino directo
  incluso en LOS).
- No correlaciona de forma reproducible con un nodo específico: en
  distintas corridas del día aparecieron picos en direcciones de Node-4,
  Node-6, Node-8, Node-10 y Node-11 por turnos, no siempre el mismo.

> **[2026-09-10] Hipótesis a reevaluar tras el fix real de §3.3**: en la
> reproducción del bug de §3.2 (Node-4, conexión reusada, `mac_address`
> capturado), la dirección `N4→N11` mostró una **mezcla** de
> `mac_address` correcto e incorrecto (28/30 pegado en N6, 2/30 ya
> correcto en N11) — es decir, el estado "pegado" a veces se rompe a
> mitad de una dirección, no es todo-o-nada. Eso produciría exactamente
> el patrón de §4.1 (bloque de muestras estables "malas" + el resto
> "buenas", desviación alta) **sin que sea multipath ni ninguna de las
> hipótesis descartadas en §2** — sería el mismo bug de §3, en su forma
> parcial/transicional. Falta confirmar esto corriendo una campaña
> completa con el fix real de §3.3 aplicado y viendo si el problema 2
> desaparece o se reduce — si es así, quedaría todo unificado bajo una
> sola causa.

### 4.2 Próximos pasos sugeridos

1. **Repetir la captura con `RANGE_DIAGNOSTICS_NTF` activo, ya con el fix
   de power-cycle aplicado**, para confirmar que los mismos diagnósticos
   (`WIFI_COEX`/`GRANT_DURATION_EXCEEDED`/`cfo_ppm`/RSSI) siguen sin
   mostrar nada anómalo en los eventos de salto post-fix — no se
   descartó la posibilidad de que el power-cycle haya cambiado algo en
   el patrón de las muestras contaminadas en sí (aunque no en su
   frecuencia).
2. Revisar si hay un **reflector físico dominante** en la sala (pared,
   mueble metálico, puerta) cuya distancia de rebote coincida con los
   valores "malos" observados — varios saltos de distintos pares cayeron
   sospechosamente cerca de distancias reales medidas entre *otros*
   pares en la misma campaña.
3. Considerar si el patrón de "bloque de muestras consecutivas
   contaminadas" tiene relación con el **orden de arranque de sesión**
   (las primeras rondas tras un `INITF`/`RESPF` recién iniciado) — dos de
   los cuatro eventos capturados con diagnóstico completo ocurrieron
   temprano en su ventana de muestreo.
4. Si no se encuentra la causa de raíz en un tiempo razonable, considerar
   una mitigación práctica en `report/build.py` (filtrado de outliers o
   mediana en vez de promedio) documentando explícitamente que es un
   paliativo, no una corrección de causa.

## 5. Fallas de conexión BLE (sin causa de fondo)

Fallas duras (no solo reintentos transitorios resueltos solos) registradas
en las campañas completas del día:

| Corrida | Direcciones | Fallas |
|---|---|---|
| Campaña con diagnóstico DIAG | 20 | 3 (N6→N4, N8→N11, N10→N8) |
| Campaña con settle de 2s | 20 | 3 (N4→N8, N6→N8, N11→N8) |
| A/B test keepalive | 16 | 4 (2 ON, 2 OFF) |
| Campaña de verificación del primer intento de fix (§3.2) | 20 | 0 |

Todas fallaron con el mismo error transitorio de Windows
(`WinError -2147023673`, "El usuario ha cancelado la operación") o
`TransportError: conexion BLE perdida esperando respuesta`, sin patrón
claro de qué nodo falla — Node-8 apareció en 3 de las 6 fallas duras, pero
no de forma consistente entre corridas. Parece inestabilidad genérica del
stack BLE de Windows (agravada por ~20 dispositivos BLE ajenos alrededor,
visibles en el scan), no un bug de este proyecto. Sin causa de fondo
identificada — el reintento automático existente (`_open_and_confirm_none`)
ya absorbe la mayoría de los casos; se subió de 2 a 4 los intentos
(`_OPEN_RETRY_ATTEMPTS`, pedido explícito del usuario) el 2026-09-10 para
darle más margen.

## 6. Cambios de código de esta sesión

- **`core/models.py`, `core/parsers.py`, `core/client.py`**: nuevo soporte
  para `RANGE_DIAGNOSTICS_NTF` (requiere `DIAG 1`) — `RangeDiagnostics`/
  `RangeDiagnosticReport`, `parse_range_diagnostics`, y
  `DwmCliClient.read_notifications` ahora empareja cada `Measurement` con
  el diagnóstico de su ronda. Con tests usando una captura real de
  hardware como fixture (`tests/fixtures/range_diagnostics_ntf_fw110_real.txt`).
- **`transport/ble_link.py`**: `BleTransport.power_cycle()` (ver §3.2) —
  se mantiene como capa extra, no fue suficiente por sí sola.
- **`ranging/pair_runner.py`**: `run_directed_measurement` llama
  `power_cycle()` antes de cada dirección, iniciador y respondedor
  (§3.2). `_OPEN_RETRY_ATTEMPTS` subido de 2 a 4 (pedido explícito).
- **`ranging/campaign.py`** (v0.1.1): reescrito — `run_campaign` ya no
  agrupa direcciones por iniciador ni reusa su conexión; llama
  `run_pair` una vez por cada una de las `N*(N-1)` direcciones,
  conectando y desconectando el iniciador de punta a punta en cada una
  (ver §3.3, el fix real). `_grouped_by_initiator` se eliminó (sin uso).
- **`docs/protocolo-ble-qorvo.md`**: corregida la sección 3.1 (keepalive),
  marcada la verificación del 08/09 como obsoleta y agregada la
  verificación fresca del 10/09 contra el firmware actual.
- **GUI (`gui/main_window.py`, `imop_measure/__init__.py`)**:
  - Botón "Examinar…" para elegir la carpeta de reportes (antes solo se
    podía tipear la ruta a mano).
  - Leyenda de versión (`__version__`, definida en `imop_measure/__init__.py`
    — no se usa `importlib.metadata` porque el `.exe` empaquetado no
    incluye el `.dist-info` del propio proyecto).
  - Barra de progreso con porcentaje, tiempo transcurrido, estimado total
    y restante — el estimado inicial contempla ~5 desconexiones BLE
    esperables (pedido explícito del usuario); una vez que hay al menos
    una dirección medida, la estimación pasa a ser adaptativa (promedio
    real de la corrida en curso).
- Versión subida de 0.1.0 a 0.1.1 (`pyproject.toml`, `imop_measure/__init__.py`).
- Ejecutable (`dist/imop-measure-gui.exe`) reconstruido con estos cambios.

> **Nota:** `environments/sala_20.toml` tiene un cambio sin commitear que
> **no** es de esta sesión (habilita `uwb_node_4`/`uwb_node_6` pero con
> posiciones todavía placeholder, sin resolver) — se dejó afuera de los
> commits de esta sesión a propósito, ver el propio archivo. También
> apareció `environments/sala_10.toml` (sin trackear, aparentemente
> generado por una herramienta externa de posicionamiento) — tampoco se
> tocó ni se commiteó.
