"""Orquestacion de una campana de medicion completa sobre un ambiente.

Ver docs/plan-implementacion.md Fase F4.
"""

import logging
from collections.abc import Callable, Iterator
from itertools import permutations

from imop_measure.config.models import Ambiente, Anchor
from imop_measure.ranging.pair_runner import MeasuredPair, run_one_to_many, run_pair
from imop_measure.ranging.session import SessionParams

logger = logging.getLogger(__name__)


def run_campaign(
    ambiente: Ambiente,
    *,
    session: SessionParams,
    n_samples: int,
    on_pair_done: Callable[[MeasuredPair], None] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> list[MeasuredPair]:
    """Mide la distancia real en ambas direcciones entre todos los nodos del ambiente.

    Cada nodo pasa por turno como iniciador contra todos los demas como
    respondedores (`N` anclas -> `N*(N-1)` mediciones direccionales,
    ver `_directed_pairs`) — a diferencia de la distancia geometrica
    (`geometry.pairs.all_pairs`, simetrica y sin dirección), la medicion
    real puede diferir segun quien inicia, asi que se mide y se reporta
    cada dirección por separado (ver `MeasuredPair`).

    [Verificado 2026-09-10 contra hardware real] Cada direccion abre y
    cierra su propia conexion BLE completa para el iniciador (via
    `run_pair`), en vez de reusarla entre los respondedores de un mismo
    nodo iniciador como se hacia antes. Se probo reusar la conexion y
    hacerle `power_cycle()` (apagar/prender el modulo Qorvo) entre
    direcciones, pero **no alcanza**: el iniciador seguia devolviendo
    `SESSION_INFO_NTF` del primer respondedor contra el que midio en esa
    conexion, confirmado con el `mac_address` crudo de cada muestra (ver
    docs/investigacion-desviaciones-uwb-2026-09-10.md). Solo una
    reconexion BLE completa (`run_pair` conecta y desconecta el iniciador
    de punta a punta) lo arregla de forma confiable. Esto suma el costo
    de conexion BLE del iniciador (~10-20s contra hardware real) en cada
    direccion en vez de una vez por nodo — deliberado: se prefiere una
    campaña mas lenta a mediciones silenciosamente contaminadas.

    Nunca aborta la campaña completa: `run_pair` ya devuelve el error en
    el propio `MeasuredPair` en vez de lanzar, pero por las dudas (un bug
    ahi, o una excepción de un tipo no contemplado) esta función también
    atrapa cualquier excepción inesperada por medición y sigue con el
    resto — mismo criterio que `validation/runner.py` del repo hermano.

    `on_pair_done`, si se pasa, se invoca con cada `MeasuredPair` apenas
    está listo (pensado para mostrar progreso en vivo desde la GUI, Fase
    F7). `on_status`, si se pasa, se invoca con mensajes legibles del paso
    en curso dentro de cada dirección (ver `pair_runner.run_pair`) —
    puramente informativo, no cambia el comportamiento de la medición.
    """
    results: list[MeasuredPair] = []
    for initiator, responder in _directed_pairs(ambiente.anchors):
        try:
            result = run_pair(
                initiator=initiator,
                responder=responder,
                session=session,
                n_samples=n_samples,
                ble_timeouts=ambiente.ble_timeouts,
                on_status=on_status,
            )
        except Exception as exc:
            # Exception generica, no MeasureError: un bug aca (no solo una
            # falla de conexion esperable) tampoco debe abortar el resto de
            # la campaña.
            logger.exception(
                "run_pair fallo de forma inesperada, iniciador=%s respondedor=%s",
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
    return results


def run_campaign_one_to_many(
    ambiente: Ambiente,
    *,
    session: SessionParams,
    n_samples: int,
    on_pair_done: Callable[[MeasuredPair], None] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> list[MeasuredPair]:
    """Igual cobertura que `run_campaign` (`N*(N-1)` direcciones: cada nodo
    mide contra todos los demas como iniciador), pero midiendo con
    `pair_runner.run_one_to_many` — una sesion FiRa uno-a-muchos (`-MULTI`)
    por nodo iniciador, contra todos los demas a la vez, en vez de una
    conexion BLE del iniciador por respondedor.

    [Modo experimental, agregado 2026-09-10 — ver
    docs/investigacion-desviaciones-uwb-2026-09-10.md]: valida factible
    contra hardware real (2 respondedores, 152/152 muestras SUCCESS), pero
    con muchas menos horas de prueba que `run_campaign` (el modo por
    defecto). No reemplaza a `run_campaign` — es una alternativa aparte,
    para no arriesgar el flujo ya validado.

    `N` sesiones en vez de `N*(N-1)` conexiones del iniciador — mucho menos
    tiempo de conexion BLE total, a costa de un modo sin la misma cantidad
    de horas de validacion.
    """
    results: list[MeasuredPair] = []
    for initiator, responders in _grouped_for_one_to_many(ambiente.anchors):
        try:
            group_results = run_one_to_many(
                initiator=initiator,
                responders=responders,
                session=session,
                n_samples=n_samples,
                ble_timeouts=ambiente.ble_timeouts,
                on_status=on_status,
            )
        except Exception as exc:
            # Exception generica, no MeasureError: un bug aca tampoco debe
            # abortar el resto de la campaña (mismo criterio que run_campaign).
            logger.exception(
                "run_one_to_many fallo de forma inesperada, iniciador=%s", initiator.nombre
            )
            group_results = [
                MeasuredPair(
                    initiator=initiator,
                    responder=responder,
                    distance_cm_samples=[],
                    mean_cm=None,
                    std_cm=None,
                    n_success=0,
                    n_requested=n_samples,
                    error=str(exc),
                )
                for responder in responders
            ]
        for result in group_results:
            results.append(result)
            if on_pair_done is not None:
                on_pair_done(result)
    return results


def _grouped_for_one_to_many(anchors: list[Anchor]) -> Iterator[tuple[Anchor, list[Anchor]]]:
    """Un grupo por nodo iniciador, con el resto de las anclas como
    respondedores (ver `run_campaign_one_to_many`)."""
    for initiator in anchors:
        responders = [a for a in anchors if a is not initiator]
        if responders:
            yield initiator, responders


def _directed_pairs(anchors: list[Anchor]) -> Iterator[tuple[Anchor, Anchor]]:
    """Todas las combinaciones ordenadas (iniciador, respondedor), `N*(N-1)` en total.

    A diferencia de `geometry.pairs.all_pairs` (combinaciones sin orden,
    para la distancia geométrica simétrica), acá el orden importa: cada
    nodo mide una vez como iniciador contra cada otro nodo como
    respondedor.
    """
    return permutations(anchors, 2)
