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
│  geometry/             │  config/           │  dwm3001c_cli      │
│  distancia euclídea,   │  lectura/valid.    │  (repo hermano,    │
│  generación de pares   │  environments/*.toml│  transporte BLE +  │
│                        │                     │  cliente Qorvo)    │
├─────────────────────────────────────────────────────────────┤
│  report/         Construye y escribe reportes JSON + Markdown │
└─────────────────────────────────────────────────────────────┘
```

Regla de dependencia: **una sola dirección**, de arriba hacia abajo.
`geometry/` y `config/` son puros (sin I/O de red, sin hardware) y
totalmente testeables sin nodos conectados. `ranging/` es la única capa que
habla con BLE/UWB, y lo hace a través de `dwm3001c_cli`, no directamente con
`bleak`. `report/` no sabe de dónde salieron los números, solo los recibe
con una forma ya definida (ver §2.4) y los escribe.

Esta separación es la misma que usa `i-mop-qorvo-CLI-script`
(`app → validation/calibration → core → transport`), deliberadamente: ese
repo ya demostró que permite construir una GUI (`dwm-gui`) sin tocar la
lógica de negocio. Es el mismo camino que se espera para este proyecto
(script → herramienta visual, ver plan F7).

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
| `session.py` | Arma los parámetros de sesión FiRa (`CHAN`, `PRFSET`, `PCODE`, `SLOT`, `BLOCK`, `ROUND`, `RRU`, `ID`, `VUPPER`) reusando el patrón `SessionParams` de `dwm3001c_cli.calibration.sampler`. |
| `pair_runner.py` | Por cada par: conecta BLE a ambos nodos (vía `dwm3001c_cli.transport.ble_link.BleTransport` + `dwm3001c_cli.core.client.DwmCliClient`), enciende (`qorvo on`), configura un nodo como `RESPF` y el otro como `INITF`, lee N notificaciones `SESSION_INFO_NTF`, filtra `status="SUCCESS"`, promedia `distance[cm]`, detiene la sesión (`qorvo STOP`), apaga (`qorvo off`) y desconecta. |
| `campaign.py` | Itera `pair_runner.run_pair()` sobre todos los pares del ambiente, recolectando resultados y tolerando el fallo de un par sin abortar la campaña completa. |

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
| **D1** — Reusar `dwm3001c_cli` (BLE transport + cliente de comandos Qorvo) en vez de reimplementarlo. | Ya está validado contra hardware real, incluyendo una sesión de ranging completa por BLE (`docs/verificacion-comandos-responder-ble.md` del repo hermano). Reimplementarlo duplicaría lógica y reintroduciría bugs ya resueltos (fragmentación de `SESSION_INFO_NTF`, filtrado del prompt Zephyr, reconexión BLE tras inactividad). |
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
  │           ├─ dwm3001c_cli.transport.ble_link.BleTransport (x2, uno por nodo)
  │           ├─ dwm3001c_cli.core.client.DwmCliClient.setapp / start_respf / start_initf
  │           ├─ lectura de notificaciones SESSION_INFO_NTF → distancia medida (promedio)
  │           └─ qorvo STOP + qorvo off + desconexión
  │
  ├─ report/build.py          → PairResult por par (calculada, medida, error, estado)
  └─ report/write.py          → reports/medicion-<sala>-<timestamp>.{json,md}
```
