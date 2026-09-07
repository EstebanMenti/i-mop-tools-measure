"""Tests de imop_measure.ranging.campaign.run_campaign — no requieren hardware."""

from unittest.mock import patch

from imop_measure.config.models import Ambiente, Anchor
from imop_measure.ranging import campaign
from imop_measure.ranging.pair_runner import MeasuredPair
from imop_measure.ranging.session import SessionParams


def _anchor(key: str) -> Anchor:
    return Anchor(
        key=key,
        nombre=key,
        mac="00:00:00:00:00:00",
        uwb_addr="00:00",
        posicion=(0.0, 0.0, 0.0),
        tiempo_prendido="60s",
    )


def _ambiente(anchors: list[Anchor]) -> Ambiente:
    return Ambiente(
        id="99", nombre=None, dimensiones=(1.0, 1.0, 1.0), anchors=anchors, ble_timeouts={}
    )


def _fake_result(anchor_a: Anchor, anchor_b: Anchor, **_kwargs: object) -> MeasuredPair:
    return MeasuredPair(
        anchor_a=anchor_a,
        anchor_b=anchor_b,
        distance_cm_samples=[100],
        mean_cm=100.0,
        std_cm=0.0,
        n_success=1,
        n_requested=1,
        error=None,
    )


def test_run_campaign_measures_all_pairs() -> None:
    anchors = [_anchor("a"), _anchor("b"), _anchor("c")]

    with patch("imop_measure.ranging.campaign.run_pair", side_effect=_fake_result) as mock_run_pair:
        results = campaign.run_campaign(_ambiente(anchors), session=SessionParams(), n_samples=1)

    assert len(results) == 3  # C(3,2)
    assert mock_run_pair.call_count == 3
    assert all(r.error is None for r in results)


def test_run_campaign_does_not_abort_on_unexpected_exception() -> None:
    anchors = [_anchor("a"), _anchor("b"), _anchor("c")]
    call_count = 0

    def side_effect(anchor_a: Anchor, anchor_b: Anchor, **_kwargs: object) -> MeasuredPair:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("fallo inesperado simulado")
        return _fake_result(anchor_a, anchor_b)

    with patch("imop_measure.ranging.campaign.run_pair", side_effect=side_effect):
        results = campaign.run_campaign(_ambiente(anchors), session=SessionParams(), n_samples=1)

    assert len(results) == 3
    errors = [r.error for r in results]
    assert errors.count(None) == 2
    assert "fallo inesperado simulado" in errors


def test_run_campaign_calls_on_pair_done_callback() -> None:
    anchors = [_anchor("a"), _anchor("b")]
    seen: list[MeasuredPair] = []

    with patch("imop_measure.ranging.campaign.run_pair", side_effect=_fake_result):
        campaign.run_campaign(
            _ambiente(anchors), session=SessionParams(), n_samples=1, on_pair_done=seen.append
        )

    assert len(seen) == 1
    assert seen[0].mean_cm == 100.0
