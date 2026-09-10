"""Tests de imop_measure.ranging.campaign.run_campaign.

Mockea `run_pair` (ver ranging/pair_runner.py) para probar la logica de
orquestacion en si: que se llame una vez por cada direccion (`N*(N-1)`,
sin reusar conexiones entre direcciones -- ver docstring de
`run_campaign` para por que se dejo de reusar la conexion del iniciador),
que el loop no aborte si una direccion falla con una excepcion inesperada,
y que el callback `on_pair_done` se invoque con cada resultado. Simular
"varias mediciones, una falla" no se puede ejercitar con hardware real de
forma deterministica, por eso se mockea. La marcada `@pytest.mark.hardware`
corre run_campaign de punta a punta contra los nodos reales, como smoke
test end-to-end.
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


def _fake_measurement(*, initiator: Anchor, responder: Anchor, **_kwargs: object) -> MeasuredPair:
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

    with patch(
        "imop_measure.ranging.campaign.run_pair", side_effect=_fake_measurement
    ) as mock_run_pair:
        results = campaign.run_campaign(_ambiente(anchors), session=SessionParams(), n_samples=1)

    assert len(results) == 6  # N*(N-1) con N=3: cada nodo iniciador contra los otros 2
    assert mock_run_pair.call_count == 6
    assert all(r.error is None for r in results)
    # Cada nodo aparece como iniciador exactamente 2 veces (contra los otros 2).
    initiators = [r.initiator.key for r in results]
    assert sorted(initiators) == ["a", "a", "b", "b", "c", "c"]
    # Ninguna medicion tiene el mismo nodo como iniciador y respondedor.
    assert all(r.initiator.key != r.responder.key for r in results)


def test_run_campaign_connects_fresh_for_every_direction() -> None:
    """A diferencia del diseño anterior (reusar la conexion del iniciador
    entre respondedores), cada direccion llama `run_pair` por separado --
    una conexion BLE completa nueva por direccion, no una por nodo
    iniciador. Ver docstring de `run_campaign` para el motivo (power_cycle
    sobre una conexion reusada no bastaba para evitar que el iniciador
    quedara "pegado" al primer respondedor).
    """
    anchors = [_anchor("a"), _anchor("b"), _anchor("c")]
    calls: list[tuple[str, str]] = []

    def capture(*, initiator: Anchor, responder: Anchor, **_kwargs: object) -> MeasuredPair:
        calls.append((initiator.key, responder.key))
        return _fake_measurement(initiator=initiator, responder=responder)

    with patch("imop_measure.ranging.campaign.run_pair", side_effect=capture):
        campaign.run_campaign(_ambiente(anchors), session=SessionParams(), n_samples=1)

    assert calls == [
        ("a", "b"),
        ("a", "c"),
        ("b", "a"),
        ("b", "c"),
        ("c", "a"),
        ("c", "b"),
    ]


def test_run_campaign_unexpected_exception_does_not_abort_campaign() -> None:
    """`run_pair` nunca deberia dejar escapar una excepcion (ver su propio
    docstring), pero si lo hiciera (un bug, no una falla de conexion
    esperable), no debe abortar el resto de la campaña.
    """
    anchors = [_anchor("a"), _anchor("b"), _anchor("c")]

    def side_effect(*, initiator: Anchor, responder: Anchor, **_kwargs: object) -> MeasuredPair:
        if initiator.key == "b":
            raise RuntimeError("bug simulado")
        return _fake_measurement(initiator=initiator, responder=responder)

    with patch("imop_measure.ranging.campaign.run_pair", side_effect=side_effect):
        results = campaign.run_campaign(_ambiente(anchors), session=SessionParams(), n_samples=1)

    assert len(results) == 6
    b_results = [r for r in results if r.initiator.key == "b"]
    assert len(b_results) == 2
    assert all("bug simulado" in (r.error or "") for r in b_results)
    assert all(r.n_success == 0 for r in b_results)
    other_results = [r for r in results if r.initiator.key != "b"]
    assert all(r.error is None for r in other_results)


def test_run_campaign_forwards_on_status_to_run_pair() -> None:
    anchors = [_anchor("a"), _anchor("b")]
    captured_callbacks: list[object] = []

    def capture(
        *, initiator: Anchor, responder: Anchor, on_status: object = None, **_kwargs: object
    ) -> MeasuredPair:
        captured_callbacks.append(on_status)
        return _fake_measurement(initiator=initiator, responder=responder)

    def my_on_status(_message: str) -> None:
        pass

    with patch("imop_measure.ranging.campaign.run_pair", side_effect=capture):
        campaign.run_campaign(
            _ambiente(anchors), session=SessionParams(), n_samples=1, on_status=my_on_status
        )

    assert captured_callbacks == [my_on_status, my_on_status]


def test_run_campaign_calls_on_pair_done_callback() -> None:
    anchors = [_anchor("a"), _anchor("b")]
    seen: list[MeasuredPair] = []

    with patch("imop_measure.ranging.campaign.run_pair", side_effect=_fake_measurement):
        campaign.run_campaign(
            _ambiente(anchors), session=SessionParams(), n_samples=1, on_pair_done=seen.append
        )

    assert len(seen) == 2  # N*(N-1) con N=2: a->b y b->a
    assert seen[0].mean_cm == 100.0


@pytest.mark.hardware
def test_run_campaign_against_real_nodes() -> None:
    """Corre run_campaign de punta a punta contra environments/sala_20.toml.

    Con las anclas reales activas hoy mide todas las direcciones posibles
    (N*(N-1)), conectando y desconectando el iniciador de punta a punta en
    cada una (ver run_campaign). Sirve para confirmar que la orquestacion
    en si no rompe nada al envolver llamadas reales a `run_pair`.
    """
    toml_path = Path(__file__).resolve().parent.parent / "environments" / "sala_20.toml"
    ambiente = load_ambiente(toml_path)
    seen: list[MeasuredPair] = []

    results = campaign.run_campaign(
        ambiente, session=SessionParams(), n_samples=10, on_pair_done=seen.append
    )

    n = len(ambiente.anchors)
    assert len(results) == n * (n - 1)
    assert results == seen  # el callback se llamo exactamente con esos resultados
    for result in results:
        assert result.error is None, result.error
        assert result.n_success >= result.n_requested / 2
        assert result.mean_cm is not None
        assert 0 < result.mean_cm < 5000
