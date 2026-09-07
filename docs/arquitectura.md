# Arquitectura

> **Propósito:** describir las capas del proyecto, sus responsabilidades y
> las decisiones de diseño tomadas, para que cualquier cambio (incluida la
> futura GUI) respete la separación existente.
> **Alcance:** aplica a `src/imop_measure/`. No cubre el protocolo BLE en sí
> (ver [protocolo-ble-qorvo.md](protocolo-ble-qorvo.md)) ni el plan de
> fases (ver [plan-implementacion.md](plan-implementacion.md)).

## 1. Visión general

```
┌─────────────────────────────────────────────────────────────┐
│  app/            CLI (Typer + Rich). Futuro: gui/ (Fase F7)  │
├─────────────────────────────────────────────────────────────┤
│  ranging/        Orquesta sesiones INITF/RESPF por par de    │
│                   nodos, lee notificaciones, promedia         │
├───────────────────────┬───────────────────┬───────────────────┤
│  geometry/             │  config/           │  core/             │
│  distancia euclídea,   │  lectura/valid.    │  cliente protocolo │
│  generación de pares   │  environments/*.toml│  CLI Qorvo, parsers│
│                        │                     │  ┌───────────────┤
│                        │                     │  │  transport/    │
│                        │                     │  │  BleTransport  │
│                        │                     │  │  (NUS/bleak)   │
├─────────────────────────────────────────────────────────────┤
│  report/         Construye y escribe reportes JSON + Markdown │
└─────────────────────────────────────────────────────────────┘
```

Regla de dependencia: **una sola dirección**, de arriba hacia abajo.
`geometry/` y `config/` son puros (sin I/O de red, sin hardware) y
totalmente testeables sin nodos conectados. `ranging/` es la única capa que
orquesta sesiones de ranging, y lo hace a través de `core/` (que a su vez
usa `transport/` para hablar BLE con `bleak`) — nunca directamente con
`bleak`. `report/` no sabe de dónde salieron los números, solo los recibe
con una forma ya definida (ver §2.4) y los escribe.

Esta separación es la misma que usa `i-mop-qorvo-CLI-script`
(`app → validation/calibration → core → transport`), deliberadamente: ese
repo ya demostró que permite construir una GUI (`dwm-gui`) sin tocar la
lógica de negocio, y de hecho `core/` y `transport/` de este proyecto son
un puerto directo de los suyos (ver decisión D1). Es el mismo camino que se
espera para este proyecto (script → herramienta visual, ver plan F7).

## 2. Módulos

### 2.1 `config/`

| Módulo | Responsabilidad |
|---|---|
| `loader.py` | Lee y parsea `environments/sala_XX.toml` con `tomllib` (stdlib). |
| `models.py` | Dataclasses: `Anchor` (key, nombre, mac, uwb_addr, posicion, tiempo_prendido), `Ambiente` (id, nombre, dimensiones, anchors, ble_timeouts). |
| `validate.py` | Valida el TOML: claves de ancla únicas, `uwb_addr` con formato `XX:YY`, posiciones con 3 componentes, al menos 2 anclas activas. |

### 2.2 `geometry/`

| Módulo | Responsabilidad |
|---|---|
| `distance.py` | `euclidean_distance(a: Anchor, b: Anchor) -> float` (metros). |
| `pairs.py` | `all_pairs(anchors: list[Anchor]) -> list[tuple[Anchor, Anchor]]` — genera todas las combinaciones sin repetición (`n·(n-1)/2` pares). |

### 2.3 `ranging/`

| Módulo | Responsabilidad |
|---|---|
| `addressing.py` | Convierte `uwb_addr` (`"00:02"`) a entero decimal para `-ADDR=`/`-PADDR=`. |
| `session.py` | Arma los parámetros de sesión FiRa (`CHAN`, `PRFSET`, `PCODE`, `SLOT`, `BLOCK`, `ROUND`, `RRU`, `ID`, `VUPPER`) — `SessionParams` portada de `dwm3001c_cli.calibration.sampler` (ver decisión D1). |
| `pair_runner.py` | Por cada par: conecta BLE a ambos nodos (vía `core.client.DwmCliClient` sobre `transport.ble_link.BleTransport`), enciende (`qorvo on`), configura un nodo como `RESPF` y el otro como `INITF`, lee N notificaciones `SESSION_INFO_NTF`, filtra `status="SUCCESS"`, promedia `distance[cm]`, detiene la sesión (`qorvo STOP`), apaga (`qorvo off`) y desconecta. |
| `campaign.py` | Itera `pair_runner.run_pair()` sobre todos los pares del ambiente, recolectando resultados y tolerando el fallo de un par sin abortar la campaña completa. |

### 2.3.1 `core/` y `transport/` (portados, ver decisión D1)

| Módulo | Responsabilidad |
|---|---|
| `transport/base.py` | Protocolo `Transport` (contrato mínimo de transporte de líneas) + `LineAssembler` (reensambla fragmentos BLE en líneas). |
| `transport/ble_link.py` | `BleTransport`: transporte sobre el puente nRF52840 (Nordic UART Service / `bleak`). Reconecta sola tras inactividad, filtra el prompt del shell Zephyr, drena la respuesta sin marcador de `qorvo on`/`off`. |
| `core/models.py` | Dataclasses de respuestas del firmware: `DeviceInfo`, `CalKey`, `Measurement`, `ChipId`, `RangingStats`. |
| `core/parsers.py` | Funciones puras de parseo: `parse_stat`, `parse_session_info`, `parse_calkey_line`, `parse_listcal`, `parse_decaid`, `is_ok`. |
| `core/client.py` | `DwmCliClient`: envía comandos (`STAT`, `STOP`, `INITF`, `RESPF`, `SAVE`, `DIAG`, etc.) sobre un `Transport` ya construido, interpreta eco/`ok`/`KO`, y `read_notifications()` para leer `SESSION_INFO_NTF` durante una sesión activa. |

Estos dos paquetes son una copia adaptada y **deliberadamente reducida**
del código homónimo en `dwm3001c_cli` (repo hermano): no se portaron
`SerialLink` (este proyecto nunca habla serie directo con los nodos) ni los
métodos `restore()`/`enable_uart_output()` de `DwmCliClient` (comandos
destructivos que `CLAUDE.md` prohíbe automatizar — al no existir el método,
no se pueden invocar por error).

### 2.4 `report/`

| Módulo | Responsabilidad |
|---|---|
| `models.py` | `PairResult` (par de nodos, distancia calculada, distancia medida, n_muestras, error_abs_cm, error_pct, estado). |
| `build.py` | Arma el resumen (PASS = medición dentro de tolerancia, FAIL = fuera de tolerancia, ERROR = no se pudo medir) a partir de una lista de `PairResult`. |
| `write.py` | Escribe `reports/medicion-<sala>-<timestamp>.json` y `.md`, mismo patrón que `validation/report.py` del repo hermano. |

### 2.5 `app/`

| Módulo | Responsabilidad |
|---|---|
| `cli.py` | App Typer (`imop-measure`). Subcomando principal: `run --environment environments/sala_20.toml`. |
| `config_cli.py` | Resolución de opciones CLI (timeouts, cantidad de muestras, tolerancia) con precedencia CLI > TOML (`[ble_timeouts]`) > default, igual que `app/config.py` del repo hermano. |

## 3. Decisiones de diseño

| Decisión | Justificación |
|---|---|
| **D1** — Portar (copiar y adaptar) el transporte BLE y el cliente de comandos Qorvo de `dwm3001c_cli` a `src/imop_measure/{transport,core}/`, en vez de depender del repo hermano en tiempo de ejecución o reimplementarlos desde cero. | El código de `dwm3001c_cli` ya está validado contra hardware real, incluyendo una sesión de ranging completa por BLE (`docs/verificacion-comandos-responder-ble.md` del repo hermano) — reimplementarlo de cero reintroduciría bugs ya resueltos (fragmentación de `SESSION_INFO_NTF`, filtrado del prompt Zephyr, reconexión BLE tras inactividad, buffer colgado sin cierre). Depender de una instalación editable del repo hermano (`pip install -e ../i-mop-qorvo-CLI-script`, como se hizo originalmente en la Fase F2) ataba este proyecto a tener ese otro repo clonado al lado en la ruta correcta — no es una herramienta independiente. Portar el código (con su procedencia documentada: commit `ad7079aab0d32b603b4f83ce8be9ac5ce49bd0bd`) resuelve ambos problemas a la vez. **Costo aceptado:** un fix de protocolo descubierto en el repo hermano no se propaga solo — hay que portarlo a mano si aplica también acá. |
| **D2** — `ranging/` no conoce Typer/Rich. | Habilita reusar toda la orquestación desde una futura GUI (Fase F7) sin reescritura, igual que hizo el repo hermano con `dwm-gui`. |
| **D3** — Un par de nodos se mide de a uno por vez (no todos en paralelo). | El firmware/BLE del repo hermano documenta un límite duro de conexiones BLE simultáneas (`max_concurrent_connections` en `[ble_timeouts]`, ~5-7 según el bridge). Medir de a pares evita saturar el enlace y simplifica el manejo de errores por nodo. Paralelizar queda para una fase posterior si el tiempo total de campaña lo justifica. |
| **D4** — El archivo de ambiente vive en `environments/`, no en la raíz del repo. | Coincide con el propio encabezado de `sala_20.toml` (`# environments/sala_20.toml`) y dejar la raíz del repo limpia para múltiples ambientes futuros. |
| **D5** — `reports/` y `logs/` se generan en tiempo de ejecución y están gitignored. | Mismo patrón que el repo hermano: son salidas, no fuente de verdad versionada. |

## 4. Flujo de datos: campaña de medición completa

```
CLI (app/cli.py: `imop-measure run --environment environments/sala_20.toml`)
  │
  ├─ config/loader.py        → Ambiente (lista de Anchor)
  │
  ├─ geometry/pairs.py        → lista de pares (Anchor, Anchor)
  ├─ geometry/distance.py     → distancia calculada por par
  │
  ├─ ranging/campaign.py
  │     └─ por cada par → ranging/pair_runner.py
  │           ├─ transport.ble_link.BleTransport (x2, uno por nodo)
  │           ├─ core.client.DwmCliClient.setapp / start_respf / start_initf
  │           ├─ lectura de notificaciones SESSION_INFO_NTF → distancia medida (promedio)
  │           └─ qorvo STOP + qorvo off + desconexión
  │
  ├─ report/build.py          → PairResult por par (calculada, medida, error, estado)
  └─ report/write.py          → reports/medicion-<sala>-<timestamp>.{json,md}
```
