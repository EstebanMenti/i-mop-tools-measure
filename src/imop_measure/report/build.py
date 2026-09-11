"""Construye las filas y el resumen del reporte a partir de mediciones reales.

Ver docs/plan-implementacion.md Fase F5 y docs/formato-reporte.md.
"""

import statistics

from imop_measure.geometry.distance import euclidean_distance
from imop_measure.ranging.pair_runner import MeasuredPair
from imop_measure.report.models import Estado, PairResult

# TODO(confirmar-con-usuario): valor sugerido, no confirmado contra un
# criterio de precision real del ambiente (ver docs/plan-implementacion.md
# Fase F5). F6 lo expone como `--tolerance-cm` con este mismo default.
DEFAULT_TOLERANCE_CM = 5.0


def build_results(
    measured_pairs: list[MeasuredPair], *, tolerance_cm: float = DEFAULT_TOLERANCE_CM
) -> list[PairResult]:
    """Arma un `PairResult` por cada `MeasuredPair`, comparando la distancia
    medida contra la distancia geométrica calculada a partir de las
    posiciones declaradas en el ambiente."""
    return [_build_one(measured, tolerance_cm=tolerance_cm) for measured in measured_pairs]


def summarize(results: list[PairResult]) -> dict[str, int]:
    """Cuenta resultados por estado y el total."""
    counts = {"pass": 0, "fail": 0, "error": 0}
    for result in results:
        counts[result.estado.lower()] += 1
    counts["total"] = len(results)
    return counts


def _build_one(measured: MeasuredPair, *, tolerance_cm: float) -> PairResult:
    distance_calc_m = euclidean_distance(measured.initiator, measured.responder)

    if measured.mean_cm is None:
        return PairResult(
            initiator=measured.initiator.nombre,
            responder=measured.responder.nombre,
            distance_calc_m=distance_calc_m,
            distance_measured_m=None,
            diff_m=None,
            diff_pct=None,
            n_samples_success=measured.n_success,
            n_samples_requested=measured.n_requested,
            estado="ERROR",
            detalle=measured.error,
            std_measured_cm=None,
            min_measured_cm=None,
            max_measured_cm=None,
            mode_measured_cm=None,
        )

    distance_measured_m = measured.mean_cm / 100.0
    diff_m = distance_measured_m - distance_calc_m
    diff_cm = diff_m * 100.0
    diff_cm_abs = abs(diff_cm)
    diff_pct = (diff_cm / (distance_calc_m * 100.0) * 100.0) if distance_calc_m > 0 else None
    estado: Estado = "PASS" if diff_cm_abs <= tolerance_cm else "FAIL"
    samples = measured.distance_cm_samples

    return PairResult(
        initiator=measured.initiator.nombre,
        responder=measured.responder.nombre,
        distance_calc_m=distance_calc_m,
        distance_measured_m=distance_measured_m,
        diff_m=diff_m,
        diff_pct=diff_pct,
        n_samples_success=measured.n_success,
        n_samples_requested=measured.n_requested,
        estado=estado,
        # measured.error es None salvo que run_pair haya fallado, en cuyo
        # caso measured.mean_cm tambien seria None y ya habriamos vuelto
        # arriba — queda explicito por si ese invariante cambia.
        detalle=measured.error,
        std_measured_cm=measured.std_cm,
        min_measured_cm=float(min(samples)),
        max_measured_cm=float(max(samples)),
        mode_measured_cm=float(statistics.mode(samples)),
    )
