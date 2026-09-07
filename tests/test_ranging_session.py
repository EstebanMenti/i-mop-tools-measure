"""Tests de imop_measure.ranging.session — no requieren hardware."""

from imop_measure.ranging.session import SessionParams, initiator_kwargs, responder_kwargs


def test_initiator_kwargs_usa_direcciones_reales() -> None:
    params = SessionParams()

    kwargs = initiator_kwargs(params, addr=10, paddr=11)

    assert kwargs["addr"] == 10
    assert kwargs["paddr"] == 11
    assert kwargs["chan"] == params.chan
    assert kwargs["id"] == params.session_id


def test_responder_kwargs_usa_direcciones_reales() -> None:
    params = SessionParams()

    kwargs = responder_kwargs(params, addr=11, paddr=10)

    assert kwargs["addr"] == 11
    assert kwargs["paddr"] == 10
    assert kwargs["vupper"] == params.vupper


def test_initiator_y_responder_quedan_cruzados() -> None:
    params = SessionParams()

    init_kwargs = initiator_kwargs(params, addr=10, paddr=11)
    resp_kwargs = responder_kwargs(params, addr=11, paddr=10)

    assert init_kwargs["addr"] == resp_kwargs["paddr"]
    assert resp_kwargs["addr"] == init_kwargs["paddr"]
