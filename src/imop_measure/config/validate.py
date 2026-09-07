"""Validaciones semanticas de un Ambiente ya parseado.

Ver docs/formato-ambiente-toml.md para las reglas completas.
"""

import re
from pathlib import Path

from imop_measure.config.models import Ambiente
from imop_measure.errors import ConfigError

_UWB_ADDR_RE = re.compile(r"^[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}$")


def validate_ambiente(ambiente: Ambiente, path: Path) -> None:
    """Valida un Ambiente ya parseado contra el esquema documentado.

    Args:
        ambiente: Ambiente ya construido por config.loader.load_ambiente.
        path: Path del archivo TOML de origen, para chequear que
            `[sala].id` coincide con el nombre de archivo `sala_<id>.toml`.

    Raises:
        ConfigError: si alguna de las reglas de
            docs/formato-ambiente-toml.md no se cumple.
    """
    expected_id = path.stem.removeprefix("sala_")
    if ambiente.id != expected_id:
        raise ConfigError(
            f"[sala].id ('{ambiente.id}') no coincide con el nombre de archivo "
            f"('{path.name}', se esperaba id='{expected_id}')"
        )

    if len(ambiente.anchors) < 2:
        raise ConfigError(
            f"El ambiente debe tener al menos 2 anclas activas, tiene {len(ambiente.anchors)}"
        )

    keys = [anchor.key for anchor in ambiente.anchors]
    duplicated = sorted({key for key in keys if keys.count(key) > 1})
    if duplicated:
        raise ConfigError(f"Claves de ancla duplicadas: {duplicated}")

    for anchor in ambiente.anchors:
        if not _UWB_ADDR_RE.match(anchor.uwb_addr):
            raise ConfigError(
                f"Ancla '{anchor.key}': uwb_addr '{anchor.uwb_addr}' "
                "no respeta el formato XX:YY (dos bytes hexadecimales)"
            )
