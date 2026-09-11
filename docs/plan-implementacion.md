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
| F3 | `ranging/pair_runner.py`: medición de un par de nodos, con fakes para test | `feature/f3-sesion-ranging` | F2b | ✅ (verificado contra hardware real 2026-09-07) |
| F4 | `ranging/campaign.py`: orquestación de todos los pares del ambiente | `feature/f4-orquestacion-campania` | F3 | ✅ |
| F5 | `report/`: construcción y escritura de reporte JSON + Markdown | `feature/f5-reporte` | F1, F4 | ✅ |
| F6 | `app/cli.py`: comando `imop-measure run`, end-to-end | `feature/f6-cli` | F5 | ✅ (verificado contra hardware real 2026-09-07) |
| F7 | Herramienta visual (GUI) — reusa `ranging/`, `report/`, `config/`, `geometry/` sin cambios | `feature/f7-gui` | F6 (validado en hardware real) | ✅ (verificado contra hardware real 2026-09-07) |

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
    *,
    initiator: Anchor,
    responder: Anchor,
    session: SessionParams,
    n_samples: int,
    ble_timeouts: dict[str, float],
) -> MeasuredPair:
    """Conecta a ambos nodos, configura responder=RESPF/initiator=INITF,
    promedia n_samples lecturas SUCCESS de SESSION_INFO_NTF, detiene y
    desconecta ambos."""
```

`initiator`/`responder` son keyword-only a propósito: la versión inicial
de F3 tenía `anchor_a`/`anchor_b` posicionales con una convención
implícita (`a`=respondedor, `b`=iniciador) fácil de invocar al revés sin
que nada lo marque como error — se corrigió después de F4 (ver más abajo)
a nombres explícitos.

Secuencia exacta (ver [protocolo-ble-qorvo.md](protocolo-ble-qorvo.md) §3-4):

1. Conectar BLE a `responder` e `initiator` (dos
   `transport.ble_link.BleTransport` + dos `core.client.DwmCliClient`,
   ambos ya portados y disponibles desde F2b — ver
   [arquitectura.md](arquitectura.md) §2.3.1 —, timeouts desde
   `ble_timeouts`). El respondedor se conecta primero.
2. `qorvo on` en ambos, esperar settle.
3. `qorvo STOP` + `qorvo STAT` en ambos, confirmar modo `NONE`.
4. `RESPF` en `responder`, después `INITF` en `initiator` (parámetros
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

`MeasuredPair`: `initiator: Anchor`, `responder: Anchor`,
`distance_cm_samples: list[int]`, `mean_cm: float | None`,
`std_cm: float | None`, `n_success: int`, `n_requested: int`,
`error: str | None`.

Tests: con fakes de `DwmCliClient`/`BleTransport` (mismo patrón
`FakeTransport` del repo hermano) alimentados con notificaciones
`SESSION_INFO_NTF` capturadas reales — no requieren hardware. Casos
implementados en `tests/test_ranging_pair_runner.py`: todas SUCCESS,
mezcla SUCCESS/RX_TIMEOUT, 0% SUCCESS (marca el par como error, no
crashea), fallo de conexión BLE, y el formato real de 3 fragmentos de
`SESSION_INFO_NTF` (ver más abajo). Ejercitan `BleTransport`/`DwmCliClient`
reales inyectando un `FakeBleakClient` scripteado (no un doble de más
alto nivel), para probar el código de producción real.

**Verificado contra hardware real (2026-09-07):** `test_run_pair_against_real_nodes`
(`@pytest.mark.hardware`) corrió `run_pair` contra `uwb_node_10` y
`uwb_node_11` físicos de `environments/sala_20.toml` — **15/15 muestras
SUCCESS, distancia media 341.9 cm, desvío estándar 2.1 cm**, sin ningún
error. De paso se descubrió que el formato real de `SESSION_INFO_NTF`
sobre estos nodos llega en **3** fragmentos (no 2 como documentaba el
repo hermano) — ver [protocolo-ble-qorvo.md](protocolo-ble-qorvo.md)
sección 4 para el detalle exacto; el parser tolerante ya lo maneja bien
sin cambios de código, y ese formato real quedó fijado como test de
regresión (`test_run_pair_handles_real_three_fragment_notification`).
**La Fase F3 queda cerrada.**

## 6. F4 — Campaña completa (`campaign.py`)

```python
def run_campaign(
    ambiente: Ambiente,
    *,
    session: SessionParams,
    n_samples: int,
    on_pair_done: Callable[[MeasuredPair], None] | None = None,
) -> list[MeasuredPair]:
    """Itera cada nodo como iniciador contra todos los demas como
    respondedores (N*(N-1) mediciones direccionales), corre
    pair_runner.run_pair por cada una, no aborta si una falla, soporta
    callback de progreso (para reusar desde una futura GUI)."""
```

**Decisión tomada (pedido explícito del usuario tras cerrar F3):** cada
nodo del ambiente mide contra **todos** los demás en **ambos roles** —
primero como iniciador contra cada respondedor, después ese mismo nodo
pasa a respondedor cuando le toca el turno a otro como iniciador. Esto da
`N*(N-1)` mediciones direccionales (permutaciones, no combinaciones) en
vez de `N*(N-1)/2` pares sin orden — a diferencia de la distancia
geométrica (`geometry.pairs.all_pairs`, simétrica), la distancia UWB
medida puede diferir según quién inicia, así que:

- Las dos direcciones de un mismo par físico (`A→B` y `B→A`) se miden y
  se **reportan por separado** (no se promedian) — permite detectar
  asimetrías de hardware/protocolo entre nodos. Ver F5, `PairResult`.
- Por ahora se reconecta todo (ambos nodos) en cada medición direccional,
  aunque el mismo nodo actúe de iniciador varias veces seguidas contra
  distintos respondedores — más simple de razonar, y con la cantidad de
  nodos actual (2) el costo extra de reconectar es mínimo. Reusar la
  conexión BLE del iniciador entre respondedor y respondedor (evitar
  reconectarlo en cada vuelta) es una optimización de `pair_runner.py`
  que se puede hacer más adelante si el tiempo total de campaña con más
  nodos lo justifica — no implementada todavía.
- `pair_runner.run_pair` pasó a tener `initiator`/`responder`
  keyword-only en vez de `anchor_a`/`anchor_b` posicionales (ver F3
  arriba), para que quién es cada rol quede explícito en cada llamado.

Criterio de aceptación: sobre un ambiente fake de 3 anclas (`N*(N-1)=6`
mediciones direccionales), con `pair_runner.run_pair` mockeado,
`run_campaign` devuelve 6 resultados incluso si una de las seis levanta
una excepción simulada.

**Verificado contra hardware real (2026-09-07):**
`test_run_campaign_against_real_nodes` (`@pytest.mark.hardware`) corrió
`run_campaign` de punta a punta contra las 2 anclas activas de
`environments/sala_20.toml` — las 2 mediciones direccionales posibles
(`uwb_node_10→uwb_node_11` y `uwb_node_11→uwb_node_10`) completaron sin
error. Con solo 2 nodos no se pudo ejercitar "varias mediciones, una
falla" contra hardware real (hacen falta 3+); ese caso sigue cubierto
solo con mocks. **La Fase F4 queda cerrada.**

## 7. F5 — Reporte

`report/models.py`:
```python
@dataclass(frozen=True)
class PairResult:
    initiator: str          # nombre — quien inicio esta medicion direccional
    responder: str          # nombre
    distance_calc_m: float  # geometrica, simetrica: la misma para A->B y B->A
    distance_measured_m: float | None   # None si la medicion fallo
    error_abs_cm: float | None
    error_pct: float | None
    n_samples_success: int
    n_samples_requested: int
    estado: Literal["PASS", "FAIL", "ERROR"]
```

Una fila por `MeasuredPair` de `run_campaign` (F4) — es decir, **una fila
por dirección**, no una por par físico: el mismo par de nodos aparece dos
veces (`A→B` y `B→A`), cada una con su propia `distance_measured_m` pero
la misma `distance_calc_m` (la distancia geométrica no tiene dirección).
Ver decisión de F4 más arriba.

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

**Implementado:** `DEFAULT_TOLERANCE_CM = 5.0` en `report/build.py`, con
el `TODO(confirmar-con-usuario)` explícito en el código — sigue siendo un
valor sugerido, no confirmado; F6 lo va a exponer como `--tolerance-cm`
con este mismo default, así que confirmarlo más adelante no requiere
tocar `report/`. Se agregó un campo `detalle: str | None` a `PairResult`
(no estaba en el esquema original del plan) para poder mostrar la
excepción de `MeasuredPair.error` en la sección de fallos del Markdown sin
tener que recorrer los `MeasuredPair` originales por separado. **La Fase
F5 queda cerrada** (sin verificar contra hardware real: no hay BLE
involucrado en `report/`, todo el input ya viene resuelto en
`MeasuredPair`).

**Revisión posterior (pedido explícito del usuario, tras ver el primer
reporte real):** el formato se rediseñó para ser legible directamente por
el usuario, no solo como dato crudo. Cambios sobre el esquema de arriba —
ver [formato-reporte.md](formato-reporte.md) para el detalle completo y
un ejemplo real:

- `PairResult.error_abs_cm`/`.error_pct` (sin signo, en cm) se
  reemplazaron por `diff_m`/`diff_pct` (**con signo**, en metros:
  `medida − calculada`) — más legible y permite ver si se midió de más o
  de menos, no solo cuánto.
- Nuevo campo `necesita_revision: bool`: umbral independiente de `estado`
  (default 30 cm, `DEFAULT_REVIEW_THRESHOLD_CM` en `report/build.py`,
  expuesto como `--review-threshold-cm` en F6) para distinguir "un poco
  fuera de tolerancia" (ruido normal) de "diferencia enorme, revisar
  datos cargados". `summarize()` agrega un conteo `revisar` al resumen.
- `write_reports()` ahora acepta también `sala_nombre`, `samples`,
  `tolerance_cm` y `review_threshold_cm` (antes solo `sala_id`) para
  mostrarlos en el encabezado del reporte.
- Markdown rediseñado: título con nombre de sala, fecha y hora legible
  (`dd/mm/aaaa hh:mm:ss`), línea de criterios usados, sección "Resumen
  ejecutivo" con emoji por estado, tabla de detalle numerada con columnas
  `Diferencia (m)` / `Diferencia (%)` / `Revisar` separadas, y la sección
  de fallos renombrada a "Mediciones que requieren revisión" (incluye
  tanto `estado != PASS` como `necesita_revision = true`).
- Estos emoji/flechas (`✅`, `→`, etc.) son seguros en los archivos
  (`encoding="utf-8"` explícito) pero **no** en lo que se imprime a
  terminal — ver el hallazgo de F6 sobre la consola legacy de Windows.

**[2026-09-11, pedido explícito del usuario]** `necesita_revision` y
`--review-threshold-cm` se **eliminaron** — el usuario los consideraba
redundantes con `estado`/`--tolerance-cm` (que ya cubre la señal de
"algo anda mal" en esta fila). En su lugar se agregaron `min_measured_cm`/
`max_measured_cm`/`mode_measured_cm` a `PairResult`, estadísticas
descriptivas de las propias muestras (igual que `std_measured_cm`, no
comparan contra lo calculado) — ver
[formato-reporte.md](formato-reporte.md) para el esquema vigente.

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

**Verificado contra hardware real (2026-09-07):** el comando corrió de
punta a punta contra los 2 nodos reales — 30/30 muestras SUCCESS en
ambas direcciones (`UWB-Node-10↔UWB-Node-11`, ~3.48 m medidos, consistente
entre direcciones) y generó `reports/medicion-20-<timestamp>.{json,md}`
completos. El reporte marcó ambas mediciones `FAIL` — **correcto**, no es
un bug: `posicion` en `sala_20.toml` sigue siendo un valor `TODO` (no la
ubicación física real de los nodos), así que la distancia calculada
(0.59 m) no tiene por qué coincidir con la medida.

De paso se encontró un bug real: `console.print`/`rich` con caracteres no
ASCII (`→`, usado en el progreso por consola) hace `UnicodeEncodeError` y
crashea en la consola legacy de Windows — no degrada con un reemplazo.
Se corrigió reemplazando esos caracteres por equivalentes ASCII (`->`)
en todo lo que se imprime a terminal; ver `CLAUDE.md` §2. Los reportes en
disco (`report/write.py`) no estaban afectados (usan `encoding="utf-8"`
explícito) y mantienen `→`/acentos sin problema. **La Fase F6 queda
cerrada.**

## 9. F7 — Herramienta visual

**Alcance de la v1 (decidido con el usuario tras cerrar F6):** una sola
ventana que corre una campaña completa con progreso en vivo — el
equivalente visual de `imop-measure run`, no un visor de reportes ya
generados ni un editor del TOML (eso queda para una v2 si hace falta).
Framework: **PySide6** (ya anticipado en `CLAUDE.md` §4 y en
`pyproject.toml` como extra `[gui]`), mismo patrón de threading que
`dwm3001c_cli.gui` del repo hermano — ver decisión abajo.

`gui/` consume `config/`, `ranging/campaign.run_campaign` (con
`on_pair_done` para progreso) y `report/` **sin modificarlos** — si hace
falta cambiar algo de esas capas para que la GUI funcione, es señal de
que F0-F6 dejaron una abstracción incorrecta y hay que corregirla ahí, no
parchear desde la GUI.

**Decisión — threading:** `run_campaign` es bloqueante (conexiones BLE
reales, minutos de duración) — correrlo en el hilo de UI congelaría la
ventana. Igual que `dwm3001c_cli.gui.workers`: un `QObject` (no una
subclase de `QThread`) movido a un `QThread` con `moveToThread()`, no
`QThreadPool` (necesita señales de progreso continuas, no un resultado
único). El `run()` del worker atrapa **cualquier** excepción
(`except Exception`, no solo `MeasureError`) y la emite por señal
`failed` — el repo hermano documenta un bug real: un worker que deja
escapar una excepción en silencio deja el botón de "Ejecutar" trabado
para siempre sin ningún mensaje. Un helper `start_worker()` (portado del
mismo módulo) arma el `QThread` y conecta `started`/`finished`.

Módulos (`src/imop_measure/gui/`):

| Módulo | Responsabilidad |
|---|---|
| `app.py` | Entry point `main_gui()` (comando `imop-measure-gui`): crea `QApplication` + `MainWindow`. |
| `models.py` | `CampaignResultsModel(QAbstractTableModel)`: misma tabla que el resumen del CLI (iniciador, respondedor, calculada, medida, mínimo/máximo/moda/desviación, diferencia m/%, estado), coloreada por `estado`. Se llena fila por fila a medida que llegan resultados, no de una vez al final. |
| `worker.py` | `CampaignWorker(QObject)`: `run()` hace `load_ambiente` → `ranging.campaign.run_campaign` (cada `on_pair_done` arma un `PairResult` de a uno vía `report.build.build_results([medido], ...)` y lo emite por señal `pair_measured`, acumulándolo también en una lista local) → `report.write.write_reports` con esa lista acumulada. Señales: `pair_measured(object)`, `finished(list, object, object)` (resultados, path json, path md), `failed(str)`. También expone `start_worker()`. |
| `main_window.py` | `MainWindow(QMainWindow)`: formulario (archivo de ambiente con selector `QFileDialog`, muestras, tolerancia, carpeta de reportes — mismos parámetros que `imop-measure run`), botón "Ejecutar campaña", tabla en vivo, etiqueta de estado/resumen, etiqueta con las rutas del reporte al terminar. |

**Dependencias:** solo `PySide6` por ahora. `pyqtgraph` se saca de
`pyproject.toml` extra `[gui]` hasta que haga falta un gráfico de verdad
(ej. un plano de la sala con los nodos) — no instalar una dependencia sin
usarla (`CLAUDE.md` §4).

**Tests:** con `pytest-qt` (nuevo dev-dependency, mismo que el repo
hermano). `CampaignWorker.run()` con `load_ambiente`/`run_campaign`/
`write_reports` mockeados (sin BLE real, sin ventana): verifica que emite
`pair_measured` por cada resultado, `finished` con la lista completa y
las rutas del reporte, y que **nunca deja escapar una excepción** —
siempre emite `failed` en su lugar. `CampaignResultsModel`: agregar,
limpiar, `rowCount`/`data` devuelven lo esperado. `MainWindow` se deja
sin test de interacción profunda por ahora (ver nota del repo hermano:
las vistas son la parte más costosa de testear de una GUI Qt) — alcanza
con confirmar que se construye sin error.

Criterio de aceptación: `imop-measure-gui` abre una ventana, se puede
elegir `environments/sala_20.toml`, correr una campaña contra hardware
real sin congelar la ventana, ver el progreso fila por fila, y terminar
mostrando las rutas del reporte generado — mismo resultado que
`imop-measure run`, mostrado visualmente.

**Verificado contra hardware real (2026-09-07):** `imop-measure-gui`
abre la ventana correctamente (confirmado por título de ventana, sin
capturas de pantalla — ver nota de privacidad más abajo). Disparando
`_on_run_clicked()` programáticamente (mismo camino de código que un
click real) contra los 2 nodos físicos: la campaña completa corrió en
~95 s en el `QThread` de background mientras el bucle de eventos de la
ventana siguió respondiendo (`processEvents()` devolvió el control 1885
veces durante esos 95 s, sin bloquearse ni una vez) — confirma que la UI
no se congela mientras mide. Terminó con 2 resultados y el reporte
escrito correctamente. **La Fase F7 (v1) queda cerrada.**

> **Nota de proceso:** al intentar verificar la ventana visualmente se
> tomó por error una captura de **toda la pantalla** (no solo la
> ventana de la app), que expuso de forma no intencional una
> conversación privada de Mattermost del usuario en primer plano en ese
> momento. Se borró el archivo de inmediato sin usar ni referenciar su
> contenido. La verificación real se hizo sin capturas de pantalla,
> comprobando el título de la ventana por proceso
> (`Get-Process | Where-Object MainWindowTitle`) y validando el flujo
> mediante código, no capturas visuales.

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
| `n_samples` por dirección | 30 (`--samples`) | implementado, sin confirmar como valor final — `TODO(confirmar-con-usuario)` en `app/cli.py`/`gui/main_window.py` |
| tolerancia PASS/FAIL | 5.0 cm (`--tolerance-cm`) | `DEFAULT_TOLERANCE_CM` en `report/build.py`, mismo estado de confirmación que arriba |
| `[ble_timeouts]` | ver `environments/sala_20.toml` | mismo esquema que `i-mop-qorvo-CLI-script` |
