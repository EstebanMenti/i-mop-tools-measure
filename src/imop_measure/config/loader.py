"""Lectura de environments/sala_XX.toml.

Ver docs/formato-ambiente-toml.md para el esquema completo.
"""

import tomllib
from pathlib import Path
from typing import Any

from imop_measure.config.models import Ambiente, Anchor
from imop_measure.config.validate import validate_ambiente
from imop_measure.errors import ConfigError


def load_ambiente(path: Path) -> Ambiente:
    """Lee y valida un archivo de ambiente TOML.

    Las anclas comentadas (`#[[anchors]]`) no aparecen en el TOML parseado
    y por lo tanto quedan excluidas automaticamente — no requieren manejo
    especial.

    Raises:
        ConfigError: si el archivo no respeta el esquema documentado en
            docs/formato-ambiente-toml.md.
    """
    with path.open("rb") as toml_file:
        data = tomllib.load(toml_file)

    sala = data.get("sala", {})
    dimensions = data.get("dimensions", {})
    anchors = [_parse_anchor(raw) for raw in data.get("anchors", [])]
    ble_timeouts = {key: float(value) for key, value in data.get("ble_timeouts", {}).items()}

    ambiente = Ambiente(
        id=str(sala.get("id", "")),
        nombre=sala.get("nombre"),
        dimensiones=(
            float(dimensions.get("x", 0.0)),
            float(dimensions.get("y", 0.0)),
            float(dimensions.get("z", 0.0)),
        ),
        anchors=anchors,
        ble_timeouts=ble_timeouts,
    )
    validate_ambiente(ambiente, path)
    return ambiente


def _parse_anchor(raw: dict[str, Any]) -> Anchor:
    key = str(raw.get("key", ""))
    return Anchor(
        key=key,
        nombre=str(raw.get("nombre", "")),
        mac=str(raw.get("mac", "")),
        uwb_addr=str(raw.get("uwb_addr", "")),
        posicion=_parse_posicion(raw.get("posicion"), anchor_key=key),
        tiempo_prendido=str(raw.get("tiempo_prendido", "")),
    )


def _parse_posicion(raw: Any, *, anchor_key: str) -> tuple[float, float, float]:
    if not isinstance(raw, list) or len(raw) != 3:
        raise ConfigError(
            f"Ancla '{anchor_key}': 'posicion' debe tener exactamente 3 componentes [x, y, z]"
        )
    x, y, z = raw
    return (float(x), float(y), float(z))
