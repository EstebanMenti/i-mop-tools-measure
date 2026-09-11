"""Tests de imop_measure.report.build — no requieren hardware."""

import pytest

from imop_measure.config.models import Anchor
from imop_measure.ranging.pair_runner import MeasuredPair
from imop_measure.report.build import build_results, summarize


def _anchor(key: str, posicion: tuple[float, float, float]) -> Anchor:
    return Anchor(
        key=key,
        nombre=key,
        mac="00:00:00:00:00:00",
        uwb_addr="00:00",
        posicion=posicion,
        tiempo_prendido="60s",
    )


NODE_A = _anchor("a", (0.0, 0.0, 0.0))
NODE_B = _anchor("b", (3.0, 4.0, 0.0))  # distancia geometrica: 5.0 m = 500 cm


def _measured(
    mean_cm: float | None,
    *,
    error: str | None = None,
    std_cm: float = 0.0,
    samples: list[int] | None = None,
) -> MeasuredPair:
    if samples is None:
        samples = [] if mean_cm is None else [round(mean_cm)]
    return MeasuredPair(
        initiator=NODE_A,
        responder=NODE_B,
        distance_cm_samples=samples,
        mean_cm=mean_cm,
        std_cm=std_cm if mean_cm is not None else None,
        n_success=len(samples),
        n_requested=1,
        error=error,
    )


def test_build_results_pass_within_tolerance() -> None:
    results = build_results([_measured(500.0, std_cm=2.1)], tolerance_cm=5.0)

    assert len(results) == 1
    result = results[0]
    assert result.estado == "PASS"
    assert result.initiator == "a"
    assert result.responder == "b"
    assert result.distance_calc_m == pytest.approx(5.0)
    assert result.distance_measured_m == pytest.approx(5.0)
    assert result.diff_m == pytest.approx(0.0)
    assert result.diff_pct == pytest.approx(0.0)
    assert result.detalle is None
    assert result.std_measured_m == pytest.approx(0.021)


def test_build_results_fail_outside_tolerance() -> None:
    results = build_results([_measured(520.0)], tolerance_cm=5.0)

    result = results[0]
    assert result.estado == "FAIL"
    assert result.diff_m == pytest.approx(0.20)  # medida (5.20m) - calculada (5.00m)
    assert result.diff_pct == pytest.approx(4.0)


def test_build_results_negative_diff_when_measured_is_shorter() -> None:
    results = build_results([_measured(480.0)], tolerance_cm=5.0)  # 20cm mas corto

    result = results[0]
    assert result.diff_m == pytest.approx(-0.20)
    assert result.diff_pct == pytest.approx(-4.0)


def test_build_results_std_measured_is_independent_of_diff() -> None:
    """`std_measured_m` refleja la dispersion entre muestras, no la
    diferencia contra lo calculado -- dos direcciones pueden compartir el
    mismo `diff_m` con una dispersion muy distinta (ver
    docs/formato-reporte.md seccion 7).
    """
    results = build_results(
        [
            _measured(520.0, std_cm=1.5),  # mismo diff_m (20cm)...
            _measured(520.0, std_cm=18.0),  # ...pero mucha mas dispersion
        ],
        tolerance_cm=5.0,
    )

    consistente, disperso = results
    assert consistente.diff_m == pytest.approx(disperso.diff_m)
    assert consistente.std_measured_m == pytest.approx(0.015)
    assert disperso.std_measured_m == pytest.approx(0.18)


def test_build_results_error_when_no_measurement() -> None:
    results = build_results([_measured(None, error="sin mediciones SUCCESS recibidas")])

    result = results[0]
    assert result.estado == "ERROR"
    assert result.distance_measured_m is None
    assert result.diff_m is None
    assert result.diff_pct is None
    assert result.n_samples_success == 0
    assert result.detalle == "sin mediciones SUCCESS recibidas"
    # La distancia calculada se informa igual, aunque la medicion haya fallado.
    assert result.distance_calc_m == pytest.approx(5.0)
    assert result.std_measured_m is None
    assert result.min_measured_m is None
    assert result.max_measured_m is None
    assert result.mode_measured_m is None


def test_build_results_zero_calculated_distance_has_no_diff_pct() -> None:
    same_spot = _anchor("c", (0.0, 0.0, 0.0))
    measured = MeasuredPair(
        initiator=NODE_A,
        responder=same_spot,
        distance_cm_samples=[10],
        mean_cm=10.0,
        std_cm=0.0,
        n_success=1,
        n_requested=1,
        error=None,
    )

    result = build_results([measured])[0]

    assert result.distance_calc_m == 0.0
    assert result.diff_pct is None  # evita division por cero
    assert result.diff_m == pytest.approx(0.10)  # diff_m si se calcula, solo el % se omite


def test_summarize_counts_by_estado() -> None:
    results = build_results(
        [
            _measured(500.0),  # PASS
            _measured(520.0),  # FAIL
            _measured(535.0),  # FAIL
            _measured(None, error="timeout"),  # ERROR
        ]
    )

    summary = summarize(results)

    assert summary == {"pass": 1, "fail": 2, "error": 1, "total": 4}


def test_build_results_computes_min_max_mode_from_samples() -> None:
    """`min_measured_m`/`max_measured_m`/`mode_measured_m` se calculan
    sobre las muestras individuales (`distance_cm_samples`, convertidas a
    metros), no sobre el promedio -- ver docs/formato-reporte.md seccion 4."""
    results = build_results(
        [_measured(mean_cm=502.0, samples=[498, 500, 500, 505, 507])], tolerance_cm=5.0
    )

    result = results[0]
    assert result.min_measured_m == pytest.approx(4.98)
    assert result.max_measured_m == pytest.approx(5.07)
    assert result.mode_measured_m == pytest.approx(5.00)  # se repite dos veces


def test_build_results_mode_of_single_sample_equals_that_sample() -> None:
    results = build_results([_measured(500.0, samples=[500])], tolerance_cm=5.0)

    result = results[0]
    assert result.min_measured_m == pytest.approx(5.00)
    assert result.max_measured_m == pytest.approx(5.00)
    assert result.mode_measured_m == pytest.approx(5.00)
