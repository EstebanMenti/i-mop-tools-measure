"""Modelo del resultado de una medicion, listo para reportar.

Ver docs/plan-implementacion.md Fase F5 y docs/formato-reporte.md.
"""

from dataclasses import dataclass
from typing import Literal

Estado = Literal["PASS", "FAIL", "ERROR"]


@dataclass(frozen=True)
class PairResult:
    """Una fila del reporte: distancia calculada vs. medida en una direccion.

    Una fila por `MeasuredPair` de `ranging.campaign.run_campaign` — es
    decir, una fila por **direccion** medida, no por par fisico: el mismo
    par de nodos aparece dos veces (`A->B` y `B->A`), cada una con su
    propia `distance_measured_m` pero la misma `distance_calc_m` (la
    distancia geometrica no tiene direccion). Ver
    docs/arquitectura.md decision D6.

    `diff_m`/`diff_pct` llevan signo (`medida - calculada`): positivo si
    se midio mas lejos de lo calculado, negativo si mas cerca. `diff_pct`
    usa `distance_calc_m` como base, `None` si esa distancia es cero
    (evita division por cero).

    `detalle` (agregado respecto al esquema original del plan) guarda el
    mensaje de `MeasuredPair.error` cuando la medicion fallo del todo
    (`estado="ERROR"`), para que el reporte pueda mostrar por que sin
    tener que recorrer los `MeasuredPair` originales por separado.

    `std_measured_m`/`min_measured_m`/`max_measured_m`/`mode_measured_m`
    describen la dispersion de las muestras `distance_cm_samples` de esa
    direccion entre si (convertidas a metros, igual unidad que
    `distance_calc_m`/`distance_measured_m`/`diff_m` — para poder
    comparar todas las columnas de distancia de un vistazo, sin mezclar
    cm y m) — no confundir con `diff_m`/`diff_pct` (que comparan el
    *promedio* medido contra la distancia calculada). Dos direcciones
    pueden tener el mismo `diff_m` con dispersion muy distinta: una con
    todas las muestras muy juntas (confiable aunque este lejos de lo
    calculado) y otra con muestras muy dispersas (sospechosa aunque el
    promedio de casualidad caiga cerca). `mode_measured_m` es la moda
    (valor mas frecuente); ante empate, `statistics.mode` devuelve el
    primero encontrado en las muestras. Los cuatro son `None` si no se
    junto ninguna muestra (`estado="ERROR"`).
    """

    initiator: str
    responder: str
    distance_calc_m: float
    distance_measured_m: float | None
    diff_m: float | None
    diff_pct: float | None
    n_samples_success: int
    n_samples_requested: int
    estado: Estado
    detalle: str | None = None
    std_measured_m: float | None = None
    min_measured_m: float | None = None
    max_measured_m: float | None = None
    mode_measured_m: float | None = None
