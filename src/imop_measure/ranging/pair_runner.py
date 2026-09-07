"""Medicion de la distancia real entre un par de nodos, via BLE + sesion FiRa.

Ver docs/protocolo-ble-qorvo.md secciones 3-4 para la secuencia exacta de
comandos, y docs/plan-implementacion.md Fase F3 para el criterio de diseno.
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

_TransportFactory = Callable[[str], BleTransport]


@dataclass(frozen=True)
class MeasuredPair:
    """Resultado de medir la distancia real entre dos nodos.

    `error` es `None` solo si se juntó al menos una muestra `SUCCESS`;
    cualquier otra falla (conexión, modo inesperado, timeout, cero
    muestras) queda descripta ahí en vez de propagarse como excepción —
    ver `run_pair`.
    """

    anchor_a: Anchor
    anchor_b: Anchor
    distance_cm_samples: list[int]
    mean_cm: float | None
    std_cm: float | None
    n_success: int
    n_requested: int
    error: str | None


def run_pair(
    anchor_a: Anchor,
    anchor_b: Anchor,
    *,
    session: SessionParams,
    n_samples: int,
    ble_timeouts: Mapping[str, float],
    _transport_factory: _TransportFactory | None = None,
) -> MeasuredPair:
    """Conecta a ambos nodos, configura `anchor_a`=RESPF/`anchor_b`=INITF,
    junta hasta `n_samples` muestras `SUCCESS` de `SESSION_INFO_NTF`, y
    detiene/apaga/desconecta ambos nodos siempre, incluso ante error.

    Nunca lanza: cualquier falla (conexión, modo inesperado, timeout, cero
    muestras SUCCESS) se refleja en `MeasuredPair.error`, para que un par
    fallido no aborte una campaña de medición completa (ver
    `ranging/campaign.py`, Fase F4).
    """
    make_transport = _transport_factory or _default_transport_factory(ble_timeouts)
    transport_a = make_transport(anchor_a.mac)
    transport_b = make_transport(anchor_b.mac)
    command_timeout_s = ble_timeouts.get("qorvo_command_timeout", _DEFAULT_QORVO_COMMAND_TIMEOUT_S)
    client_a = DwmCliClient(
        transport_a, command_timeout_s=command_timeout_s, quiet_period_s=_BLE_QUIET_PERIOD_S
    )
    client_b = DwmCliClient(
        transport_b, command_timeout_s=command_timeout_s, quiet_period_s=_BLE_QUIET_PERIOD_S
    )

    connected_a = connected_b = False
    try:
        transport_a.open()  # conecta + "qorvo on" + settle
        connected_a = True
        transport_b.open()
        connected_b = True

        client_a.ensure_mode_none()
        client_b.ensure_mode_none()

        addr_a = uwb_addr_to_int(anchor_a.uwb_addr)
        addr_b = uwb_addr_to_int(anchor_b.uwb_addr)

        # anchor_a = respondedor, anchor_b = iniciador; el respondedor
        # arranca primero para no perderse la primera transmision del
        # iniciador (ver docs/protocolo-ble-qorvo.md seccion 3).
        client_a.start_respf(**responder_kwargs(session, addr=addr_a, paddr=addr_b))
        client_b.start_initf(**initiator_kwargs(session, addr=addr_b, paddr=addr_a))

        successes = _collect_success_samples(client_b, session=session, n_samples=n_samples)

        client_a.stop()
        client_b.stop()

        error = None if successes else "sin mediciones SUCCESS recibidas"
        return _build_result(anchor_a, anchor_b, successes, n_samples, error)
    except MeasureError as exc:
        logger.warning("Fallo midiendo %s <-> %s: %s", anchor_a.nombre, anchor_b.nombre, exc)
        return _build_result(anchor_a, anchor_b, [], n_samples, str(exc))
    finally:
        if connected_a:
            _safe_power_off(transport_a)
        if connected_b:
            _safe_power_off(transport_b)
        transport_a.close()
        transport_b.close()


def _default_transport_factory(ble_timeouts: Mapping[str, float]) -> _TransportFactory:
    connect_timeout_s = ble_timeouts.get("connection_timeout", _DEFAULT_CONNECTION_TIMEOUT_S)
    write_timeout_s = ble_timeouts.get("command_timeout", _DEFAULT_COMMAND_TIMEOUT_S)

    def factory(address: str) -> BleTransport:
        return BleTransport(
            address, connect_timeout_s=connect_timeout_s, write_timeout_s=write_timeout_s
        )

    return factory


def _collect_success_samples(
    client: DwmCliClient, *, session: SessionParams, n_samples: int
) -> list[int]:
    """Lee notificaciones del iniciador hasta juntar `n_samples` muestras
    `SUCCESS` o agotar el tiempo estimado para esa cantidad de muestras.

    Mismo criterio de ventana que `dwm3001c_cli.calibration.sampler` (repo
    hermano): al menos 3 bloques de margen por muestra pedida.
    """
    limit_s = n_samples * session.block_ms * 3 / 1000
    deadline = time.monotonic() + limit_s
    successes: list[int] = []
    while len(successes) < n_samples:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        window_s = min(remaining, session.block_ms * 3 / 1000)
        for measurement in client.read_notifications(duration_s=window_s, max_count=1):
            if measurement.status == "SUCCESS" and measurement.distance_cm is not None:
                successes.append(measurement.distance_cm)
    return successes


def _build_result(
    anchor_a: Anchor,
    anchor_b: Anchor,
    successes: list[int],
    n_samples: int,
    error: str | None,
) -> MeasuredPair:
    mean_cm = statistics.fmean(successes) if successes else None
    std_cm = statistics.pstdev(successes) if successes else None
    return MeasuredPair(
        anchor_a=anchor_a,
        anchor_b=anchor_b,
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
