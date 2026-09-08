"""Orquestacion de una campana de medicion completa sobre un ambiente.

Ver docs/plan-implementacion.md Fase F4.
"""

import logging
from collections.abc import Callable, Iterator
from itertools import groupby, permutations

from imop_measure.config.models import Ambiente, Anchor
from imop_measure.ranging.pair_runner import (
    MeasuredPair,
    close_initiator,
    open_initiator,
    run_directed_measurement,
)
from imop_measure.ranging.session import SessionParams

logger = logging.getLogger(__name__)


def run_campaign(
    ambiente: Ambiente,
    *,
    session: SessionParams,
    n_samples: int,
    on_pair_done: Callable[[MeasuredPair], None] | None = None,
) -> list[MeasuredPair]:
    """Mide la distancia real en ambas direcciones entre todos los nodos del ambiente.

    Cada nodo pasa por turno como iniciador contra todos los demas como
    respondedores (`N` anclas -> `N*(N-1)` mediciones direccionales,
    ver `_directed_pairs`) — a diferencia de la distancia geometrica
    (`geometry.pairs.all_pairs`, simetrica y sin dirección), la medicion
    real puede diferir segun quien inicia, asi que se mide y se reporta
    cada dirección por separado (ver `MeasuredPair`).

    Conecta el iniciador **una sola vez por grupo** (`open_initiator`) y
    lo reusa contra todos sus respondedores (`_grouped_by_initiator`,
    apoyado en que `_directed_pairs` ya los deja consecutivos) antes de
    desconectarlo (`close_initiator`) — conectar por BLE es el costo mas
    grande de una medicion (~10s contra hardware real, medido
    2026-09-08, ver docs/arquitectura.md decision D3): evita pagarlo una
    vez por direccion en vez de una vez por nodo. Si `open_initiator`
    falla, todo el grupo queda en error sin reintentar por direccion (no
    tendria sentido: el iniciador no responde); si una direccion puntual
    falla con el iniciador ya conectado, no aborta el resto del grupo — el
    enlace del iniciador se reconecta solo si hizo falta (ver
    transport/ble_link.py `_ensure_connected`).

    Nunca aborta la campaña completa: `run_directed_measurement` ya
    devuelve el error en el propio `MeasuredPair` en vez de lanzar, pero
    por las dudas (un bug ahi, o una excepción de un tipo no contemplado)
    esta función también atrapa cualquier excepción inesperada por
    medición y sigue con el resto — mismo criterio que
    `validation/runner.py` del repo hermano.

    `on_pair_done`, si se pasa, se invoca con cada `MeasuredPair` apenas
    está listo (pensado para mostrar progreso en vivo desde la GUI, Fase
    F7).
    """
    results: list[MeasuredPair] = []
    for initiator, responders in _grouped_by_initiator(ambiente.anchors):
        try:
            handle = open_initiator(initiator, ble_timeouts=ambiente.ble_timeouts)
        except Exception as exc:
            # Exception generica, no MeasureError: un bug aca (no solo una
            # falla de conexion esperable) tampoco debe abortar el resto de
            # la campaña — mismo criterio que el loop de mediciones de abajo.
            logger.exception(
                "No se pudo conectar %s como iniciador, se omiten sus %d direcciones",
                initiator.nombre,
                len(responders),
            )
            for responder in responders:
                result = MeasuredPair(
                    initiator=initiator,
                    responder=responder,
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
            continue

        try:
            for responder in responders:
                try:
                    result = run_directed_measurement(
                        initiator_handle=handle,
                        responder=responder,
                        session=session,
                        n_samples=n_samples,
                        ble_timeouts=ambiente.ble_timeouts,
                    )
                except Exception as exc:
                    logger.exception(
                        "run_directed_measurement fallo de forma inesperada, "
                        "iniciador=%s respondedor=%s",
                        initiator.nombre,
                        responder.nombre,
                    )
                    result = MeasuredPair(
                        initiator=initiator,
                        responder=responder,
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
        finally:
            close_initiator(handle)
    return results


def _directed_pairs(anchors: list[Anchor]) -> Iterator[tuple[Anchor, Anchor]]:
    """Todas las combinaciones ordenadas (iniciador, respondedor), `N*(N-1)` en total.

    A diferencia de `geometry.pairs.all_pairs` (combinaciones sin orden,
    para la distancia geométrica simétrica), acá el orden importa: cada
    nodo mide una vez como iniciador contra cada otro nodo como
    respondedor.
    """
    return permutations(anchors, 2)


def _grouped_by_initiator(anchors: list[Anchor]) -> Iterator[tuple[Anchor, list[Anchor]]]:
    """Direcciones a medir, agrupadas por iniciador (ver `run_campaign`).

    `permutations` ya genera los pares consecutivos por primer elemento
    (`A→B, A→C, ..., B→A, B→C, ...`), asi que `groupby` sin ordenar antes
    alcanza para agruparlos sin cambiar el orden de medicion existente.
    """
    for initiator, pairs in groupby(_directed_pairs(anchors), key=lambda pair: pair[0]):
        yield initiator, [responder for _, responder in pairs]
