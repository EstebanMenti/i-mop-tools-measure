"""Modelos de datos tipados del protocolo Qorvo.

Portado de `dwm3001c_cli.core.models` (repo hermano
`i-mop-qorvo-CLI-script`, commit ad7079aab0d32b603b4f83ce8be9ac5ce49bd0bd)
— ver docs/arquitectura.md decision D1. Dataclasses inmutables que
representan las respuestas parseadas del firmware CLI; todas conservan la
entrada cruda (`raw`) cuando aplica, para diagnostico.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceInfo:
    """Informacion reportada por `STAT`.

    `mode` se toma de la linea `MODE:` si el firmware la emite; si no
    (caso del firmware 1.1.0 real), se deriva del campo `Current App`.
    """

    mode: str
    device: str
    current_app: str
    version: str
    build: str
    apps: tuple[str, ...]
    driver: str
    uwb_stack: str
    raw: str


@dataclass(frozen=True)
class CalKey:
    """Una clave de calibracion, segun la salida de `CALKEY`/`LISTCAL`."""

    name: str
    value: int
    length_bytes: int
    raw: str


@dataclass(frozen=True)
class Measurement:
    """Una medicion de una notificacion `SESSION_INFO_NTF`.

    `distance_cm` y `rssi_dbm` pueden faltar: la distancia no se reporta
    si la ronda fallo, y el RSSI solo aparece con `DIAG 1` habilitado.
    """

    sequence_number: int
    block_index: int
    mac_address: str
    status: str
    distance_cm: int | None
    rssi_dbm: float | None
    raw: str


@dataclass(frozen=True)
class RangingStats:
    """Estadisticas de un lote de mediciones TWR."""

    n_requested: int
    n_received: int
    n_success: int
    mean_cm: float
    std_cm: float
    min_cm: int
    max_cm: int


@dataclass(frozen=True)
class ChipId:
    """Identificacion del chip UWB reportada por `DECAID`."""

    device_id: str
    lot_id: str
    part_id: str
    soc_id: str
