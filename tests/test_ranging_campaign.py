"""Tests de imop_measure.ranging.campaign.run_campaign.

La mayoria mockea `open_initiator`/`run_directed_measurement`/
`close_initiator` (ver ranging/pair_runner.py) para probar la logica de
orquestacion en si: que agrupe las direcciones por iniciador y reuse su
conexion (`open_initiator` una vez por nodo iniciador, no una vez por
direccion), que el loop no aborte si una direccion o un grupo entero
falla, y que `close_initiator` se llame siempre. Simular "varias
mediciones, una falla" no se puede ejercitar con hardware real de forma
determinista, por eso se mockea. La marcada `@pytest.mark.hardware` corre
run_campaign de punta a punta contra los nodos reales, como smoke test
end-to-end.
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from imop_measure.config.loader import load_ambiente
from imop_measure.config.models import Ambiente, Anchor
from imop_measure.errors import MeasureError
from imop_measure.ranging import campaign
from imop_measure.ranging.pair_runner import InitiatorHandle, MeasuredPair
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


def _fake_open_initiator(initiator: Anchor, **_kwargs: object) -> InitiatorHandle:
    return InitiatorHandle(anchor=initiator, transport=Mock(), client=Mock())


def _fake_measurement(
    *, initiator_handle: InitiatorHandle, responder: Anchor, **_kwargs: object
) -> MeasuredPair:
    return MeasuredPair(
        initiator=initiator_handle.anchor,
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

    with (
        patch(
            "imop_measure.ranging.campaign.open_initiator", side_effect=_fake_open_initiator
        ) as mock_open,
        patch(
            "imop_measure.ranging.campaign.run_directed_measurement",
            side_effect=_fake_measurement,
        ) as mock_measure,
        patch("imop_measure.ranging.campaign.close_initiator") as mock_close,
    ):
        results = campaign.run_campaign(_ambiente(anchors), session=SessionParams(), n_samples=1)

    assert len(results) == 6  # N*(N-1) con N=3: cada nodo iniciador contra los otros 2
    # Un solo open_initiator/close_initiator por nodo iniciador -- no uno
    # por direccion medida (ver run_campaign).
    assert mock_open.call_count == 3
    assert mock_close.call_count == 3
    assert mock_measure.call_count == 6
    assert all(r.error is None for r in results)
    # Cada nodo aparece como iniciador exactamente 2 veces (contra los otros 2).
    initiators = [r.initiator.key for r in results]
    assert sorted(initiators) == ["a", "a", "b", "b", "c", "c"]
    # Ninguna medicion tiene el mismo nodo como iniciador y respondedor.
    assert all(r.initiator.key != r.responder.key for r in results)


def test_run_campaign_reuses_initiator_across_its_group() -> None:
    """El iniciador se conecta una sola vez por nodo, no una vez por
    direccion: verifica que `open_initiator` reciba el mismo objeto
    `Anchor` en las N-1 llamadas a `run_directed_measurement` de su grupo.
    """
    anchors = [_anchor("a"), _anchor("b"), _anchor("c")]
    handles_used: list[InitiatorHandle] = []

    def capture_measurement(
        *, initiator_handle: InitiatorHandle, responder: Anchor, **_kwargs: object
    ) -> MeasuredPair:
        handles_used.append(initiator_handle)
        return _fake_measurement(initiator_handle=initiator_handle, responder=responder)

    with (
        patch("imop_measure.ranging.campaign.open_initiator", side_effect=_fake_open_initiator),
        patch(
            "imop_measure.ranging.campaign.run_directed_measurement",
            side_effect=capture_measurement,
        ),
        patch("imop_measure.ranging.campaign.close_initiator"),
    ):
        campaign.run_campaign(_ambiente(anchors), session=SessionParams(), n_samples=1)

    # Las primeras 2 mediciones (a->b, a->c) comparten el mismo handle; lo
    # mismo para las siguientes 2 (b->a, b->c) y las ultimas 2 (c->a, c->b).
    assert handles_used[0] is handles_used[1]
    assert handles_used[2] is handles_used[3]
    assert handles_used[4] is handles_used[5]
    assert handles_used[0] is not handles_used[2]


def test_run_campaign_open_initiator_failure_marks_whole_group_error() -> None:
    """Si `open_initiator` falla para un nodo, sus N-1 direcciones quedan
    en error sin tocar `run_directed_measurement` -- no tendria sentido
    reintentar por direccion si el iniciador no responde. El resto de los
    iniciadores no se ve afectado.
    """
    anchors = [_anchor("a"), _anchor("b"), _anchor("c")]

    def open_initiator_side_effect(initiator: Anchor, **_kwargs: object) -> InitiatorHandle:
        if initiator.key == "b":
            raise MeasureError("b: fallo de conexion simulado")
        return _fake_open_initiator(initiator)

    with (
        patch(
            "imop_measure.ranging.campaign.open_initiator",
            side_effect=open_initiator_side_effect,
        ),
        patch(
            "imop_measure.ranging.campaign.run_directed_measurement",
            side_effect=_fake_measurement,
        ) as mock_measure,
        patch("imop_measure.ranging.campaign.close_initiator") as mock_close,
    ):
        results = campaign.run_campaign(_ambiente(anchors), session=SessionParams(), n_samples=1)

    assert len(results) == 6
    b_results = [r for r in results if r.initiator.key == "b"]
    assert len(b_results) == 2
    assert all(r.error == "b: fallo de conexion simulado" for r in b_results)
    assert all(r.n_success == 0 for r in b_results)
    other_results = [r for r in results if r.initiator.key != "b"]
    assert all(r.error is None for r in other_results)
    # run_directed_measurement nunca se llamo para el grupo de "b" (2
    # direcciones menos que las 6 totales).
    assert mock_measure.call_count == 4
    # close_initiator no se llama para un grupo que nunca abrio su handle.
    assert mock_close.call_count == 2


def test_run_campaign_open_initiator_unexpected_exception_does_not_abort_campaign() -> None:
    """`open_initiator` puede fallar con algo que no sea `MeasureError` (un
    bug, no una falla de conexion esperable) -- tampoco debe abortar el
    resto de la campaña, mismo criterio que ya aplica al loop de
    mediciones (ver test_run_campaign_closes_initiator_even_if_a_measurement_raises).
    """
    anchors = [_anchor("a"), _anchor("b"), _anchor("c")]

    def open_initiator_side_effect(initiator: Anchor, **_kwargs: object) -> InitiatorHandle:
        if initiator.key == "b":
            raise RuntimeError("bug simulado, no MeasureError")
        return _fake_open_initiator(initiator)

    with (
        patch(
            "imop_measure.ranging.campaign.open_initiator",
            side_effect=open_initiator_side_effect,
        ),
        patch(
            "imop_measure.ranging.campaign.run_directed_measurement",
            side_effect=_fake_measurement,
        ),
        patch("imop_measure.ranging.campaign.close_initiator"),
    ):
        results = campaign.run_campaign(_ambiente(anchors), session=SessionParams(), n_samples=1)

    assert len(results) == 6
    b_results = [r for r in results if r.initiator.key == "b"]
    assert len(b_results) == 2
    assert all("bug simulado, no MeasureError" in (r.error or "") for r in b_results)
    other_results = [r for r in results if r.initiator.key != "b"]
    assert all(r.error is None for r in other_results)


def test_run_campaign_closes_initiator_even_if_a_measurement_raises() -> None:
    anchors = [_anchor("a"), _anchor("b"), _anchor("c")]
    call_count = 0

    def side_effect(
        *, initiator_handle: InitiatorHandle, responder: Anchor, **_kwargs: object
    ) -> MeasuredPair:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("fallo inesperado simulado")
        return _fake_measurement(initiator_handle=initiator_handle, responder=responder)

    with (
        patch("imop_measure.ranging.campaign.open_initiator", side_effect=_fake_open_initiator),
        patch("imop_measure.ranging.campaign.run_directed_measurement", side_effect=side_effect),
        patch("imop_measure.ranging.campaign.close_initiator") as mock_close,
    ):
        results = campaign.run_campaign(_ambiente(anchors), session=SessionParams(), n_samples=1)

    assert len(results) == 6
    errors = [r.error for r in results]
    assert errors.count(None) == 5
    assert "fallo inesperado simulado" in errors
    # El grupo del iniciador que fallo a mitad de camino igual se cierra.
    assert mock_close.call_count == 3


def test_run_campaign_calls_on_pair_done_callback() -> None:
    anchors = [_anchor("a"), _anchor("b")]
    seen: list[MeasuredPair] = []

    with (
        patch("imop_measure.ranging.campaign.open_initiator", side_effect=_fake_open_initiator),
        patch(
            "imop_measure.ranging.campaign.run_directed_measurement",
            side_effect=_fake_measurement,
        ),
        patch("imop_measure.ranging.campaign.close_initiator"),
    ):
        campaign.run_campaign(
            _ambiente(anchors), session=SessionParams(), n_samples=1, on_pair_done=seen.append
        )

    assert len(seen) == 2  # N*(N-1) con N=2: a->b y b->a
    assert seen[0].mean_cm == 100.0


@pytest.mark.hardware
def test_run_campaign_against_real_nodes() -> None:
    """Corre run_campaign de punta a punta contra environments/sala_20.toml.

    Con las anclas reales activas hoy mide todas las direcciones posibles
    (N*(N-1)) reusando la conexion de cada iniciador contra todos sus
    respondedores (ver run_campaign). Sirve para confirmar que la
    orquestacion en si no rompe nada al envolver llamadas reales a
    open_initiator/run_directed_measurement/close_initiator.
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
