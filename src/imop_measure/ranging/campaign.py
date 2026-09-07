"""Orquestacion de una campana de medicion completa sobre un ambiente.

Ver docs/plan-implementacion.md Fase F4.
"""

import logging
from collections.abc import Callable

from imop_measure.config.models import Ambiente
from imop_measure.geometry.pairs import all_pairs
from imop_measure.ranging.pair_runner import MeasuredPair, run_pair
from imop_measure.ranging.session import SessionParams

logger = logging.getLogger(__name__)


def run_campaign(
    ambiente: Ambiente,
    *,
    session: SessionParams,
    n_samples: int,
    on_pair_done: Callable[[MeasuredPair], None] | None = None,
) -> list[MeasuredPair]:
    """Mide la distancia real entre todos los pares de anclas del ambiente.

    Itera `geometry.pairs.all_pairs(ambiente.anchors)` y corre
    `ranging.pair_runner.run_pair` por cada par. Nunca aborta la campaña
    completa: `run_pair` ya devuelve el error en el propio `MeasuredPair`
    en vez de lanzar, pero por las dudas (un bug ahi, o una excepción de
    un tipo no contemplado) esta función también atrapa cualquier
    excepción inesperada por par y sigue con el resto — mismo criterio que
    `validation/runner.py` del repo hermano.

    `on_pair_done`, si se pasa, se invoca con cada `MeasuredPair` apenas
    está listo (pensado para mostrar progreso en vivo desde una futura
    GUI, Fase F7).
    """
    results: list[MeasuredPair] = []
    for anchor_a, anchor_b in all_pairs(ambiente.anchors):
        try:
            result = run_pair(
                anchor_a,
                anchor_b,
                session=session,
                n_samples=n_samples,
                ble_timeouts=ambiente.ble_timeouts,
            )
        except Exception as exc:
            logger.exception(
                "run_pair fallo de forma inesperada para %s <-> %s",
                anchor_a.nombre,
                anchor_b.nombre,
            )
            result = MeasuredPair(
                anchor_a=anchor_a,
                anchor_b=anchor_b,
                distance_cm_samples=[],
                mean_cm=None,
                std_cm=None,
                n_success=0,
                n_requested=n_samples,
                error=str(exc),
            )
        results.append(result)
        if on_pair_done is not None:
            on_pair_done(result)
    return results
