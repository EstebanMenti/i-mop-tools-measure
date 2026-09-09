"""Medicion de la distancia real entre un iniciador y un respondedor, via
BLE + sesion FiRa.

Ver docs/protocolo-ble-qorvo.md secciones 3-4 para la secuencia exacta de
comandos, y docs/plan-implementacion.md Fase F3/F4 para el criterio de
diseno (incluida la decision de medir cada par en las dos direcciones).
"""

import logging
import statistics
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from imop_measure.config.models import Anchor
from imop_measure.core.client import DwmCliClient
from imop_measure.errors import MeasureError
from imop_measure.ranging.addressing import uwb_addr_to_int
from imop_measure.ranging.session import SessionParams, initiator_kwargs, responder_kwargs
from imop_measure.transport.ble_link import BleTransport

logger = logging.getLogger(__name__)

# Por BLE hace falta un periodo de silencio mayor al default de USB (0.3s):
# se midieron gaps de ~590ms incluso entre fragmentos de una respuesta sana
# (ver imop_measure.core.client.DwmCliClient, docs/protocolo-ble-qorvo.md).
_BLE_QUIET_PERIOD_S = 1.5

_DEFAULT_CONNECTION_TIMEOUT_S = 180.0
_DEFAULT_COMMAND_TIMEOUT_S = 5.0
_DEFAULT_QORVO_COMMAND_TIMEOUT_S = 10.0

# Mientras se juntan muestras solo se lee el enlace BLE del iniciador (ver
# `_collect_success_samples`); el del respondedor no recibe trafico propio
# y se desconecta solo tras ~7-8s de inactividad (ver transport/ble_link.py,
# confirmado contra hardware real 2026-09-08: UWB-Node-11 se desconecto a
# los ~15s de inactividad). Un STAT periodico, bien por debajo de ese
# umbral, mantiene el enlace vivo sin tocar la sesion RESPF en curso (STAT
# es una consulta de solo lectura, no reinicia ni reconfigura la app —
# a diferencia de INITF/RESPF, ver docs/protocolo-ble-qorvo.md seccion 3).
#
# [Verificado 2026-09-08 contra hardware real]: environments/sala_20.toml
# (3 anclas, 6 direcciones) corrio de punta a punta con este keepalive
# activo, 30/30 muestras SUCCESS en las 6 direcciones y cero errores de
# conexion BLE — antes del fix, 2/6 terminaban en error (0/30) con
# UWB-Node-11 como respondedor (ver reports/medicion-20-20260908-084928.md).
_RESPONDER_KEEPALIVE_INTERVAL_S = 5.0

# [Verificado 2026-09-09, hardware real] Un `transport.open()` que falla a
# medio camino (p. ej. la conexion se cae justo esperando la respuesta de
# `enable_stream()`) puede dejar un hilo/loop de asyncio de `BleTransport`
# corriendo para siempre sin nadie que lo cierre (`open()` no se limpia
# solo si una etapa intermedia falla) — un intento posterior de conectar al
# MISMO dispositivo puede entonces fallar con un error de WinRT no
# relacionado (`[WinError -2147023673] El usuario ha cancelado la
# operacion`), porque el stack BLE de Windows todavia ve una sesion GATT a
# medio cerrar hacia esa direccion. `open_initiator` ahora cierra siempre el
# transporte fallido antes de reintentar (nunca reusa uno a medio abrir) y
# reintenta con un backoff corto para darle tiempo al stack de asentarse.
_OPEN_INITIATOR_RETRY_ATTEMPTS = 2
_OPEN_INITIATOR_RETRY_BACKOFF_S = 3.0

_TransportFactory = Callable[[str], BleTransport]


@dataclass(frozen=True)
class MeasuredPair:
    """Resultado de medir la distancia real entre un iniciador y un respondedor.

    Cada nodo del ambiente mide contra todos los demas en ambos roles
    (ver `ranging/campaign.py`), asi que el mismo par fisico de nodos
    produce dos `MeasuredPair`, uno por direccion (`initiator`/`responder`
    intercambiados) — se mantienen separados a proposito, no promediados,
    para poder detectar asimetrias de hardware/protocolo entre nodos.

    `error` es `None` solo si se juntó al menos una muestra `SUCCESS`;
    cualquier otra falla (conexión, modo inesperado, timeout, cero
    muestras) queda descripta ahí en vez de propagarse como excepción —
    ver `run_pair`.
    """

    initiator: Anchor
    responder: Anchor
    distance_cm_samples: list[int]
    mean_cm: float | None
    std_cm: float | None
    n_success: int
    n_requested: int
    error: str | None


@dataclass
class InitiatorHandle:
    """Conexion de un nodo como iniciador, mantenida abierta a lo largo de
    varias mediciones consecutivas contra distintos respondedores (ver
    `open_initiator`/`run_directed_measurement`/`close_initiator` y
    `ranging/campaign.py`).

    Evita pagar el costo de conectar por BLE (~10s en la practica contra
    hardware real, con ~15-20 dispositivos BLE alrededor en el scan —
    medido 2026-09-08) en cada direccion medida: solo hace falta una vez
    por nodo que actua de iniciador, no una vez por par.
    """

    anchor: Anchor
    transport: BleTransport
    client: DwmCliClient


def open_initiator(
    initiator: Anchor,
    *,
    ble_timeouts: Mapping[str, float],
    _transport_factory: _TransportFactory | None = None,
) -> InitiatorHandle:
    """Conecta `initiator` y lo deja en modo `NONE`, listo para medir
    contra varios respondedores en secuencia sin reconectar (ver
    `run_directed_measurement`).

    Nunca deja un transporte a medio abrir: ante cualquier falla lo cierra
    antes de reintentar o propagar — apagando el modulo Qorvo primero
    (`_safe_power_off`) solo si `transport.open()` llego a tener exito (si
    la propia conexion fallo, no hay nada que apagar: forzar un apagado ahi
    dispararia una reconexion inmediata y sin backoff dentro de
    `_safe_power_off`, justo el apuro que puede volver a fallar contra un
    dispositivo que recien se desconecto). Reintenta hasta
    `_OPEN_INITIATOR_RETRY_ATTEMPTS` veces con un transporte nuevo en cada
    intento (ver esa constante) — una falla de conexion transitoria no debe
    descartar de entrada las direcciones de todo un nodo (ver
    `ranging/campaign.py`).

    Raises:
        MeasureError: si ningun intento logro conectar o confirmar modo
            `NONE`.
    """
    make_transport = _transport_factory or _default_transport_factory(ble_timeouts)
    command_timeout_s = ble_timeouts.get("qorvo_command_timeout", _DEFAULT_QORVO_COMMAND_TIMEOUT_S)

    last_error: MeasureError | None = None
    for attempt in range(1, _OPEN_INITIATOR_RETRY_ATTEMPTS + 1):
        transport = make_transport(initiator.mac)
        client = DwmCliClient(
            transport, command_timeout_s=command_timeout_s, quiet_period_s=_BLE_QUIET_PERIOD_S
        )
        try:
            transport.open()  # conecta + "qorvo on" + settle
        except MeasureError as exc:
            last_error = exc
            transport.close()
        else:
            try:
                client.ensure_mode_none()
                return InitiatorHandle(anchor=initiator, transport=transport, client=client)
            except MeasureError as exc:
                last_error = exc
                _safe_power_off(transport)
                transport.close()
        if attempt < _OPEN_INITIATOR_RETRY_ATTEMPTS:
            logger.warning(
                "%s: fallo al conectar como iniciador (intento %d/%d): %s",
                initiator.nombre,
                attempt,
                _OPEN_INITIATOR_RETRY_ATTEMPTS,
                last_error,
            )
            time.sleep(_OPEN_INITIATOR_RETRY_BACKOFF_S)
    assert last_error is not None  # el loop corrio al menos una vez
    raise last_error


def close_initiator(handle: InitiatorHandle) -> None:
    """Apaga y desconecta un iniciador abierto con `open_initiator`, una
    vez terminado de medir contra todos los respondedores de su grupo.

    Nunca lanza (mismo criterio que el resto de la limpieza en este
    modulo, ver `_safe_power_off`).
    """
    _safe_power_off(handle.transport)
    handle.transport.close()


def run_directed_measurement(
    *,
    initiator_handle: InitiatorHandle,
    responder: Anchor,
    session: SessionParams,
    n_samples: int,
    ble_timeouts: Mapping[str, float],
    _transport_factory: _TransportFactory | None = None,
) -> MeasuredPair:
    """Mide una direccion contra `responder`, reusando la conexion ya
    abierta de `initiator_handle` (ver `open_initiator`).

    Conecta y desconecta el respondedor igual que antes hacia `run_pair`
    (incluido el keepalive del respondedor durante el muestreo, ver
    `_collect_success_samples`); lo unico que cambia es que el iniciador
    ya esta conectado y no se cierra aca — lo cierra quien abrio el grupo
    (ver `close_initiator`).

    Nunca lanza: cualquier falla (conexión, modo inesperado, timeout, cero
    muestras SUCCESS) se refleja en `MeasuredPair.error`, para que una
    direccion fallida no aborte el resto de las mediciones del grupo (ver
    `ranging/campaign.py`) — incluida una falla transitoria del propio
    iniciador ya conectado, que se reintenta de forma transparente en el
    siguiente comando (ver transport/ble_link.py `_ensure_connected`).
    """
    initiator = initiator_handle.anchor
    client_init = initiator_handle.client

    make_transport = _transport_factory or _default_transport_factory(ble_timeouts)
    transport_resp = make_transport(responder.mac)
    command_timeout_s = ble_timeouts.get("qorvo_command_timeout", _DEFAULT_QORVO_COMMAND_TIMEOUT_S)
    client_resp = DwmCliClient(
        transport_resp, command_timeout_s=command_timeout_s, quiet_period_s=_BLE_QUIET_PERIOD_S
    )

    connected_resp = False
    successes: list[int] = []
    try:
        transport_resp.open()  # conecta + "qorvo on" + settle
        connected_resp = True

        client_resp.ensure_mode_none()
        # El iniciador ya esta en NONE por open_initiator() o por el
        # _stop_quietly() de la direccion anterior del grupo, pero se
        # reconfirma aca (barato, un STOP+STAT): si el STOP anterior fallo
        # en silencio, mejor detectarlo ahora que arrancar INITF a ciegas.
        client_init.ensure_mode_none()

        addr_init = uwb_addr_to_int(initiator.uwb_addr)
        addr_resp = uwb_addr_to_int(responder.uwb_addr)

        # El respondedor arranca primero para no perderse la primera
        # transmision del iniciador (ver docs/protocolo-ble-qorvo.md
        # seccion 3).
        client_resp.start_respf(**responder_kwargs(session, addr=addr_resp, paddr=addr_init))
        client_init.start_initf(**initiator_kwargs(session, addr=addr_init, paddr=addr_resp))

        successes = _collect_success_samples(
            client_init, session=session, n_samples=n_samples, keepalive_client=client_resp
        )

        # Tolerante a fallas (ver _stop_quietly): si el enlace del
        # respondedor ya se desconecto solo por inactividad y reconectar
        # para mandar STOP falla, no hay que invalidar muestras que ya se
        # juntaron del lado del iniciador.
        _stop_quietly(client_resp)
        _stop_quietly(client_init)

        error = None if successes else "sin mediciones SUCCESS recibidas"
        return _build_result(initiator, responder, successes, n_samples, error)
    except MeasureError as exc:
        logger.warning(
            "Fallo midiendo iniciador=%s respondedor=%s: %s",
            initiator.nombre,
            responder.nombre,
            exc,
        )
        return _build_result(initiator, responder, successes, n_samples, str(exc))
    finally:
        if connected_resp:
            _safe_power_off(transport_resp)
        transport_resp.close()


def run_pair(
    *,
    initiator: Anchor,
    responder: Anchor,
    session: SessionParams,
    n_samples: int,
    ble_timeouts: Mapping[str, float],
    _transport_factory: _TransportFactory | None = None,
) -> MeasuredPair:
    """Mide una sola direccion de punta a punta: conecta al iniciador,
    mide contra `responder`, y desconecta al iniciador.

    Envoltorio fino sobre `open_initiator` + `run_directed_measurement` +
    `close_initiator` para el caso de una unica direccion (usado por los
    tests y como bloque de construccion independiente); una campaña con
    varias direcciones por iniciador usa esas piezas directamente para no
    reconectarlo en cada una (ver `ranging/campaign.py`).

    Nunca lanza: cualquier falla (conexión, modo inesperado, timeout, cero
    muestras SUCCESS) se refleja en `MeasuredPair.error`, para que un par
    fallido no aborte una campaña de medición completa (ver
    `ranging/campaign.py`, Fase F4).
    """
    try:
        handle = open_initiator(
            initiator, ble_timeouts=ble_timeouts, _transport_factory=_transport_factory
        )
    except MeasureError as exc:
        logger.warning(
            "Fallo midiendo iniciador=%s respondedor=%s: %s",
            initiator.nombre,
            responder.nombre,
            exc,
        )
        return _build_result(initiator, responder, [], n_samples, str(exc))
    try:
        return run_directed_measurement(
            initiator_handle=handle,
            responder=responder,
            session=session,
            n_samples=n_samples,
            ble_timeouts=ble_timeouts,
            _transport_factory=_transport_factory,
        )
    finally:
        close_initiator(handle)


def _default_transport_factory(ble_timeouts: Mapping[str, float]) -> _TransportFactory:
    connect_timeout_s = ble_timeouts.get("connection_timeout", _DEFAULT_CONNECTION_TIMEOUT_S)
    write_timeout_s = ble_timeouts.get("command_timeout", _DEFAULT_COMMAND_TIMEOUT_S)

    def factory(address: str) -> BleTransport:
        return BleTransport(
            address, connect_timeout_s=connect_timeout_s, write_timeout_s=write_timeout_s
        )

    return factory


def _collect_success_samples(
    client: DwmCliClient,
    *,
    session: SessionParams,
    n_samples: int,
    keepalive_client: DwmCliClient | None = None,
    keepalive_interval_s: float = _RESPONDER_KEEPALIVE_INTERVAL_S,
) -> list[int]:
    """Lee notificaciones del iniciador hasta juntar `n_samples` muestras
    `SUCCESS` o agotar el tiempo estimado para esa cantidad de muestras.

    Mismo criterio de ventana que `dwm3001c_cli.calibration.sampler` (repo
    hermano): al menos 3 bloques de margen por muestra pedida.

    `keepalive_client`, si se pasa, recibe un `STAT` cada
    `keepalive_interval_s` mientras se espera (ver
    `_RESPONDER_KEEPALIVE_INTERVAL_S`) — pensado para el respondedor, cuyo
    enlace BLE si no queda sin trafico propio durante toda la espera.
    """
    limit_s = n_samples * session.block_ms * 3 / 1000
    deadline = time.monotonic() + limit_s
    successes: list[int] = []
    last_keepalive = time.monotonic()
    while len(successes) < n_samples:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        window_s = min(remaining, session.block_ms * 3 / 1000)
        for measurement in client.read_notifications(duration_s=window_s, max_count=1):
            if measurement.status == "SUCCESS" and measurement.distance_cm is not None:
                successes.append(measurement.distance_cm)
        if keepalive_client is not None:
            now = time.monotonic()
            if now - last_keepalive >= keepalive_interval_s:
                _keep_responder_alive(keepalive_client)
                last_keepalive = now
    return successes


def _keep_responder_alive(client: DwmCliClient) -> None:
    """Consulta `STAT` (solo lectura) para que el enlace BLE del respondedor
    no quede inactivo mientras dura el muestreo (ver
    `_RESPONDER_KEEPALIVE_INTERVAL_S`). Una falla aca no debe abortar la
    medicion en curso — se loguea y se sigue, igual que `_stop_quietly`.
    """
    try:
        client.stat()
    except Exception:
        # Exception generica a proposito: el keepalive es best-effort y una
        # falla inesperada (p. ej. un ValueError de parseo si la respuesta
        # del STAT se pierde entre el backlog de notificaciones del canal de
        # comandos) no debe abortar la medicion en curso.
        logger.debug(
            "%s: keepalive STAT fallo durante el muestreo (se ignora)", client.name, exc_info=True
        )


def _stop_quietly(client: DwmCliClient) -> None:
    """Manda `STOP` tolerando que el enlace BLE haya quedado inactivo y la
    reconexion para mandarlo falle (ver `run_pair`): a esta altura ya se
    juntaron (o no) las muestras, y una falla de limpieza no debe
    invalidarlas.
    """
    try:
        client.stop()
    except MeasureError:
        logger.warning(
            "%s: fallo al detener la app al final de la medicion (se ignora)",
            client.name,
            exc_info=True,
        )


def _build_result(
    initiator: Anchor,
    responder: Anchor,
    successes: list[int],
    n_samples: int,
    error: str | None,
) -> MeasuredPair:
    mean_cm = statistics.fmean(successes) if successes else None
    std_cm = statistics.pstdev(successes) if successes else None
    return MeasuredPair(
        initiator=initiator,
        responder=responder,
        distance_cm_samples=successes,
        mean_cm=mean_cm,
        std_cm=std_cm,
        n_success=len(successes),
        n_requested=n_samples,
        error=error,
    )


def _safe_power_off(transport: BleTransport) -> None:
    try:
        transport.power_off()
    except MeasureError:
        logger.warning("%s: fallo al apagar el modulo Qorvo", transport.name, exc_info=True)
