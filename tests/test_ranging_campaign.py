"""Tests de imop_measure.ranging.campaign.run_campaign.

La mayoria mockea `pair_runner.run_pair` para probar la logica de
orquestacion en si (el loop de pares direccionales, que no aborte si uno
falla) — eso requiere simular una medicion fallando mientras otras no,
algo que no se puede ejercitar con hardware real todavia:
`environments/sala_20.toml` solo tiene 2 anclas activas hoy, es decir
un unico par direccional por sentido (`N*(N-1)=2`), no alcanza para tener
"varias mediciones, una falla". La marcada `@pytest.mark.hardware` corre
run_campaign de punta a punta contra esas 2 mediciones reales (ambas
direcciones), como smoke test end-to-end.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from imop_measure.config.loader import load_ambiente
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


def _fake_result(*, initiator: Anchor, responder: Anchor, **_kwargs: object) -> MeasuredPair:
    return MeasuredPair(
        initiator=initiator,
        responder=responder,
        distance_cm_samples=[100],
        mean_cm=100.0,
        std_cm=0.0,
        n_success=1,
        n_requested=1,
        error=None,
    )


def test_run_campaign_measures_every_directed_pair() -> None:
    anchors = [_anchor("a"), _anchor("b"), _anchor("c")]

    with patch("imop_measure.ranging.campaign.run_pair", side_effect=_fake_result) as mock_run_pair:
        results = campaign.run_campaign(_ambiente(anchors), session=SessionParams(), n_samples=1)

    assert len(results) == 6  # N*(N-1) con N=3: cada nodo iniciador contra los otros 2
    assert mock_run_pair.call_count == 6
    assert all(r.error is None for r in results)
    # Cada nodo aparece como iniciador exactamente 2 veces (contra los otros 2).
    initiators = [r.initiator.key for r in results]
    assert sorted(initiators) == ["a", "a", "b", "b", "c", "c"]
    # Ninguna medicion tiene el mismo nodo como iniciador y respondedor.
    assert all(r.initiator.key != r.responder.key for r in results)


def test_run_campaign_does_not_abort_on_unexpected_exception() -> None:
    anchors = [_anchor("a"), _anchor("b"), _anchor("c")]
    call_count = 0

    def side_effect(*, initiator: Anchor, responder: Anchor, **_kwargs: object) -> MeasuredPair:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("fallo inesperado simulado")
        return _fake_result(initiator=initiator, responder=responder)

    with patch("imop_measure.ranging.campaign.run_pair", side_effect=side_effect):
        results = campaign.run_campaign(_ambiente(anchors), session=SessionParams(), n_samples=1)

    assert len(results) == 6
    errors = [r.error for r in results]
    assert errors.count(None) == 5
    assert "fallo inesperado simulado" in errors


def test_run_campaign_calls_on_pair_done_callback() -> None:
    anchors = [_anchor("a"), _anchor("b")]
    seen: list[MeasuredPair] = []

    with patch("imop_measure.ranging.campaign.run_pair", side_effect=_fake_result):
        campaign.run_campaign(
            _ambiente(anchors), session=SessionParams(), n_samples=1, on_pair_done=seen.append
        )

    assert len(seen) == 2  # N*(N-1) con N=2: a->b y b->a
    assert seen[0].mean_cm == 100.0


@pytest.mark.hardware
def test_run_campaign_against_real_nodes() -> None:
    """Corre run_campaign de punta a punta contra environments/sala_20.toml.

    Con 2 anclas activas hoy mide las 2 direcciones posibles
    (uwb_node_10->uwb_node_11 y uwb_node_11->uwb_node_10) — no ejercita
    "varias mediciones, una falla" (para eso hacen falta 3+ nodos). Sirve
    para confirmar que run_campaign en si (el loop de pares direccionales
    + on_pair_done) no rompe nada al envolver llamadas reales a run_pair.
    """
    toml_path = Path(__file__).resolve().parent.parent / "environments" / "sala_20.toml"
    ambiente = load_ambiente(toml_path)
    seen: list[MeasuredPair] = []

    results = campaign.run_campaign(
        ambiente, session=SessionParams(), n_samples=10, on_pair_done=seen.append
    )

    assert len(results) == 2  # N*(N-1) con las 2 anclas activas de hoy
    assert results == seen  # el callback se llamo exactamente con esos resultados
    for result in results:
        assert result.error is None, result.error
        assert result.n_success >= result.n_requested / 2
        assert result.mean_cm is not None
        assert 0 < result.mean_cm < 5000
