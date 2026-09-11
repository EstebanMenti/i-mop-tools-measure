"""Parametros de sesion FiRa para una medicion de ranging entre un par de nodos.

`SessionParams` esta portada de
`dwm3001c_cli.calibration.sampler.SessionParams` (repo hermano
`i-mop-qorvo-CLI-script`, commit ad7079aab0d32b603b4f83ce8be9ac5ce49bd0bd)
— ver docs/arquitectura.md decision D1. Sus metodos originales
`initiator_kwargs()`/`responder_kwargs()` fijan `ADDR`/`PADDR` en los
defaults de rol (0/1); las funciones de este modulo los envuelven para
sobreescribirlos con las direcciones UWB reales de cada nodo del par (ver
ranging/addressing.py).
"""

from dataclasses import dataclass

__all__ = [
    "SessionParams",
    "initiator_kwargs",
    "initiator_kwargs_multi",
    "responder_kwargs",
    "responder_kwargs_multi",
]


@dataclass(frozen=True)
class SessionParams:
    """Parametros FiRa de la sesion TWR (defaults del firmware).

    Se envia **siempre el juego completo** de parametros en `INITF`/
    `RESPF`: cualquier parametro provisto resetea los demas a default
    (ver docs/protocolo-ble-qorvo.md seccion 3), asi que enviar todos
    evita estados a medias.
    """

    chan: int = 9
    prfset: str = "BPRF4"
    pcode: int = 10
    slot: int = 2400
    block_ms: int = 200
    round_slots: int = 25
    rru: str = "DSTWR"
    session_id: int = 42
    vupper: str = "01:02:03:04:05:06:07:08"

    def _common_kwargs(self) -> dict[str, object]:
        return {
            "chan": self.chan,
            "prfset": self.prfset,
            "pcode": self.pcode,
            "slot": self.slot,
            "block": self.block_ms,
            "round": self.round_slots,
            "rru": self.rru,
            "id": self.session_id,
            "vupper": self.vupper,
        }

    def initiator_kwargs(self) -> dict[str, object]:
        """Opciones completas para `INITF` (ADDR=0, PADDR=1 — defaults del rol)."""
        return {**self._common_kwargs(), "addr": 0, "paddr": 1}

    def responder_kwargs(self) -> dict[str, object]:
        """Opciones completas para `RESPF` (ADDR=1, PADDR=0 — defaults del rol)."""
        return {**self._common_kwargs(), "addr": 1, "paddr": 0}


def initiator_kwargs(params: SessionParams, *, addr: int, paddr: int) -> dict[str, object]:
    """Kwargs completos para `INITF`, con las direcciones reales del par."""
    return {**params.initiator_kwargs(), "addr": addr, "paddr": paddr}


def responder_kwargs(params: SessionParams, *, addr: int, paddr: int) -> dict[str, object]:
    """Kwargs completos para `RESPF`, con las direcciones reales del par."""
    return {**params.responder_kwargs(), "addr": addr, "paddr": paddr}


def initiator_kwargs_multi(
    params: SessionParams, *, addr: int, paddr: list[int]
) -> dict[str, object]:
    """Kwargs completos para `INITF` en modo uno-a-muchos (`-MULTI`), con la
    lista de direcciones de todos los respondedores de la ronda.

    [Verificado 2026-09-10 contra hardware real, Developer Manual
    QM33SDK-1.1.1 seccion 7 Listing 7.5]: `-PADDR=[1,2,.,.,n]` acepta N
    respondedores; probado con 2 (UWB-Node-6/UWB-Node-8), 152/152 muestras
    `SUCCESS`. No hay formula confirmada para el maximo de respondedores
    que entran en `round_slots` (el manual solo advierte que "ROUND tiene
    que ajustarse a la cantidad de controlees", sin dar la cuenta exacta)
    — `TODO(verificar-con-hardware)` para N mayor a 2.
    """
    if not paddr:
        raise ValueError("initiator_kwargs_multi: paddr no puede estar vacio")
    return {**params.initiator_kwargs(), "addr": addr, "paddr": paddr, "multi": True}


def responder_kwargs_multi(params: SessionParams, *, addr: int, paddr: int) -> dict[str, object]:
    """Kwargs completos para `RESPF` en modo uno-a-muchos (`-MULTI`).

    A diferencia del iniciador, el respondedor sigue usando un `-PADDR=`
    unico (la direccion del iniciador, no una lista) — el flag `-MULTI` es
    lo unico que cambia respecto a `responder_kwargs` (verificado contra
    hardware real 2026-09-10, Developer Manual QM33SDK-1.1.1 Listing 7.6:
    `RESPF -MULTI -PADDR=0 -ADDR=1`). Sin este flag en el respondedor, la
    ronda no arranca: las muestras dan `RX_TIMEOUT` al 100% (reproducido).
    """
    return {**params.responder_kwargs(), "addr": addr, "paddr": paddr, "multi": True}
