"""Tests de imop_measure.gui.worker.CampaignWorker — no requieren hardware.

`worker.run()` se llama directamente (no via QThread real): lo que importa
acá es la logica de `run()`, no el hilado en si (eso ya lo prueba, de forma
generica, el patron portado del repo hermano). Todo mockeado, sin BLE.
"""

from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from imop_measure.config.models import Ambiente, Anchor
from imop_measure.gui.worker import CampaignWorker
from imop_measure.ranging.pair_runner import MeasuredPair


def _anchor(key: str) -> Anchor:
    return Anchor(
        key=key,
        nombre=key,
        mac="00:00:00:00:00:00",
        uwb_addr="00:00",
        posicion=(0.0, 0.0, 0.0),
        tiempo_prendido="60s",
    )


def _ambiente() -> Ambiente:
    return Ambiente(
        id="99",
        nombre="Sala de prueba",
        dimensiones=(1.0, 1.0, 1.0),
        anchors=[_anchor("a"), _anchor("b")],
        ble_timeouts={},
    )


def _fake_measured(*, initiator: Anchor, responder: Anchor, **_kwargs: object) -> MeasuredPair:
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


def test_worker_emits_pair_measured_and_finished(qtbot: object, tmp_path: Path) -> None:
    ambiente = _ambiente()

    def fake_run_campaign(
        amb: Ambiente,
        *,
        session: object,
        n_samples: int,
        on_pair_done: Callable[[MeasuredPair], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> list[MeasuredPair]:
        if on_status is not None:
            on_status("Conectando a UWB-Node-A...")
        result = _fake_measured(initiator=amb.anchors[0], responder=amb.anchors[1])
        if on_pair_done is not None:
            on_pair_done(result)
        return [result]

    worker = CampaignWorker(
        environment_path=tmp_path / "sala_99.toml",
        samples=1,
        tolerance_cm=5.0,
        report_dir=tmp_path,
    )
    pairs_seen: list[object] = []
    finished_calls: list[tuple[object, object, object]] = []
    failed_messages: list[str] = []
    worker.pair_measured.connect(pairs_seen.append)
    worker.finished.connect(lambda *args: finished_calls.append(args))
    worker.failed.connect(failed_messages.append)

    with (
        patch("imop_measure.gui.worker.load_ambiente", return_value=ambiente),
        patch("imop_measure.gui.worker.run_campaign", side_effect=fake_run_campaign),
    ):
        worker.run()

    assert failed_messages == []
    assert len(pairs_seen) == 1
    assert len(finished_calls) == 1
    results, json_path, md_path = finished_calls[0]
    assert len(results) == 1
    assert Path(json_path).exists()  # type: ignore[arg-type]
    assert Path(md_path).exists()  # type: ignore[arg-type]


def test_worker_one_to_many_flag_uses_one_to_many_campaign(qtbot: object, tmp_path: Path) -> None:
    """`one_to_many=True` debe llamar `run_campaign_one_to_many`, no
    `run_campaign` -- puramente de enrutamiento, mismo criterio que
    `app/cli.py --one-to-many` (ver test_app_cli.py)."""
    ambiente = _ambiente()

    def fake_run_campaign_one_to_many(
        amb: Ambiente,
        *,
        session: object,
        n_samples: int,
        on_pair_done: Callable[[MeasuredPair], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> list[MeasuredPair]:
        result = _fake_measured(initiator=amb.anchors[0], responder=amb.anchors[1])
        if on_pair_done is not None:
            on_pair_done(result)
        return [result]

    worker = CampaignWorker(
        environment_path=tmp_path / "sala_99.toml",
        samples=1,
        tolerance_cm=5.0,
        report_dir=tmp_path,
        one_to_many=True,
    )
    finished_calls: list[object] = []
    worker.finished.connect(lambda *args: finished_calls.append(args))

    with (
        patch("imop_measure.gui.worker.load_ambiente", return_value=ambiente),
        patch(
            "imop_measure.gui.worker.run_campaign_one_to_many",
            side_effect=fake_run_campaign_one_to_many,
        ) as mock_one_to_many,
        patch("imop_measure.gui.worker.run_campaign") as mock_default,
    ):
        worker.run()

    assert len(finished_calls) == 1
    mock_one_to_many.assert_called_once()
    mock_default.assert_not_called()


def test_worker_emits_failed_on_missing_environment_file(qtbot: object, tmp_path: Path) -> None:
    # Sin mockear load_ambiente: un archivo inexistente levanta
    # FileNotFoundError (no ConfigError) — confirma que `except Exception`
    # (no solo MeasureError) atrapa cualquier falla, nunca la deja escapar.
    worker = CampaignWorker(
        environment_path=tmp_path / "no_existe.toml",
        samples=1,
        tolerance_cm=5.0,
        report_dir=tmp_path,
    )
    failed_messages: list[str] = []
    finished_calls: list[object] = []
    worker.failed.connect(failed_messages.append)
    worker.finished.connect(lambda *args: finished_calls.append(args))

    worker.run()

    assert len(failed_messages) == 1
    assert finished_calls == []


def test_worker_never_lets_unexpected_exception_escape(qtbot: object, tmp_path: Path) -> None:
    ambiente = _ambiente()
    worker = CampaignWorker(
        environment_path=tmp_path / "sala_99.toml",
        samples=1,
        tolerance_cm=5.0,
        report_dir=tmp_path,
    )
    failed_messages: list[str] = []
    worker.failed.connect(failed_messages.append)

    def raise_unexpected(*_args: object, **_kwargs: object) -> list[MeasuredPair]:
        raise RuntimeError("bug inesperado")

    with (
        patch("imop_measure.gui.worker.load_ambiente", return_value=ambiente),
        patch("imop_measure.gui.worker.run_campaign", side_effect=raise_unexpected),
    ):
        worker.run()  # no debe relanzar

    assert failed_messages == ["bug inesperado"]
