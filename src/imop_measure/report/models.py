"""Modelo del resultado de una medicion, listo para reportar.

Ver docs/plan-implementacion.md Fase F5.
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

    `detalle` (agregado respecto al esquema original del plan) guarda el
    mensaje de `MeasuredPair.error` cuando `estado != "PASS"`, para que el
    reporte pueda mostrar por que fallo una medicion sin tener que
    recorrer los `MeasuredPair` originales por separado.
    """

    initiator: str
    responder: str
    distance_calc_m: float
    distance_measured_m: float | None
    error_abs_cm: float | None
    error_pct: float | None
    n_samples_success: int
    n_samples_requested: int
    estado: Estado
    detalle: str | None = None
