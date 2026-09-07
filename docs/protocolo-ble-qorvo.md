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
- **Limitación de diseño:** `qorvo <cmd>` es estrictamente request/response
  y no está pensado para reenviar datos asíncronos del Qorvo. Sin embargo,
  las notificaciones `SESSION_INFO_NTF` de una sesión de ranging activa
  **sí llegan** por el canal de notificaciones NUS TX una vez que la sesión
  fue arrancada con `qorvo INITF ...` / `qorvo RESPF ...` — quedó
  confirmado con hardware real (30/30 notificaciones recibidas) en
  `../i-mop-qorvo-CLI-script/docs/verificacion-comandos-responder-ble.md`.
  No están garantizadas completas ni en orden: el código de lectura debe
  tolerar huecos.

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

## 4. Lectura de la distancia medida

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
