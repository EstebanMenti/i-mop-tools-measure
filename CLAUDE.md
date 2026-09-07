# CLAUDE.md — Guía para asistentes de IA en este repositorio

> Este archivo es la referencia obligatoria para cualquier asistente de IA (o
> desarrollador) que trabaje en `i-mop-tools-measure`. Si algo en el código
> contradice lo que dice aquí, se actualiza este archivo en el mismo PR que
> corrige el código — nunca se deja desactualizado.

## 1. Contexto del proyecto

`i-mop-tools-measure` mide la **distancia real** entre nodos UWB (Qorvo
DW3xxx, accedidos vía el puente BLE nRF52840 de `I-mop-nrf52840-fw`) y la
compara contra la **distancia geométrica calculada** a partir de las
posiciones `[x, y, z]` declaradas en un archivo de ambiente TOML
(`environments/sala_XX.toml`, ver [docs/formato-ambiente-toml.md](docs/formato-ambiente-toml.md)).

Flujo de alto nivel:

1. Leer `environments/sala_XX.toml` → lista de nodos (nombre, MAC BLE,
   dirección corta UWB, posición).
2. Calcular la distancia euclídea entre **todos los pares** de nodos
   (referencia "verdadera", asumiendo las posiciones correctas).
3. Para cada par: conectar por BLE a los dos nodos, configurar uno como
   **iniciador** (`INITF`) y el otro como **respondedor** (`RESPF`) con IDs
   coherentes, arrancar una sesión de ranging UWB, leer N muestras de
   distancia medida y promediarlas.
4. Repetir para todos los pares del ambiente.
5. Generar un reporte (JSON + Markdown) con distancia calculada vs. medida,
   error absoluto y porcentual por par.

Hoy es un **script/CLI**. La intención declarada del proyecto es que
evolucione a una **herramienta visual** (GUI) una vez validado el flujo por
línea de comandos — ver [docs/plan-implementacion.md](docs/plan-implementacion.md)
fase F7. Por eso la capa `core`/`ranging`/`geometry`/`report` **no debe saber
nada de Typer/Rich** (ver §5): así se puede construir una GUI encima sin
reescribir la lógica, tal como hizo `i-mop-qorvo-CLI-script` con `dwm-gui`.

### 1.1 Repos hermanos — leer antes de tocar protocolo BLE/UWB

| Repo | Qué aporta |
|---|---|
| `../i-mop-qorvo-CLI-script` | CLI Python ya validada en hardware real contra estos mismos nodos. Su transporte BLE (`transport/ble_link.py`) y cliente de comandos Qorvo (`core/client.py`, `core/parsers.py`) están **portados** en `src/imop_measure/{transport,core}/` (ver [docs/arquitectura.md](docs/arquitectura.md) decisión D1) — este proyecto no depende de tenerlo instalado, pero cualquier fix de protocolo descubierto ahí debe portarse acá a mano. |
| `../I-mop-nrf52840-fw` | Firmware del puente BLE. `doc/00_BLE_Protocol_Specification.md` es la especificación autoritativa del protocolo GATT y del comando `qorvo`. |

Referencia condensada y específica a este proyecto:
[docs/protocolo-ble-qorvo.md](docs/protocolo-ble-qorvo.md). Para el detalle
exhaustivo de cada comando de firmware, consultar
`../i-mop-qorvo-CLI-script/docs/referencia-comandos-fw110.md`.

### 1.2 Reglas de dominio críticas (no reinventar mal)

- El comando que llega al Qorvo por BLE es **`qorvo <texto>`** (ej.
  `qorvo STAT`, `qorvo INITF -CHAN=9 ...`). El viejo comando `uwb on/off` fue
  **unificado en `qorvo on`/`qorvo off`** y ya no existe en el firmware del
  puente — no usar `uwb` como prefijo de comando en ningún lado del código
  nuevo.
- `INITF`, `RESPF` y `LISTENER` son mutuamente excluyentes y solo se pueden
  lanzar en modo `NONE` (`qorvo STOP` + `qorvo STAT` para confirmar antes de
  arrancar una sesión nueva).
- Pasar **cualquier** parámetro a `INITF`/`RESPF` resetea todos los demás a
  su valor por defecto. Siempre enviar el **set completo** de parámetros de
  sesión (`CHAN`, `PRFSET`, `PCODE`, `SLOT`, `BLOCK`, `ROUND`, `RRU`, `ID`,
  `VUPPER`, `ADDR`, `PADDR`), nunca un subconjunto.
- La distancia **no se puede pedir** con un comando de consulta: llega de
  forma asíncrona como notificación `SESSION_INFO_NTF` mientras la sesión de
  ranging está activa. Hay que escuchar el canal de notificaciones BLE
  (NUS TX) y quedarse solo con las líneas `status="SUCCESS"`, promediando
  varias muestras (repo hermano usa 100 para calibración; para este proyecto
  ver el default en `docs/protocolo-ble-qorvo.md`).
- El puente `qorvo <cmd>` es estrictamente request/response y, por diseño,
  no reenvía datos asíncronos — pero en la práctica las notificaciones de
  ranging sí llegan igual por el canal de notificaciones NUS TX una vez
  arrancada la sesión (validado en hardware real, ver
  `../i-mop-qorvo-CLI-script/docs/verificacion-comandos-responder-ble.md`).
  Diseñar la lectura tolerando pérdida/reordenamiento de notificaciones, no
  asumir un stream perfecto ni ordenado.
- `uwb_addr` del TOML (formato `"00:02"`, dos bytes hex) se traduce a un
  entero **decimal** para `-ADDR=`/`-PADDR=` (ej. `"00:02"` → `2`).
- **Nunca** ejecutar `RESTORE`, escrituras NVM, ni `SAVE` durante una sesión
  de ranging activa de forma automática — son operaciones destructivas o
  que pueden dejar el nodo en un estado inconsistente.

## 2. Reglas de programación

- Python **≥ 3.11** (se usa `tomllib` de la stdlib para leer TOML, no
  agregar `tomli` como dependencia).
- `.venv/` nunca se versiona. Proyecto configurado con `pyproject.toml`
  (PEP 621), instalable con `pip install -e .[dev]`.
- Formateo y lint con **ruff** (`ruff format`, `ruff check`), largo de línea
  100.
- **mypy** en modo `strict` sobre `src/`.
- Docstrings **obligatorios**, en español, estilo Google. Los
  identificadores (nombres de función, clase, variable) van en **inglés**.
- Comentarios en español, solo cuando explican un motivo no obvio
  (restricción del protocolo, workaround de firmware, etc.) — no explican
  qué hace el código.
- Usar el módulo `logging`, nunca `print` fuera de la capa de presentación
  (`app/`). El tráfico BLE crudo (comandos enviados, líneas recibidas) debe
  quedar logueable en nivel `DEBUG`.
- Jerarquía de excepciones propia, con raíz `MeasureError` (vive en
  `src/imop_measure/errors.py`, a crear en la Fase F1 — análogo a
  `Dwm3001cError` del repo hermano).
- Nada de efectos secundarios peligrosos detrás de nombres inocuos (una
  función `connect()` no debería, de paso, lanzar `RESTORE`).

## 3. Testing

- `pytest`. Los tests en `tests/` **no requieren hardware** por defecto:
  se usan transportes/clientes falsos (`tests/fakes.py`: `FakeTransport` y
  `FakeBleakClient`, portados del repo hermano) con capturas reales de
  firmware como fixtures.
- Tests que sí requieren nodos físicos conectados se marcan
  `@pytest.mark.hardware` y quedan excluidos por defecto
  (`-m "not hardware"`).
- Todo parser de protocolo (notificaciones `SESSION_INFO_NTF`, `STAT`, etc.)
  necesita tests unitarios con salidas reales de firmware como casos —no
  inventar formatos de respuesta.
- Gate antes de cada commit/PR: `ruff check`, `ruff format --check`,
  `mypy src`, `pytest -m "not hardware"`.

## 4. Dependencias

Mínimas y justificadas. Base autorizada: `typer`, `rich`, `bleak` (BLE).
El transporte BLE y el cliente de comandos Qorvo están **portados** dentro
de este proyecto (`src/imop_measure/{transport,core}/`, ver
[docs/arquitectura.md](docs/arquitectura.md) decisión D1) — no reimplementar
ni volver a depender del repo hermano en tiempo de ejecución; si aparece un
fix de protocolo en `i-mop-qorvo-CLI-script`, portarlo a mano acá.
Dev: `pytest`, `ruff`, `mypy`.

Cualquier dependencia nueva se agrega solo si está en esta lista o si el
usuario la aprueba explícitamente — no instalar paquetes "por si acaso".

## 5. Estructura del repositorio

```
i-mop-tools-measure/
├── CLAUDE.md                  # este archivo
├── README.md
├── pyproject.toml
├── environments/               # archivos de ambiente sala_XX.toml (versionados)
│   └── sala_20.toml
├── docs/                       # documentación del proyecto (ver docs/README.md)
├── src/imop_measure/
│   ├── config/                 # lectura y validación de environments/*.toml
│   ├── geometry/                # distancia euclídea entre posiciones, generación de pares
│   ├── transport/                # BleTransport (BLE/NUS, portado — ver arquitectura.md D1)
│   ├── core/                     # DwmCliClient + parsers del protocolo Qorvo (portado)
│   ├── ranging/                 # orquestación de sesiones BLE/UWB por par de nodos
│   ├── report/                  # construcción y escritura de reportes JSON/MD
│   └── app/                     # CLI (Typer) — capa de presentación
├── tests/
├── reports/                    # salida en tiempo de ejecución (gitignored)
└── logs/                       # salida en tiempo de ejecución (gitignored)
```

Regla de dependencias entre capas, **una sola dirección**:

```
app  →  ranging  →  { geometry, config, core → transport }
app  →  report
```

- `geometry/` y `config/` no saben nada de BLE ni de Typer.
- `core/` no sabe nada de Typer/Rich; `transport/` solo sabe hablar BLE
  (`bleak`), no conoce el protocolo de comandos del Qorvo.
- `ranging/` no sabe nada de Typer/Rich (para poder reusarse desde una
  futura GUI).
- `report/` no sabe cómo se obtuvieron los datos, solo los recibe y los
  formatea/escribe.

## 6. Reglas de documentación

- Toda la documentación en español, en Markdown, con el mismo estilo que
  [docs/README.md](docs/README.md) (encabezados numerados, tablas, bloques
  `> **Nota**`/`> **Advertencia**`).
- Todo documento nuevo en `docs/` empieza con un encabezado `>` que indica
  **propósito** y **alcance**, y se agrega a la tabla de
  [docs/README.md](docs/README.md) en el mismo PR.
- Cualquier afirmación sobre comportamiento del firmware Qorvo o del puente
  BLE debe citar el documento fuente (`docs/protocolo-ble-qorvo.md` o los
  docs de los repos hermanos) o marcarse **[Por verificar en hardware]**.
- El `README.md` raíz se mantiene sincronizado con el estado real del
  código (no describir comandos que todavía no existen sin marcarlos como
  planeados).

## 7. Flujo de trabajo con Git

Convención **unificada** con `i-mop-qorvo-CLI-script` e `I-mop-nrf52840-fw`
para que los tres repos hermanos se manejen igual.

- `main`: rama estable, solo se actualiza por Pull Request (ni siquiera en
  solitario se pushea directo a `main`).
- Ramas de trabajo de corta duración:
  `<tipo>/<descripcion-corta-en-kebab-case>`, con
  `tipo ∈ {feature, fix, docs, chore, refactor}`.
  Ejemplo: `feature/f1-config-geometria`, `docs/protocolo-ble-qorvo`.
- Para trabajo de fase (ver `docs/plan-implementacion.md`), la convención es
  `feature/f<N>-<nombre-fase>` — una rama por fase, PR contra `main` al
  cerrarla.
- Si en algún momento se necesita una rama de banco de pruebas de hardware
  de larga duración (que no se mergea nunca a `main`), usar el patrón ya
  establecido en los repos hermanos: `hardware/<descripcion-corta>`,
  sincronizada periódicamente con `git merge origin/main` (nunca rebase).
- Commits en **Conventional Commits, en español, modo imperativo, sin punto
  final**:
  ```
  feat(ranging): agrega orquestacion de sesion INITF/RESPF por par de nodos
  fix(config): tolera uwb_addr en formato hexadecimal sin ceros a la izquierda
  docs: agrega referencia condensada del protocolo qorvo
  ```
  El `scope` coincide con el nombre del módulo (`config`, `geometry`,
  `ranging`, `report`, `app`, `docs`, `chore`).
- Casi todo cambio pasa por PR, incluso trabajando en solitario.

## 8. Reglas para asistentes de IA

1. **Nunca inventar comportamiento de firmware o del protocolo BLE.** Citar
   `docs/protocolo-ble-qorvo.md` o los docs de los repos hermanos; si algo
   no está documentado, usar un parser tolerante y marcarlo
   `TODO(verificar-con-hardware)`.
2. Seguir las fases de `docs/plan-implementacion.md`. No agregar módulos ni
   dependencias fuera de lo listado en ese plan o en §4 de este archivo sin
   preguntar primero.
3. **Nunca** ejecutar automáticamente `RESTORE`, escrituras NVM, `SAVE`
   durante ranging, ni ningún comando marcado como destructivo en
   `docs/protocolo-ble-qorvo.md` sin confirmación explícita e interactiva
   del usuario.
4. Consistencia de idioma: docs/docstrings/comentarios/commits en español,
   identificadores de código en inglés.
5. Ante un requisito ambiguo (ej. cuántas muestras promediar, qué pasa si
   un nodo no responde), preguntar en vez de decidir en silencio.
6. La lógica de ranging depende de hardware real y no es 100% testeable de
   forma unitaria — separar claramente la parte pura/testeable (parseo,
   cálculo geométrico, formato de reporte) de la parte que requiere
   hardware, y proveer fakes para la primera.
