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

    `necesita_revision` es un umbral distinto e independiente de `estado`
    (que usa la tolerancia `--tolerance-cm`, mas estricta): marca
    diferencias groseras (default 30 cm) que probablemente sean un error
    de carga de datos (nodo equivocado, `posicion` mal tipeada) mas que
    ruido normal de multipath — ver docs/formato-reporte.md seccion 5.

    `detalle` (agregado respecto al esquema original del plan) guarda el
    mensaje de `MeasuredPair.error` cuando la medicion fallo del todo
    (`estado="ERROR"`), para que el reporte pueda mostrar por que sin
    tener que recorrer los `MeasuredPair` originales por separado.
    """

    initiator: str
    responder: str
    distance_calc_m: float
    distance_measured_m: float | None
    diff_m: float | None
    diff_pct: float | None
    necesita_revision: bool
    n_samples_success: int
    n_samples_requested: int
    estado: Estado
    detalle: str | None = None
