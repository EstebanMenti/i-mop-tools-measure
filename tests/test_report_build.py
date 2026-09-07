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


def _measured(mean_cm: float | None, *, error: str | None = None) -> MeasuredPair:
    samples = [] if mean_cm is None else [round(mean_cm)]
    return MeasuredPair(
        initiator=NODE_A,
        responder=NODE_B,
        distance_cm_samples=samples,
        mean_cm=mean_cm,
        std_cm=0.0 if mean_cm is not None else None,
        n_success=len(samples),
        n_requested=1,
        error=error,
    )


def test_build_results_pass_within_tolerance() -> None:
    results = build_results([_measured(500.0)], tolerance_cm=5.0)

    assert len(results) == 1
    result = results[0]
    assert result.estado == "PASS"
    assert result.initiator == "a"
    assert result.responder == "b"
    assert result.distance_calc_m == pytest.approx(5.0)
    assert result.distance_measured_m == pytest.approx(5.0)
    assert result.error_abs_cm == pytest.approx(0.0)
    assert result.error_pct == pytest.approx(0.0)
    assert result.detalle is None


def test_build_results_fail_outside_tolerance() -> None:
    results = build_results([_measured(520.0)], tolerance_cm=5.0)

    result = results[0]
    assert result.estado == "FAIL"
    assert result.error_abs_cm == pytest.approx(20.0)
    assert result.error_pct == pytest.approx(4.0)


def test_build_results_error_when_no_measurement() -> None:
    results = build_results([_measured(None, error="sin mediciones SUCCESS recibidas")])

    result = results[0]
    assert result.estado == "ERROR"
    assert result.distance_measured_m is None
    assert result.error_abs_cm is None
    assert result.error_pct is None
    assert result.n_samples_success == 0
    assert result.detalle == "sin mediciones SUCCESS recibidas"
    # La distancia calculada se informa igual, aunque la medicion haya fallado.
    assert result.distance_calc_m == pytest.approx(5.0)


def test_build_results_zero_calculated_distance_has_no_error_pct() -> None:
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
    assert result.error_pct is None  # evita division por cero


def test_summarize_counts_by_estado() -> None:
    results = build_results(
        [
            _measured(500.0),  # PASS
            _measured(520.0),  # FAIL
            _measured(None, error="timeout"),  # ERROR
        ]
    )

    summary = summarize(results)

    assert summary == {"pass": 1, "fail": 1, "error": 1, "total": 3}
