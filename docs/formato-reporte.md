# Formato del reporte de medición

> **Propósito:** documentar exactamente qué genera `imop-measure run` al
> terminar una campaña: dónde queda el archivo, qué campos tiene el JSON,
> y cómo leer la tabla del Markdown.
> **Alcance:** describe la salida de `report/write.py` (Fase F5). No
> describe cómo se obtienen los datos (ver
> [protocolo-ble-qorvo.md](protocolo-ble-qorvo.md) y
> [arquitectura.md](arquitectura.md) decisión D6).

## 1. Dónde queda el reporte

Cada corrida de `imop-measure run` escribe **dos archivos** en la carpeta
`--report-dir` (default `reports/`, gitignored — ver
[arquitectura.md](arquitectura.md) decisión D5):

```
reports/medicion-<sala_id>-<YYYYMMDD-HHMMSS>.json
reports/medicion-<sala_id>-<YYYYMMDD-HHMMSS>.md
```

`<sala_id>` es el `[sala].id` del archivo de ambiente usado (ver
[formato-ambiente-toml.md](formato-ambiente-toml.md)). Ambos archivos del
mismo run comparten el mismo `<timestamp>`, así que siempre quedan
emparejados por nombre.

## 2. Una fila por dirección, no por par

Por cada dos nodos del ambiente hay **dos filas** en el reporte: una con
cada nodo como iniciador (ver [arquitectura.md](arquitectura.md) decisión
D6). Con `N` anclas activas, el reporte tiene `N·(N-1)` filas. La
distancia *calculada* es la misma en las dos filas de un mismo par físico
(es geométrica, no tiene dirección); la distancia *medida* puede diferir
entre una dirección y la otra.

## 3. Formato JSON

```json
{
  "ambiente": "20",
  "fecha": "2026-09-07T15:13:38.417507-03:00",
  "resumen": { "pass": 0, "fail": 1, "error": 1, "total": 2 },
  "resultados": [
    {
      "initiator": "UWB-Node-10",
      "responder": "UWB-Node-11",
      "distance_calc_m": 0.5915234568468101,
      "distance_measured_m": null,
      "error_abs_cm": null,
      "error_pct": null,
      "n_samples_success": 0,
      "n_samples_requested": 15,
      "estado": "ERROR",
      "detalle": "[WinError -2147483629] Se cerró el objeto."
    },
    {
      "initiator": "UWB-Node-11",
      "responder": "UWB-Node-10",
      "distance_calc_m": 0.5915234568468101,
      "distance_measured_m": 3.4793333333333334,
      "error_abs_cm": 288.78098764865234,
      "error_pct": 488.19870844689,
      "n_samples_success": 15,
      "n_samples_requested": 15,
      "estado": "FAIL",
      "detalle": null
    }
  ]
}
```

(Captura real, `environments/sala_20.toml`, 2026-09-07 — el `ERROR` fue
un fallo transitorio real de conexión BLE en la primera dirección; la
segunda sí midió. El `FAIL` es correcto: `posicion` de esos dos nodos en
el TOML todavía es un valor `TODO`, no la ubicación física real — ver
sección 5.)

| Campo | Tipo | Descripción |
|---|---|---|
| `ambiente` | string | `[sala].id` del archivo de ambiente. |
| `fecha` | string, ISO 8601 con offset de zona horaria | Momento en que terminó la campaña. |
| `resumen.pass` / `.fail` / `.error` / `.total` | int | Conteo de filas por `estado`. |
| `resultados` | array | Una entrada por dirección medida (ver sección 2), cada una con los campos de la tabla siguiente. |

Campos de cada entrada de `resultados` (`PairResult`, ver
`report/models.py`):

| Campo | Tipo | Descripción |
|---|---|---|
| `initiator` | string | Nombre (`Anchor.nombre`) del nodo que actuó como iniciador (`INITF`) en esta dirección. |
| `responder` | string | Nombre del nodo que actuó como respondedor (`RESPF`). |
| `distance_calc_m` | float | Distancia euclídea 3D calculada a partir de `posicion` en el TOML (metros). Simétrica: igual en ambas direcciones del mismo par. |
| `distance_measured_m` | float \| null | Promedio de las muestras `SUCCESS` de `SESSION_INFO_NTF` (metros). `null` si no se pudo medir (ver `estado="ERROR"`). |
| `error_abs_cm` | float \| null | `\|distance_measured_m·100 − distance_calc_m·100\|`. `null` si `distance_measured_m` es `null`. |
| `error_pct` | float \| null | `error_abs_cm` como porcentaje de `distance_calc_m·100`. `null` si `distance_measured_m` es `null` **o** si `distance_calc_m` es `0` (evita división por cero). |
| `n_samples_success` | int | Cuántas muestras `SUCCESS` se juntaron. |
| `n_samples_requested` | int | Cuántas se pidieron (`--samples`). |
| `estado` | `"PASS"` \| `"FAIL"` \| `"ERROR"` | Ver sección 4. |
| `detalle` | string \| null | Mensaje de error si `estado != "PASS"` y hubo una falla real (conexión, timeout, excepción) — `null` si el único problema fue estar fuera de tolerancia. |

## 4. Cómo se calcula `estado`

En `report/build.py`:

1. **`ERROR`** — si `distance_measured_m` es `null` (no se juntó ninguna
   muestra `SUCCESS`: falla de conexión, timeout, excepción inesperada,
   etc.). `detalle` trae el motivo.
2. **`PASS`** — si se midió y `error_abs_cm ≤ tolerancia` (`--tolerance-cm`,
   default `5.0` — ver `DEFAULT_TOLERANCE_CM` en `report/build.py`,
   marcado `TODO(confirmar-con-usuario)`: es un valor sugerido, no
   confirmado contra un criterio de precisión real del ambiente).
3. **`FAIL`** — si se midió pero `error_abs_cm > tolerancia`.

## 5. `FAIL`/`ERROR` no siempre significan que la medición BLE/UWB falló

Un `FAIL` compara la distancia **medida** contra la distancia
**calculada** a partir de `posicion` en el TOML. Si `posicion` todavía es
un valor de ejemplo o un `TODO` (no la ubicación física real de los
nodos — ver [formato-ambiente-toml.md](formato-ambiente-toml.md)), el
reporte va a marcar `FAIL` aunque la medición UWB en sí haya sido
perfecta (muchas muestras `SUCCESS`, poca dispersión). Antes de
interpretar un `FAIL` como "el enlace UWB anda mal", revisar
`n_samples_success`/`n_samples_requested` de esa fila: si son iguales (o
casi), el problema más probable es que `posicion` no esté actualizado,
no la medición.

## 6. Formato Markdown

Mismo patrón que `validation/report.py` del repo hermano:

```markdown
# Reporte de medición de distancia UWB

> **Ambiente:** sala <id> · **Fecha:** <ISO 8601>

**<N> PASS · <N> FAIL · <N> ERROR** (total <N>)

| Par | Distancia calculada (m) | Distancia medida (m) | Error (cm) | Error (%) | Estado |
|---|---|---|---|---|---|
| <iniciador> → <respondedor> | ... | ... | ... | ... | PASS/FAIL/ERROR |

## Mediciones con error o fuera de tolerancia

- **<iniciador> → <respondedor>** (FAIL|ERROR): <n_success>/<n_requested> muestras SUCCESS [— <detalle>]
```

La sección **"Mediciones con error o fuera de tolerancia"** solo aparece
si hay al menos una fila que no sea `PASS` — con una campaña 100% exitosa
el Markdown termina en la tabla principal.
