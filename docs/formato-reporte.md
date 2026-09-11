# Formato del reporte de medición

> **Propósito:** documentar exactamente qué genera `imop-measure run` al
> terminar una campaña: dónde queda el archivo, qué campos tiene el JSON,
> y cómo leer el reporte en Markdown (pensado para abrirse directamente y
> entenderse sin conocer el código).
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
emparejados por nombre. El `.md` está pensado para abrirlo directamente
(GitHub, un editor con vista previa, etc.) sin herramientas adicionales;
el `.json` es para procesamiento automático (otro script, integraciones
externas) — la GUI (`imop-measure-gui`) no lo relee: muestra los mismos
`PairResult` en vivo, en memoria, a medida que se miden.

## 2. Una fila por dirección, no por par

Por cada dos nodos del ambiente hay **dos filas** en el reporte: una con
cada nodo como iniciador (ver [arquitectura.md](arquitectura.md) decisión
D6). Con `N` anclas activas, el reporte tiene `N·(N-1)` filas. La
distancia *calculada* es la misma en las dos filas de un mismo par físico
(es geométrica, no tiene dirección); la distancia *medida* puede diferir
entre una dirección y la otra.

## 3. Ejemplo real (Markdown)

Captura real contra hardware, `environments/sala_20.toml`, 2026-09-07 —
incluye un `ERROR` real (fallo transitorio de conexión BLE, esperable en
BLE) y un `FAIL` (la diferencia supera la tolerancia, ver sección 5). Los
valores de `Mínimo`/`Máximo`/`Moda` son ilustrativos (esta captura es de
antes de agregar esas columnas, 2026-09-11) — el resto de la fila es la
medición real:

```markdown
# Reporte de Medición de Distancia UWB — Sala 20 - Configuración Real (ID 20)

**Fecha y hora de generación:** 07/09/2026 15:32:16 UTC-0300
**Ambiente:** Sala 20 - Configuración Real (ID 20)
**Muestras por dirección:** 15
**Criterios:** tolerancia ±5.0 cm para PASS/FAIL

---

## Resumen ejecutivo

| Total mediciones | ✅ PASS | ⚠️ FAIL | ❌ ERROR |
|---|---|---|---|
| 2 | 0 | 1 | 1 |

## Detalle de mediciones

| # | Dirección | Distancia calculada (m) | Distancia medida (m) | Mínimo (cm) | Máximo (cm) | Moda (cm) | Desviación (cm) | Diferencia (m) | Diferencia (%) | Estado |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | UWB-Node-10 → UWB-Node-11 | 0.592 | 3.465 | 342.0 | 351.0 | 345.0 | 2.1 | +2.873 | +485.7% | ⚠️ FAIL |
| 2 | UWB-Node-11 → UWB-Node-10 | 0.592 | — | — | — | — | — | — | — | ❌ ERROR |

## Mediciones que requieren revisión

- **UWB-Node-10 → UWB-Node-11** (⚠️ FAIL): 15/15 muestras SUCCESS
- **UWB-Node-11 → UWB-Node-10** (❌ ERROR): 0/15 muestras SUCCESS
```

La sección **"Mediciones que requieren revisión"** solo aparece si hay al
menos una fila con `estado != PASS` — con una campaña 100% exitosa el
Markdown termina en la tabla de detalle.

> El `FAIL` de este ejemplo es correcto y esperado, no un bug: `posicion`
> de estos dos nodos en `sala_20.toml` sigue siendo un valor `TODO`, no
> la ubicación física real — ver sección 6.

## 4. Formato JSON

```json
{
  "ambiente": "20",
  "ambiente_nombre": "Sala 20 - Configuración Real",
  "fecha": "2026-09-07T15:32:16.xxxxxx-03:00",
  "parametros": {
    "muestras_por_direccion": 15,
    "tolerancia_cm": 5.0
  },
  "resumen": { "pass": 0, "fail": 1, "error": 1, "total": 2 },
  "resultados": [
    {
      "initiator": "UWB-Node-10",
      "responder": "UWB-Node-11",
      "distance_calc_m": 0.5915234568468101,
      "distance_measured_m": 3.465,
      "diff_m": 2.8734765431531897,
      "diff_pct": 485.7,
      "n_samples_success": 15,
      "n_samples_requested": 15,
      "estado": "FAIL",
      "detalle": null,
      "std_measured_cm": 2.1,
      "min_measured_cm": 342.0,
      "max_measured_cm": 351.0,
      "mode_measured_cm": 345.0
    },
    {
      "initiator": "UWB-Node-11",
      "responder": "UWB-Node-10",
      "distance_calc_m": 0.5915234568468101,
      "distance_measured_m": null,
      "diff_m": null,
      "diff_pct": null,
      "n_samples_success": 0,
      "n_samples_requested": 15,
      "estado": "ERROR",
      "detalle": "",
      "std_measured_cm": null,
      "min_measured_cm": null,
      "max_measured_cm": null,
      "mode_measured_cm": null
    }
  ]
}
```

| Campo | Tipo | Descripción |
|---|---|---|
| `ambiente` | string | `[sala].id` del archivo de ambiente. |
| `ambiente_nombre` | string \| null | `[sala].nombre` del archivo de ambiente, si tiene uno declarado. |
| `fecha` | string, ISO 8601 con offset de zona horaria | Momento en que terminó la campaña. |
| `parametros.muestras_por_direccion` | int \| null | Valor de `--samples` usado. |
| `parametros.tolerancia_cm` | float | Valor de `--tolerance-cm` usado (umbral de `PASS`/`FAIL`). |
| `resumen.pass` / `.fail` / `.error` | int | Conteo de filas por `estado`. |
| `resumen.total` | int | Cantidad total de filas (`N·(N-1)`). |
| `resultados` | array | Una entrada por dirección medida (ver sección 2), con los campos de la tabla siguiente. |

Campos de cada entrada de `resultados` (`PairResult`, ver
`report/models.py`):

| Campo | Tipo | Descripción |
|---|---|---|
| `initiator` | string | Nombre (`Anchor.nombre`) del nodo que actuó como iniciador (`INITF`) en esta dirección. |
| `responder` | string | Nombre del nodo que actuó como respondedor (`RESPF`). |
| `distance_calc_m` | float | Distancia euclídea 3D calculada a partir de `posicion` en el TOML (metros). Simétrica: igual en ambas direcciones del mismo par. |
| `distance_measured_m` | float \| null | Promedio de las muestras `SUCCESS` de `SESSION_INFO_NTF` (metros). `null` si no se pudo medir (`estado="ERROR"`). |
| `diff_m` | float \| null | `distance_measured_m − distance_calc_m`, **con signo** (positivo = se midió más lejos de lo calculado). `null` si `distance_measured_m` es `null`. |
| `diff_pct` | float \| null | `diff_m` como porcentaje de `distance_calc_m`, con el mismo signo. `null` si `distance_measured_m` es `null` **o** si `distance_calc_m` es `0` (evita división por cero). |
| `n_samples_success` | int | Cuántas muestras `SUCCESS` se juntaron. |
| `n_samples_requested` | int | Cuántas se pidieron (`--samples`). |
| `estado` | `"PASS"` \| `"FAIL"` \| `"ERROR"` | Ver sección 5. |
| `detalle` | string \| null | Mensaje de error si hubo una falla real (conexión, timeout, excepción) — `null` si la única "falla" fue estar fuera de tolerancia. |
| `std_measured_cm` | float \| null | Desviación estándar (poblacional) de las muestras `SUCCESS` de esa dirección, en cm. Mide la dispersión **entre las propias muestras**, algo distinto de `diff_m`/`diff_pct` (que comparan el *promedio* contra lo calculado) — ver sección 6. `null` si `estado="ERROR"`. |
| `min_measured_cm` | float \| null | Valor mínimo entre las muestras `SUCCESS` de esa dirección, en cm. `null` si `estado="ERROR"`. |
| `max_measured_cm` | float \| null | Valor máximo entre las muestras `SUCCESS` de esa dirección, en cm. `null` si `estado="ERROR"`. |
| `mode_measured_cm` | float \| null | Valor más frecuente (moda) entre las muestras `SUCCESS` de esa dirección, en cm — ante empate, el primero encontrado (`statistics.mode`). `null` si `estado="ERROR"`. |

## 5. Cómo se calcula `estado`

En `report/build.py`, con `diff_cm = |diff_m| · 100`:

1. **`estado = "ERROR"`** — si `distance_measured_m` es `null` (no se
   juntó ninguna muestra `SUCCESS`: falla de conexión, timeout, excepción
   inesperada, etc.). `detalle` trae el motivo.
2. **`estado = "PASS"`** — si se midió y `diff_cm ≤ tolerancia` (
   `--tolerance-cm`, default `5.0` — ver `DEFAULT_TOLERANCE_CM` en
   `report/build.py`, marcado `TODO(confirmar-con-usuario)`: es un valor
   sugerido, no confirmado contra un criterio de precisión real del
   ambiente).
3. **`estado = "FAIL"`** — si se midió pero `diff_cm > tolerancia`.

## 6. `FAIL`/`ERROR` no siempre significan que la medición BLE/UWB falló

Un `FAIL` compara la distancia **medida** contra la distancia
**calculada** a partir de `posicion` en el TOML. Si `posicion` todavía es
un valor de ejemplo o un `TODO` (no la ubicación física real de los
nodos — ver [formato-ambiente-toml.md](formato-ambiente-toml.md)), el
reporte va a marcar `FAIL` aunque la medición UWB en sí haya sido
perfecta (muchas muestras `SUCCESS`, poca dispersión entre ellas). Antes
de interpretar un `FAIL` como "el enlace UWB anda mal", revisar
`n_samples_success`/`n_samples_requested` de esa fila: si son iguales (o
casi), el problema más probable es que `posicion` no esté actualizado,
no la medición.

## 7. `diff_m` vs. `std_measured_cm`: dos preguntas distintas

`diff_m`/`diff_pct` comparan el **promedio** de las muestras contra la
distancia calculada — responden "¿la posición declarada es correcta?".
`std_measured_cm` (columna "Desviación (cm)" en el Markdown) mide qué tan
dispersas están las muestras **entre sí** — responde "¿la medición en sí
es confiable, o el promedio salió de valores erráticos?". Son
independientes: dos direcciones pueden tener el mismo `diff_m` con
lecturas muy distintas de fondo:

- **`diff_m` grande, `std_measured_cm` chico (pocos cm):** las muestras
  son consistentes entre sí, solo que lejos de lo calculado — típicamente
  `posicion` desactualizada en el TOML (ver sección 6), no un problema de
  medición.
- **`diff_m` chico, `std_measured_cm` grande:** el promedio cayó cerca de
  lo calculado, pero de casualidad — las muestras individuales están muy
  dispersas (multipath severo, interferencia, nodo mal ubicado
  físicamente). Vale la pena desconfiar de esta fila aunque el `estado`
  diga `PASS`.
- **Ambos chicos:** el caso ideal — medición confiable y consistente con
  la posición declarada.

Como referencia, `docs/protocolo-ble-qorvo.md` documenta una desviación
típica de ~2 cm contra hardware real en condiciones normales; una
desviación de varios cm o más en una fila puntual es señal de revisarla,
aunque su `diff_m` esté dentro de tolerancia.

Las columnas "Mínimo (cm)"/"Máximo (cm)"/"Moda (cm)" complementan a
`std_measured_cm` con la misma pregunta ("¿qué tan confiable es la
medición en sí?"), en formato más directo de leer de un vistazo: el
rango `[Mínimo, Máximo]` muestra la dispersión real de las muestras
(no solo su desviación estándar), y la moda muestra el valor individual
más repetido — útil para distinguir una dispersión simétrica (ruido
normal de multipath) de una con valores atípicos puntuales que
distorsionan el promedio.
