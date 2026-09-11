# Protocolo BLE + comandos Qorvo — referencia condensada

> **Propósito:** dar el subconjunto exacto del protocolo BLE/Qorvo que
> `i-mop-tools-measure` necesita para conectar a un nodo, configurarlo como
> iniciador o respondedor, y leer la distancia medida.
> **Alcance:** subconjunto orientado a ranging. Para el detalle exhaustivo
> de cada comando de firmware (calibración, diagnóstico, etc.) ver
> `../i-mop-qorvo-CLI-script/docs/referencia-comandos-fw110.md` y
> `../I-mop-nrf52840-fw/doc/00_BLE_Protocol_Specification.md`, que son la
> fuente autoritativa. Todo lo marcado **[Por verificar en hardware]** no
> está confirmado contra un nodo real todavía.

## 1. Capa BLE (GATT)

Cada nodo es un periférico BLE que anuncia como **`"UWB Node"`** y expone el
servicio **Nordic UART Service (NUS)**, que transporta un shell de Zephyr
(`shell_bt_nus`) — no es un protocolo binario propio.

| Elemento | UUID |
|---|---|
| Servicio NUS | `6e400001-b5a3-f393-e0a9-e50e24dcca9e` |
| Característica RX (el cliente escribe comandos acá) | `6e400002-b5a3-f393-e0a9-e50e24dcca9e` |
| Característica TX (el nodo notifica la salida acá) | `6e400003-b5a3-f393-e0a9-e50e24dcca9e` |
| Servicio "Qorvo Stream" (fw puente ≥ 0.3.0) | `019dad38-2b03-4df9-ac87-70ce530540fb` |
| Característica "Qorvo Stream Data" (solo Notify) | `36a9a2d9-a035-440f-8e59-ff0a72b2ba51` |

Pasos de conexión obligatorios:

1. Conectar (Just Works, sin PIN).
2. Negociar **MTU a 247 bytes** — el MTU por defecto (23B) es insuficiente
   para respuestas largas (`LISTCAL`, `GETOTP`).
3. Suscribirse a notificaciones de la característica TX (escribir `0x0001`
   en su CCCD) **antes** de enviar el primer comando.
4. Terminador de línea al escribir en RX: `\n` (con `\r\n` también funciona,
   el `\r` se ignora).
5. Sin eco ni ANSI/VT100: la característica TX solo trae la salida del
   comando, no el comando enviado de vuelta.
6. La conexión BLE se cae sola tras **~7-8 s de inactividad** — el cliente
   debe poder reconectar automáticamente si va a haber pausas largas entre
   comandos.

> **Nota:** esta capa la resuelve `imop_measure.transport.ble_link.BleTransport`
> — una copia adaptada del mismo módulo de `i-mop-qorvo-CLI-script` (no una
> reimplementación desde cero), ver [arquitectura.md](arquitectura.md)
> decisión D1.

## 2. El comando `qorvo`

Todo lo que le llega al chip Qorvo pasa por un único comando de shell:

```
qorvo on [-t|--time <valor>]      # enciende la alimentación del Qorvo
qorvo off [-t|--time <valor>]     # la apaga
qorvo <texto>                     # pasa <texto> tal cual a la CLI del Qorvo por UART
```

- `on`/`off` son palabras reservadas — nunca se reenvían al Qorvo, controlan
  un GPIO de alimentación en el nRF52840. `<valor>` de `-t/--time` es
  `<entero><s|m>` (ej. `-t 10m`).
- El comando viejo **`uwb on`/`uwb off` ya no existe** (fue unificado en
  `qorvo` a partir de la versión ≥1.17 del firmware del puente). No usarlo
  en código nuevo.
- **[2026-09-11] Apagado automático de seguridad**: `BleTransport` (código
  de producción, no los tests) siempre enciende el módulo con
  `qorvo on -t 1500s` (25 min, ver
  `transport.ble_link.SAFETY_AUTO_OFF_HOLD_S`) en vez de `qorvo on` sin
  límite — tanto en `open()` como en cada `power_cycle()` posterior (una
  por cada dirección medida). Pedido explícito del usuario: si la medición
  se interrumpe (crash, un nodo que deja de poder reconectarse por BLE) y
  nadie llega a mandar `qorvo off`, el módulo se apaga solo en vez de
  drenar la batería indefinidamente. En uso normal el temporizador se
  re-arma en cada `power_cycle()` y nunca llega a dispararse.
- Cualquier otro texto después de `qorvo ` se reenvía **verbatim** por UART
  al Qorvo (115200 baudios, terminador `\r\n`), p. ej. `qorvo STAT`,
  `qorvo INITF -CHAN=9 ...`.
- El puente espera **400 ms de silencio** o un **timeout duro de 8 s** para
  decidir que la respuesta del Qorvo terminó — no depende de que la
  respuesta traiga un terminador reconocible.
- Precondición: el Qorvo debe estar encendido (`qorvo on`) al menos ~1 s
  antes del primer `qorvo <cmd>`, si no, no responde.
- Error de timeout (texto exacto, útil para detectarlo por parsing):
  `Error: sin respuesta del modulo Qorvo (timeout)`.
- **Limitación de diseño (obsoleta desde fw puente ≥ 0.3.0):** `qorvo <cmd>`
  es estrictamente request/response con una ventana acotada (400 ms de
  silencio / timeout duro de 8 s) y, al vencer esa ventana, el puente
  suspendía el UART hacia el Qorvo incondicionalmente: con
  `SESSION_INFO_NTF` llegando cada ~200 ms durante el ranging, el silencio
  nunca se cumplía, la ventana corría siempre hasta los 8 s y todo lo que el
  Qorvo transmitía después se perdía hasta el próximo comando.
- **[fw puente ≥ 0.3.0] Canal dedicado de streaming:** el firmware agregó el
  servicio GATT "Qorvo Stream" (solo Notify, ver tabla §1), activado con el
  subcomando `qorvo stream on` (y `qorvo stream off`), que reenvía la salida
  del Qorvo de forma continua e indefinida durante una sesión de ranging
  activa, sin pasar por el shell de comandos. `BleTransport` se suscribe a
  esa característica al conectar, activa el streaming con `enable_stream()`
  (dentro de `open()`, tras `qorvo on`) y lo **reactiva tras cada
  reconexión automática** — es estado de la sesión GATT, se apaga solo al
  caerse la conexión BLE (a diferencia del encendido físico del Qorvo, que
  es un GPIO persistente). Las notificaciones `SESSION_INFO_NTF` (la
  lectura de distancia) llegan por ese canal y las respuestas de comandos
  por NUS TX: nunca se mezclan (`read_notification_line()` vs
  `read_line()` en el contrato `Transport`).

## 3. Secuencia de configuración por nodo

Para cada nodo, en modo `NONE` (confirmado con `qorvo STOP` + `qorvo STAT`):

```
qorvo on                       # esperar breve settle (ver [ble_timeouts] del TOML)
qorvo STOP
qorvo STAT                     # confirmar "Current App":"NONE" (o equivalente)
qorvo RESPF -CHAN=9 -PRFSET=BPRF4 -PCODE=10 -SLOT=2400 -BLOCK=200 -ROUND=25 \
            -RRU=DSTWR -ID=42 -VUPPER=01:02:03:04:05:06:07:08 -ADDR=<addr_resp> -PADDR=<addr_init>
```

y en el otro nodo del par, en simultáneo/inmediatamente después:

```
qorvo INITF -CHAN=9 -PRFSET=BPRF4 -PCODE=10 -SLOT=2400 -BLOCK=200 -ROUND=25 \
            -RRU=DSTWR -ID=42 -VUPPER=01:02:03:04:05:06:07:08 -ADDR=<addr_init> -PADDR=<addr_resp>
```

> **Advertencia:** pasar **cualquier** parámetro resetea todos los demás a
> su valor por defecto de firmware — siempre mandar el set completo, nunca
> un subconjunto parcial.

`-ID=` es el ID de sesión FiRa compartido por ambos nodos del par (puede
ser fijo, ej. `42`, mientras cada par se mida de a uno por vez — ver
[arquitectura.md](arquitectura.md) decisión D3). `-ADDR=`/`-PADDR=` son las
direcciones cortas de cada nodo — ver
[formato-ambiente-toml.md](formato-ambiente-toml.md) para cómo se derivan
de `uwb_addr`.

Convención de responsable de arranque: se recomienda arrancar primero el
`RESPF` (respondedor) y después el `INITF` (iniciador), igual que hace
`dwm3001c_cli.calibration.sampler.collect_samples` — evita que el
iniciador empiece a transmitir antes de que el respondedor esté escuchando.

> **[Verificado 2026-09-07 contra hardware real]:** toda esta secuencia
> (`qorvo on` → `STOP` → `STAT` → `RESPF` en el respondedor → `INITF` en
> el iniciador → lectura de `SESSION_INFO_NTF` → `STOP` en ambos →
> `qorvo off` → desconexión) corrió de punta a punta contra dos nodos
> físicos (`uwb_node_10`/`uwb_node_11` de `environments/sala_20.toml`) vía
> `ranging.pair_runner.run_pair`, sin intervención manual.

### 3.1 `STAT` periódico al respondedor durante una sesión `RESPF` activa

Mientras se juntan muestras del lado del iniciador, el enlace BLE del
respondedor no recibe tráfico propio (ver sección 7) y se desconecta solo
por el timeout de inactividad de ~7-8s. `ranging.pair_runner` (función
`_keep_responder_alive`) manda un `STAT` al respondedor cada 5s durante
el muestreo, bien por debajo de ese umbral, para mantener el enlace vivo
sin tocar la app `RESPF` en curso.

> **[Por verificar en hardware — verificación 2026-09-08 obsoleta]:** la
> verificación original de que `STAT` "no interrumpe ni degrada" la sesión
> (3 campañas completas, 30/30 en 36 direcciones, cero errores de conexión)
> se hizo el 2026-09-08, **un día antes** de que existiera el canal
> dedicado de streaming (`I-mop-nrf52840-fw` v0.3.0, 2026-09-09 — ver
> sección 2). En ese momento las notificaciones todavía viajaban por el
> canal de comandos compartido (ráfagas acotadas por la ventana de 8s), no
> por el canal "Qorvo Stream" actual — es decir, la cifra "cero errores"
> describe una arquitectura de lectura que ya no está en uso. El
> razonamiento de que el STAT ya no compite con las notificaciones (canales
> BLE separados desde v0.3.0, ver sección 4) es válido a nivel de diseño,
> pero no fue re-confirmado con una campaña de hardware real equivalente
> tras la migración.
>
> **[Verificado 2026-09-10 contra hardware real, firmware puente v0.3.1]:**
> prueba A/B controlada (keepalive ON/OFF alternado, mismas 4 direcciones,
> 2 corridas por condición, 30 muestras cada una) contra
> `environments/sala_20.toml`: **sin diferencia medible** entre tener el
> keepalive activo o no — desvío estándar promedio 3.08cm (ON) vs 3.68cm
> (OFF) sobre las corridas exitosas, y la misma tasa de fallas de conexión
> BLE en ambas condiciones (2/8 cada una, mismo error transitorio de
> Windows `WinError -2147023673` visto en general durante toda la sesión de
> pruebas, no asociado al keepalive). El salto de distancia bimodal descrito
> en el historial de este archivo (ver `reports/` de mediciones reales) no
> se reprodujo en ninguna de las 16 corridas, con o sin keepalive — se
> descarta como causa. La muestra es más chica que la verificación
> obsoleta del 08/09 (16 corridas vs 36), pero es la única contra el
> firmware actual; ampliarla si se necesita más confianza.

### 3.2 Modo uno-a-muchos (`-MULTI`)

> **Fuente:** Developer Manual `DWM3001CDK_Developer_Manual_QM33SDK-1.1.1.pdf`
> (SDK `DW3_QM33_SDK_1.1.1`), sección 7 — es el "SDK Manual" al que remite
> la ayuda del firmware (`HELP INITF`/`HELP RESPF`) para el detalle que no
> cubre `HELP`. Implementado en `ranging.pair_runner.run_one_to_many` /
> `ranging.session.initiator_kwargs_multi` / `responder_kwargs_multi` —
> modo **experimental**, opt-in (`--one-to-many` en la CLI, selector "Modo
> de medición" en la GUI desde 2026-09-11), no reemplaza el flujo por
> defecto (`ranging.campaign.run_campaign`).

Un iniciador puede rangear contra varios respondedores dentro de la misma
sesión FiRa (`MULTI_NODE_MODE: ONE_TO_MANY` en vez de `UNICAST`), en vez de
una sesión por par:

```
INITF -MULTI -ADDR=0 -PADDR=[1,2,3]

RESPF -MULTI -PADDR=0 -ADDR=1
RESPF -MULTI -PADDR=0 -ADDR=2
RESPF -MULTI -PADDR=0 -ADDR=3
```

- **El flag `-MULTI` hace falta en ambos roles.** El iniciador acepta
  `-PADDR=[lista]` (varios respondedores); el respondedor sigue usando un
  `-PADDR=` único (la dirección del iniciador, no una lista) — solo
  cambia que también lleva `-MULTI`.
  **[Verificado 2026-09-10 contra hardware real]:** con `-MULTI` solo en
  el iniciador y `RESPF` "normal" en los respondedores, el 100% de las
  rondas dio `RX_TIMEOUT` (0% éxito, ~76 rondas). Agregando `-MULTI`
  también en cada `RESPF` (igual que en el manual), 152/152 muestras
  `SUCCESS` — confirmado con 2 respondedores reales
  (`uwb_node_6`/`uwb_node_8`).
- **`SESSION_INFO_NTF` trae `n_measurements` > 1**: una notificación por
  ronda, con un bloque `[mac_address=..., status=..., distance[cm]=...]`
  por respondedor (ver `core/parsers.py::parse_session_info`, devuelve
  `list[Measurement]`). Ejemplo real:
  ```
  SESSION_INFO_NTF: {session_handle=1, sequence_number=40, block_index=40, n_measurements=2
   [mac_address=0x0006, status="SUCCESS", distance[cm]=2];
   [mac_address=0x0008, status="SUCCESS", distance[cm]=19]}
  ```
- **Cada respondedor puede configurarse y desconectarse de a uno**, sin
  necesidad de mantener conexiones BLE simultáneas: el módulo Qorvo sigue
  corriendo `RESPF` de forma autónoma sin conexión BLE activa.
  **[Verificado 2026-09-10 contra hardware real]:** se configuró un
  respondedor, se cerró su conexión BLE por completo (sin `STOP`, sin
  apagar) y se esperaron 15s — al medir después desde otro nodo, 20/20
  muestras `SUCCESS` con el `mac_address` correcto. Por esto
  `run_one_to_many` conecta y desconecta cada respondedor de a uno para
  configurarlo, y solo mantiene la conexión del iniciador activa durante
  el muestreo.
- **[Por verificar en hardware]:** no hay fórmula confirmada del máximo de
  respondedores que entran en una ronda (`round_slots`, default 25) — el
  manual solo advierte "ROUND tiene que ajustarse a la cantidad de
  controlees" sin dar la cuenta exacta. Probado únicamente con 2.
- **[Por verificar en hardware]:** no se confirmó si `RANGE_DIAGNOSTICS_NTF`
  (con `DIAG 1`) trae un bloque por respondedor o uno combinado en este
  modo.

## 4. Lectura de la distancia medida

> **[fw puente ≥ 0.3.0]:** las notificaciones `SESSION_INFO_NTF` ya **no**
> llegan por NUS TX: viajan por la característica dedicada "Qorvo Stream
> Data" (ver §1 y §2), que `BleTransport` activa en `open()` con
> `qorvo stream on` y reactiva tras cada reconexión automática. En el
> código, `DwmCliClient.read_notifications` lee vía
> `Transport.read_notification_line()` — canal separado de las respuestas
> de comandos (`read_line()`), de modo que un `STAT` de keepalive no compite
> con las notificaciones de una sesión en curso.

La distancia llega como notificación asíncrona. La documentación original
(tomada del repo hermano) describe **dos líneas** (la segunda arranca con
un `\r` residual):

```
SESSION_INFO_NTF: {session_handle=1, sequence_number=0, block_index=0, n_measurements=1
 [mac_address=0x0001, status="SUCCESS", distance[cm]=210, RSSI[dBm]=-78.0]}
```

> **[Verificado 2026-09-07 contra hardware real, `uwb_node_10` ↔
> `uwb_node_11`]:** en la práctica llegaron **tres** líneas — la
> principal, una línea **vacía** (residuo de un `\r` suelto sin `\n`
> emparejado) y la continuación arrancando con un **espacio** (no `\r`):
> ```
> SESSION_INFO_NTF: {session_handle=1, sequence_number=0, block_index=0, n_measurements=1
>
>  [mac_address=0x0001, status="SUCCESS", distance[cm]=337]}
> ```
> No hace falta manejarlo como caso especial: `DwmCliClient.read_notifications`
> acumula fragmentos hasta que las llaves `{}` balancean, sin asumir una
> cantidad fija de líneas — parsea ambas variantes igual. Este caso quedó
> fijado como test de regresión
> (`tests/test_ranging_pair_runner.py::test_run_pair_handles_real_three_fragment_notification`).

- Solo las líneas con `status="SUCCESS"` traen `distance[cm]` — otros
  estados (ej. `"RX_TIMEOUT"`) no tienen ese campo.
- Una sola muestra tiene resolución de 1 cm pero varios cm de dispersión
  por multipath — hay que promediar varias muestras.
  [Verificado 2026-09-07]: 15 muestras `SUCCESS`/15 pedidas entre
  `uwb_node_10` y `uwb_node_11`, media 341.9 cm, desvío estándar 2.1 cm —
  dispersión baja, consistente con lo esperado.
- Al terminar de medir un par: `qorvo STOP` en ambos nodos, luego
  `qorvo off` y desconexión BLE.

## 5. Comandos destructivos — nunca automatizar

| Comando | Por qué no automatizar |
|---|---|
| `RESTORE` | Resetea toda la configuración UWB y del sistema a fábrica, escribe NVM. |
| `SAVE` durante ranging activo | Puede fallar o dejar el nodo en estado inconsistente. |
| `UART <n>` | Cambia qué interfaz física recibe la consola — mal usado, deja el nodo inalcanzable por BLE. |

## 6. Direcciones y mapeo `uwb_addr` → `ADDR`/`PADDR`

Ver [formato-ambiente-toml.md](formato-ambiente-toml.md) §2.

## 7. Fallas conocidas del backend BLE de Windows

> Investigado a pedido del usuario tras encontrar esto contra hardware
> real (2026-09-07) — ver también `CLAUDE.md` sección 2 (por qué la
> salida a terminal no puede usar los mismos caracteres que los reportes).

El backend WinRT de `bleak` (la librería BLE que usa este proyecto, ver
[arquitectura.md](arquitectura.md) decisión D1) tiene fallas de conexión
**transitorias y conocidas en Windows, sin arreglo de fondo en `bleak`
todavía** — hay varios issues abiertos en su repositorio sobre esto
exacto (ej. [`hbldh/bleak#1280`](https://github.com/hbldh/bleak/issues/1280),
[`hbldh/bleak#1829`](https://github.com/hbldh/bleak/issues/1829)).
Confirmado dos veces contra hardware real en este proyecto:

- `OSError: [WinError -2147483629] Se cerró el objeto` — un error nativo
  de Windows (COM/WinRT), no una `BleakError` de `bleak`.
- `TransportError: ... conexión BLE perdida esperando respuesta` — la
  conexión se cae mientras se espera una respuesta.

Ambos son más probables cuanto más seguido se conecta/desconecta el mismo
adaptador Bluetooth en poco tiempo (exactamente lo que hace este proyecto
al medir varios nodos).

Además, la conexión BLE al puente se cierra **sola** ~7-8s después de la
última actividad — comportamiento normal del puente, no una falla. Por
eso `BleTransport.write_line` reconecta automáticamente si hace falta
(`_ensure_connected`, ver `transport/ble_link.py`), y por eso
`ranging.pair_runner` manda un `STAT` periódico al respondedor durante el
muestreo (ver sección 3.1) — su enlace, si no, queda sin tráfico propio
el tiempo suficiente como para caerse solo.

**Mitigación implementada:** `imop_measure.transport.ble_link.BleTransport`
reintenta la conexión (`_connect_with_retry`, con un cliente `bleak`
**nuevo** en cada intento, no el mismo objeto que ya falló — hay reportes
de la comunidad de que reusar el mismo objeto tras esta falla lo puede
dejar en un estado inválido) — 3 intentos con 2s de espera entre cada uno
por defecto, configurable via `BleTransport(connect_retry_attempts=,
connect_retry_backoff_s=)`. `_run_coro` envuelve tanto `BleakError` como
`OSError` crudo en nuestro propio `TransportError`, para que
`core.client.DwmCliClient`/`ranging.pair_runner` no tengan que distinguir
el tipo de excepción nativa.

**Alternativa evaluada y descartada por ahora:**
[`bleak-retry-connector`](https://github.com/Bluetooth-Devices/bleak-retry-connector)
(usada por Home Assistant) es más robusta — pero su función principal,
`establish_connection()`, exige un objeto `BLEDevice` en vez de una
dirección MAC como string, lo que hubiera requerido escanear antes de
cada conexión y reestructurar cómo se inyectan los dobles de prueba en
los tests. Se optó por el reintento propio (más simple, cero
dependencias nuevas) como primera mitigación — si en el futuro esto no
alcanza con más nodos, reconsiderar esa librería.
