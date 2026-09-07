# Plan de implementación

> **Propósito:** especificar las fases de implementación con el detalle
> suficiente para que quien implemente (persona o IA) no tenga que tomar
> decisiones de diseño no cubiertas acá — si hace falta decidir algo que no
> está especificado, preguntar antes de improvisar (ver `CLAUDE.md` §8.5).
> **Alcance:** cubre desde el andamiaje inicial hasta la campaña de
> medición completa por CLI, más el roadmap hacia la herramienta visual.
> **Documentos que rigen esta implementación:** `../CLAUDE.md`,
> [arquitectura.md](arquitectura.md), [protocolo-ble-qorvo.md](protocolo-ble-qorvo.md),
> [formato-ambiente-toml.md](formato-ambiente-toml.md).

## 0. Reglas obligatorias para quien implemente

1. Leer `CLAUDE.md` y esta guía completa antes de escribir código.
2. No inventar comportamiento de firmware/protocolo: usar parsers
   tolerantes y marcar lo no confirmado `TODO(verificar-con-hardware)`.
3. No agregar dependencias ni módulos fuera de lo listado en `CLAUDE.md`
   §4 y en este plan, sin preguntar primero.
4. Nunca automatizar `RESTORE`, `SAVE` durante ranging, ni `UART <n>`.
5. Una rama por fase: `feature/f<N>-<nombre-fase>`, PR contra `main` al
   cerrarla.
6. Idioma: docs/docstrings/comentarios/commits en español, identificadores
   de código en inglés.
7. Al completar una fase, actualizar la tabla de la §1 (marcar ✅ y, si
   aplica, el número de PR).

## 1. Fases

| Fase | Contenido | Rama | Depende de | Estado |
|---|---|---|---|---|
| F0 | Andamiaje: `pyproject.toml`, estructura `src/`, `.gitignore`, pre-commit | `feature/f0-andamiaje` | — | ✅ (este PR) |
| F1 | `config/` + `geometry/`: leer TOML, calcular distancias y pares | `feature/f1-config-geometria` | F0 | ✅ |
| F2 | Dependencia de `dwm3001c_cli`, `ranging/addressing.py`, `ranging/session.py` | `feature/f2-transporte-ble` | F1 | ✅ |
| F2b | Porta `transport/` + `core/` (BleTransport, DwmCliClient, parsers) desde `dwm3001c_cli` para dejar de depender de él en runtime | `refactor/vendoriza-transporte-ble` | F2 | ✅ |
| F3 | `ranging/pair_runner.py`: medición de un par de nodos, con fakes para test | `feature/f3-sesion-ranging` | F2b | ✅ (sin verificar contra hardware real todavía) |
| F4 | `ranging/campaign.py`: orquestación de todos los pares del ambiente | `feature/f4-orquestacion-campania` | F3 | ⬜ |
| F5 | `report/`: construcción y escritura de reporte JSON + Markdown | `feature/f5-reporte` | F1, F4 | ⬜ |
| F6 | `app/cli.py`: comando `imop-measure run`, end-to-end | `feature/f6-cli` | F5 | ⬜ |
| F7 | Herramienta visual (GUI) — reusa `ranging/`, `report/`, `config/`, `geometry/` sin cambios | `feature/f7-gui` | F6 (validado en hardware real) | ⬜ |

## 2. F0 — Andamiaje

Deliverables:

- `pyproject.toml` (ver [../pyproject.toml](../pyproject.toml), ya creado
  en este PR): src-layout, `requires-python = ">=3.11"`, deps base
  (`typer`, `rich`), dev (`pytest`, `ruff`, `mypy`), config de `ruff`
  (line-length 100), `mypy` strict sobre `src`, `pytest` con marker
  `hardware` excluido por defecto.
- Estructura de directorios completa (`src/imop_measure/{config,geometry,ranging,report,app}/`,
  `tests/`, `reports/`, `logs/`), cada paquete con `__init__.py`.
- `.gitignore`: `.venv/`, `__pycache__/`, `.mypy_cache/`, `.ruff_cache/`,
  `.pytest_cache/`, `reports/*` (excepto `.gitkeep`), `logs/*` (excepto
  `.gitkeep`), `*.egg-info/`.
- `environments/sala_20.toml` versionado (ya movido en este PR).

Criterio de aceptación: `pip install -e .[dev]` funciona, `ruff check` y
`mypy src` no fallan sobre el esqueleto vacío.

## 3. F1 — `config/` + `geometry/`

Sin dependencia de BLE — 100% testeable sin hardware.

`config/models.py`:
```python
@dataclass(frozen=True)
class Anchor:
    key: str
    nombre: str
    mac: str
    uwb_addr: str
    posicion: tuple[float, float, float]
    tiempo_prendido: str

@dataclass(frozen=True)
class Ambiente:
    id: str
    nombre: str | None
    dimensiones: tuple[float, float, float]
    anchors: list[Anchor]
    ble_timeouts: dict[str, float]
```

`config/loader.py`: `load_ambiente(path: Path) -> Ambiente` usando
`tomllib.load`. Ignora tablas `[[anchors]]` comentadas (no aparecen en el
TOML parseado, no requiere lógica extra). Valida con `config/validate.py`:

- `ambiente.id` coincide con el nombre de archivo (`sala_<id>.toml`).
- Al menos 2 `anchors`.
- `key` únicas entre anclas.
- `uwb_addr` matchea `^[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}$`.
- `posicion` tiene exactamente 3 componentes numéricos.

Errores de validación levantan `ConfigError` (subclase de `MeasureError`,
ambas en `src/imop_measure/errors.py`, a crear en esta fase).

`geometry/distance.py`:
```python
def euclidean_distance(a: Anchor, b: Anchor) -> float:
    """Distancia euclídea 3D entre dos anclas, en metros."""
```

`geometry/pairs.py`:
```python
def all_pairs(anchors: list[Anchor]) -> list[tuple[Anchor, Anchor]]:
    """Todas las combinaciones sin repetición ni orden, vía itertools.combinations."""
```

Tests (`tests/test_config.py`, `tests/test_geometry.py`): usar
`environments/sala_20.toml` real como fixture; casos de TOML inválido
(id no coincide, `uwb_addr` mal formado, 1 sola ancla) deben levantar
`ConfigError`.

Criterio de aceptación (verificado en la Fase F1): `load_ambiente` carga
sin error las anclas activas declaradas en `environments/sala_20.toml` y
`all_pairs(...)` genera todas sus combinaciones sin repetición
(`N` anclas → `N·(N-1)/2` pares). `tests/test_config.py` y
`tests/test_geometry.py` usan ese archivo como fixture real y se
actualizan junto con sus datos — no asumir en esta guía una cantidad fija
de anclas, cambia a medida que se agregan nodos reales.

## 4. F2 — Dependencia BLE + direccionamiento + sesión

- Instalar `dwm3001c_cli` en modo editable desde el path local del repo
  hermano (`pip install -e ../i-mop-qorvo-CLI-script`), documentado como
  paso manual en el README (no se referencia por path relativo dentro de
  `pyproject.toml` para no atar el build a la estructura de carpetas de
  una máquina en particular).
- `ranging/addressing.py`: `uwb_addr_to_int()` (ver
  [formato-ambiente-toml.md](formato-ambiente-toml.md) §3) +
  `mac_from_ntf(mac_address_hex: str) -> str` si hace falta matchear
  `mac_address=0x....` de `SESSION_INFO_NTF` contra el `uwb_addr` del
  ancla.
- `ranging/session.py`: `SessionConfig` (dataclass con `chan, prfset,
  pcode, slot, block_ms, round_slots, rru, session_id, vupper`, defaults
  iguales a los de `docs/protocolo-ble-qorvo.md` §3) +
  `initiator_kwargs(addr, paddr)` / `responder_kwargs(addr, paddr)` — igual
  patrón que `dwm3001c_cli.calibration.sampler.SessionParams`, evaluar
  directamente reusar esa clase en vez de duplicarla (decidir en el PR de
  esta fase, dejar comentado el motivo de la elección).

Criterio de aceptación: tests unitarios de `addressing.py` (sin hardware)
cubriendo `"00:02"` → `2`, `"0a:ff"` → `2815`, formato inválido → error.

**Decisión tomada:** se reusa `dwm3001c_cli.calibration.sampler.SessionParams`
directamente (re-exportada desde `ranging/session.py`) en vez de duplicarla.
`ranging/session.py` agrega `initiator_kwargs()`/`responder_kwargs()` como
funciones que envuelven `SessionParams.initiator_kwargs()`/`responder_kwargs()`
y sobreescriben `addr`/`paddr` con las direcciones reales del par (esos
métodos originales asumen los defaults de rol `0`/`1`). `mac_from_ntf()` no
se implementó — nada lo consume todavía (se evalúa en F3 si hace falta).
`dwm3001c_cli` no publica `py.typed`, así que se agregó un override en
`pyproject.toml` (`[[tool.mypy.overrides]]`, `ignore_missing_imports` para
`dwm3001c_cli.*`) en vez de silenciar el import línea por línea.

**Revisión posterior (tras cerrar F2):** el enfoque de "depender de
`dwm3001c_cli` instalado en modo editable" se descartó — ataba este
proyecto a tener el repo hermano clonado al lado en la ruta correcta, y no
lo dejaba funcionar como herramienta independiente. En su lugar se
**portó** el código necesario (transporte BLE + cliente de comandos Qorvo)
a `src/imop_measure/{transport,core}/`, con su procedencia documentada
(commit `ad7079aab0d32b603b4f83ce8be9ac5ce49bd0bd` de `i-mop-qorvo-CLI-script`)
— ver [arquitectura.md](arquitectura.md) decisión D1 (revisada) y sección
2.3.1. `ranging/session.py` ya no importa `dwm3001c_cli`: `SessionParams`
está definida localmente ahí (mismo contenido, portado). El override de
mypy para `dwm3001c_cli.*` se retiró de `pyproject.toml` — ya no aplica.
`pip install -e ../i-mop-qorvo-CLI-script` ya no es un paso de instalación
de este proyecto.

## 4b. F2b — Portar transporte BLE y cliente Qorvo (independencia del repo hermano)

Deliverables (todos portados de `dwm3001c_cli`, commit
`ad7079aab0d32b603b4f83ce8be9ac5ce49bd0bd`, ver
[arquitectura.md](arquitectura.md) §2.3.1):

- `errors.py`: agrega `TransportError`, `CommandTimeoutError`,
  `CommandRejectedError`, `UnexpectedModeError`, `DeviceDiscoveryError`
  como subclases de `MeasureError` (reemplazan a `Dwm3001cError` como raíz).
- `transport/base.py`: protocolo `Transport` + `LineAssembler`.
- `transport/ble_link.py`: `BleTransport` (BLE/NUS sobre `bleak`).
- `core/models.py`: `DeviceInfo`, `CalKey`, `Measurement`, `ChipId`,
  `RangingStats`.
- `core/parsers.py`: `is_ok`, `parse_stat`, `parse_calkey_line`,
  `parse_listcal`, `parse_session_info`, `parse_decaid`.
- `core/client.py`: `DwmCliClient` — **sin** `restore()` ni
  `enable_uart_output()` (comandos destructivos que `CLAUDE.md` prohíbe
  automatizar; al no existir el método, no se pueden invocar por error).
- `ranging/session.py`: `SessionParams` pasa a estar definida localmente
  (mismo contenido que la versión de `dwm3001c_cli.calibration.sampler`,
  ya no importada).
- `pyproject.toml`: agrega `bleak>=3.0` a las dependencias base, retira el
  override de mypy para `dwm3001c_cli.*`.
- `tests/fakes.py`: `FakeTransport` + `FakeBleakClient`, portados.
- Tests portados: `tests/test_core_parsers.py`, `tests/test_core_client.py`,
  `tests/test_transport_ble_link.py` (incluye los casos de los bugs reales
  ya resueltos en el repo hermano: buffer colgado sin cierre, fragmentación
  arbitraria de notificaciones BLE, filtrado del prompt de shell,
  reconexión automática tras inactividad).

Criterio de aceptación: `pip install -e .[dev]` sin ningún paso adicional
(ya no hace falta instalar `dwm3001c_cli`); `ruff check`, `ruff format
--check`, `mypy src` y `pytest -m "not hardware"` en verde.

## 5. F3 — Medición de un par (`pair_runner.py`)

```python
def run_pair(
    anchor_a: Anchor,
    anchor_b: Anchor,
    *,
    session: SessionParams,
    n_samples: int,
    ble_timeouts: dict[str, float],
) -> MeasuredPair:
    """Conecta a ambos nodos, configura A=RESPF/B=INITF, promedia n_samples
    lecturas SUCCESS de SESSION_INFO_NTF, detiene y desconecta ambos."""
```

Secuencia exacta (ver [protocolo-ble-qorvo.md](protocolo-ble-qorvo.md) §3-4):

1. Conectar BLE a `anchor_a` y `anchor_b` (dos
   `transport.ble_link.BleTransport` + dos `core.client.DwmCliClient`,
   ambos ya portados y disponibles desde F2b — ver
   [arquitectura.md](arquitectura.md) §2.3.1 —, timeouts desde
   `ble_timeouts`).
2. `qorvo on` en ambos, esperar settle.
3. `qorvo STOP` + `qorvo STAT` en ambos, confirmar modo `NONE`.
4. `RESPF` en `anchor_a`, después `INITF` en `anchor_b` (parámetros
   completos, `ADDR`/`PADDR` cruzados vía `addressing.py`).
5. Leer notificaciones del cliente iniciador hasta juntar `n_samples`
   muestras `SUCCESS` o agotar un timeout máximo (usar
   `qorvo_command_timeout`/`session_end_timeout` de `ble_timeouts` como
   referencia de orden de magnitud, ajustar si hace falta).
6. `qorvo STOP` en ambos, `qorvo off` en ambos, desconectar.
7. Si algún paso falla (conexión, timeout, 0 muestras SUCCESS): no lanzar
   la excepción hacia arriba sin capturarla en `campaign.py` — un par
   fallido no debe abortar la campaña completa (igual criterio que
   `validation/runner.py` del repo hermano).

`MeasuredPair`: `anchor_a`, `anchor_b`, `distance_cm_samples: list[int]`,
`mean_cm: float | None`, `std_cm: float | None`, `n_success: int`,
`n_requested: int`, `error: str | None`.

Tests: con fakes de `DwmCliClient`/`BleTransport` (mismo patrón
`FakeTransport` del repo hermano) alimentados con notificaciones
`SESSION_INFO_NTF` capturadas reales — no requieren hardware. Casos
implementados en `tests/test_ranging_pair_runner.py`: todas SUCCESS,
mezcla SUCCESS/RX_TIMEOUT, 0% SUCCESS (marca el par como error, no
crashea), fallo de conexión BLE. Ejercitan `BleTransport`/`DwmCliClient`
reales inyectando un `FakeBleakClient` scripteado (no un doble de más
alto nivel), para probar el código de producción real.

**Pendiente:** tests marcados `@pytest.mark.hardware` (excluidos por
defecto) que corran `run_pair` contra dos nodos reales y verifiquen que
la distancia medida esté en un rango físicamente razonable — no
implementados todavía, requieren hardware disponible para escribirlos
contra capturas reales (no inventar el formato de respuesta).

## 6. F4 — Campaña completa (`campaign.py`)

```python
def run_campaign(
    ambiente: Ambiente,
    *,
    session: SessionParams,
    n_samples: int,
    on_pair_done: Callable[[MeasuredPair], None] | None = None,
) -> list[MeasuredPair]:
    """Itera geometry.pairs.all_pairs(ambiente.anchors), corre pair_runner.run_pair
    por cada uno, no aborta si un par falla, soporta callback de progreso
    (para reusar desde una futura GUI)."""
```

Criterio de aceptación: sobre un ambiente fake de 3 anclas (3 pares), con
`pair_runner.run_pair` mockeado, `run_campaign` devuelve 3 resultados
incluso si uno de los tres levanta una excepción simulada.

## 7. F5 — Reporte

`report/models.py`:
```python
@dataclass(frozen=True)
class PairResult:
    anchor_a: str          # nombre
    anchor_b: str          # nombre
    distance_calc_m: float
    distance_measured_m: float | None   # None si el par falló
    error_abs_cm: float | None
    error_pct: float | None
    n_samples_success: int
    n_samples_requested: int
    estado: Literal["PASS", "FAIL", "ERROR"]
```

`estado` se calcula en `report/build.py`: `ERROR` si
`distance_measured_m is None`; si no, `PASS` si `error_abs_cm` está dentro
de una tolerancia configurable (default a definir junto con el usuario —
sugerido 5 cm, marcar `TODO(confirmar-con-usuario)` si se implementa antes
de tener el valor confirmado), si no `FAIL`.

`report/write.py`: escribe `reports/medicion-<sala_id>-<YYYYMMDD-HHMMSS>.json`
y `.md`, mismo patrón que `validation/report.py` del repo hermano:

- JSON: `{ambiente: {...}, fecha (ISO), resumen: {pass, fail, error, total},
  resultados: [PairResult asdict, ...]}`.
- Markdown: título, blockquote con `> **Ambiente:** ... · **Fecha:** ...`,
  línea en negrita con el resumen, tabla
  `| Par | Distancia calculada (m) | Distancia medida (m) | Error (cm) | Error (%) | Estado |`,
  y una sección aparte solo para los pares en `ERROR`/`FAIL` con detalle
  (muestras recibidas, excepción si la hubo).

Tests: sobre una lista de `PairResult` fija, verificar contenido exacto
del JSON y presencia/ausencia de la sección de fallos en el Markdown.

## 8. F6 — CLI

```
imop-measure run --environment environments/sala_20.toml [--samples 30] [--tolerance-cm 5] [--report-dir reports/]
```

`app/cli.py`: Typer app, comando `run`. Flujo: `config.loader.load_ambiente`
→ `geometry.pairs.all_pairs` + `geometry.distance.euclidean_distance` →
`ranging.campaign.run_campaign` (con `on_pair_done` para progreso en vivo
vía Rich) → `report.build` → `report.write`. Manejo de errores con un
`_error_boundary()` análogo al del repo hermano (traduce `MeasureError` a
exit code 1 con mensaje legible, sin traceback crudo salvo `--verbose`).

Criterio de aceptación: correr `imop-measure run --environment
environments/sala_20.toml` contra hardware real produce un reporte
completo en `reports/`.

## 9. F7 — Herramienta visual (roadmap, no implementar todavía)

Cuando F6 esté validado contra hardware real: agregar `gui/` siguiendo el
mismo patrón que `dwm3001c_cli.gui` (PySide6 + pyqtgraph como dependencias
opcionales `[gui]`, ver `CLAUDE.md` §4). La GUI consume `config/`,
`geometry/`, `ranging/campaign.run_campaign` (con `on_pair_done` para
progreso) y `report/` **sin modificarlos** — si hace falta cambiar algo de
esas capas para que la GUI funcione, es señal de que F0-F6 dejaron una
abstracción incorrecta y hay que corregirla ahí, no parchear desde la GUI.
No hay fecha ni alcance detallado todavía — se especifica en detalle
cuando se llegue a esta fase.

## 10. Resumen de valores por defecto

| Parámetro | Default | Fuente |
|---|---|---|
| `CHAN` | 9 | `docs/protocolo-ble-qorvo.md` §3 |
| `PRFSET` | `BPRF4` | ídem |
| `PCODE` | 10 | ídem |
| `SLOT` | 2400 | ídem |
| `BLOCK` | 200 | ídem |
| `ROUND` | 25 | ídem |
| `RRU` | `DSTWR` | ídem |
| `VUPPER` | `01:02:03:04:05:06:07:08` | ídem |
| `n_samples` por par | por definir (sugerido 30) | `TODO(confirmar-con-usuario)` |
| tolerancia de error | por definir (sugerido 5 cm) | `TODO(confirmar-con-usuario)` |
| `[ble_timeouts]` | ver `environments/sala_20.toml` | mismo esquema que `i-mop-qorvo-CLI-script` |
