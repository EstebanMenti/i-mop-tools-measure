"""Conversion de direcciones UWB entre el formato del TOML y el protocolo Qorvo.

Ver docs/formato-ambiente-toml.md seccion 3.
"""

import re

from imop_measure.errors import ConfigError

_UWB_ADDR_RE = re.compile(r"^[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}$")


def uwb_addr_to_int(uwb_addr: str) -> int:
    """Convierte "XX:YY" (dos bytes hexadecimales) al entero decimal que
    esperan los parametros ``-ADDR=``/``-PADDR=`` de ``INITF``/``RESPF``.

    Raises:
        ConfigError: si uwb_addr no respeta el formato "XX:YY".
    """
    if not _UWB_ADDR_RE.match(uwb_addr):
        raise ConfigError(f"uwb_addr '{uwb_addr}' no respeta el formato XX:YY (dos bytes hex)")
    high, low = uwb_addr.split(":")
    return (int(high, 16) << 8) | int(low, 16)
