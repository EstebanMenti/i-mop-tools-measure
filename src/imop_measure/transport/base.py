"""Contrato de transporte de lineas y ensamblado de fragmentos en lineas.

Portado de `dwm3001c_cli.transport.serial_link` (repo hermano
`i-mop-qorvo-CLI-script`, commit ad7079aab0d32b603b4f83ce8be9ac5ce49bd0bd),
sin la parte especifica de puerto serie — este proyecto solo habla BLE con
los nodos (ver docs/arquitectura.md decision D1).
"""

from typing import Protocol


class Transport(Protocol):
    """Contrato minimo de un transporte de lineas hacia un nodo.

    Lo implementa `BleTransport` (hardware real) y los fakes de los tests
    (simulacion sin hardware).
    """

    def open(self) -> None: ...

    def close(self) -> None: ...

    def write_line(self, line: str) -> None: ...

    def read_line(self, timeout_s: float) -> str | None:
        """Devuelve la proxima linea recibida, o `None` si vencio el timeout."""
        ...

    @property
    def name(self) -> str:
        """Identificador del transporte, p. ej. `"BLE-FD7A9057CC9F"`."""
        ...


class LineAssembler:
    """Arma lineas completas a partir de fragmentos de bytes recibidos.

    El transporte entrega los datos en trozos arbitrarios; esta clase
    acumula los bytes parciales entre llamadas y devuelve solo lineas
    terminadas en `\\n` (descartando `\\r`). La decodificacion es ASCII con
    reemplazo, porque el firmware CLI emite texto plano.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[str]:
        """Ingresa un fragmento y devuelve las lineas completas disponibles."""
        self._buffer.extend(data)
        lines: list[str] = []
        while (newline_at := self._buffer.find(b"\n")) >= 0:
            raw = bytes(self._buffer[:newline_at])
            del self._buffer[: newline_at + 1]
            lines.append(raw.decode("ascii", errors="replace").rstrip("\r"))
        return lines
