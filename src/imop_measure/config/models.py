"""Modelos de datos del ambiente (environments/sala_XX.toml).

Ver docs/formato-ambiente-toml.md para el esquema completo.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Anchor:
    """Un nodo UWB dentro de un ambiente.

    Attributes:
        key: Identificador unico del nodo dentro del archivo (ej. "uwb_node_2").
        nombre: Nombre legible (ej. "UWB-Node-2").
        mac: MAC BLE completa ("AA:BB:CC:DD:EE:FF"), usada para conectar/desconectar.
        uwb_addr: Direccion corta UWB ("XX:YY"), usada en la sesion de ranging.
        posicion: Posicion (x, y, z) en metros.
        tiempo_prendido: Tiempo sugerido de encendido (ej. "120s"), informativo.
    """

    key: str
    nombre: str
    mac: str
    uwb_addr: str
    posicion: tuple[float, float, float]
    tiempo_prendido: str


@dataclass(frozen=True)
class Ambiente:
    """Un ambiente completo: sala, dimensiones, anclas y timeouts BLE.

    Attributes:
        id: Identificador de sala, debe coincidir con el nombre del archivo.
        nombre: Nombre descriptivo, opcional.
        dimensiones: Dimensiones del espacio (x, y, z) en metros.
        anchors: Anclas activas (las comentadas en el TOML no aparecen aca).
        ble_timeouts: Timeouts BLE de la sala, ver docs/formato-ambiente-toml.md.
    """

    id: str
    nombre: str | None
    dimensiones: tuple[float, float, float]
    anchors: list[Anchor]
    ble_timeouts: dict[str, float]
