"""Parametros de sesion FiRa para una medicion de ranging entre un par de nodos.

Decision de diseno (docs/arquitectura.md D1): se reusa
``dwm3001c_cli.calibration.sampler.SessionParams`` (repo hermano
``i-mop-qorvo-CLI-script``) en vez de duplicar los defaults FiRa — ya esta
validado contra hardware real y evita reintroducir bugs ya resueltos ahi.
Ese modulo expone ``initiator_kwargs()``/``responder_kwargs()`` con
``ADDR``/``PADDR`` fijos en sus valores por defecto de rol (0/1); las
funciones de este modulo los sobreescriben con las direcciones UWB reales
de cada nodo del par (ver ranging/addressing.py).
"""

from dwm3001c_cli.calibration.sampler import SessionParams

__all__ = ["SessionParams", "initiator_kwargs", "responder_kwargs"]


def initiator_kwargs(params: SessionParams, *, addr: int, paddr: int) -> dict[str, object]:
    """Kwargs completos para ``INITF``, con las direcciones reales del par."""
    return {**params.initiator_kwargs(), "addr": addr, "paddr": paddr}


def responder_kwargs(params: SessionParams, *, addr: int, paddr: int) -> dict[str, object]:
    """Kwargs completos para ``RESPF``, con las direcciones reales del par."""
    return {**params.responder_kwargs(), "addr": addr, "paddr": paddr}
