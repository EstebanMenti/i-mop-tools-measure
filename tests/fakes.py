"""Transportes simulados para tests sin hardware.

Portado de `i-mop-qorvo-CLI-script/tests/fakes.py` (commit
ad7079aab0d32b603b4f83ce8be9ac5ce49bd0bd) y adaptado a
`imop_measure.transport`/`imop_measure.core`.

`FakeTransport` implementa el protocolo `Transport` reproduciendo
respuestas del firmware a partir de un guion (comando -> lineas de
respuesta) y de una cola de notificaciones espontaneas (para simular
`SESSION_INFO_NTF` durante una sesion de ranging).

`FakeBleakClient` es el equivalente para `BleTransport`: implementa el
subconjunto de la API de `bleak.BleakClient` que usa `BleTransport`
(`_BleakClientLike`), sin depender de Bluetooth real ni de la libreria
`bleak`.
"""

from collections import deque
from collections.abc import Callable, Iterable


class FakeTransport:
    """Simulacion de un nodo detras de un transporte de lineas.

    Args:
        script: mapa de linea de comando exacta -> lineas de respuesta. Si
            el comando enviado no figura, se busca por su primera palabra
            (util para comandos con parametros variables). Sin
            coincidencia, no se encola respuesta (simula silencio ->
            timeout).
        notifications: lineas espontaneas que se entregan de a una cuando
            no hay respuestas pendientes (simula notificaciones de
            ranging).
    """

    def __init__(
        self,
        script: dict[str, list[str]] | None = None,
        notifications: Iterable[str] = (),
    ) -> None:
        self.script = dict(script or {})
        self.notifications: deque[str] = deque(notifications)
        self.sent: list[str] = []
        self.opened = False
        self._pending: deque[str] = deque()
        self._queued: dict[str, deque[list[str]]] = {}

    def queue_response(self, command: str, lines: list[str]) -> None:
        """Encola una respuesta de un solo uso para `command`.

        Las respuestas encoladas tienen prioridad sobre el guion estatico
        y se consumen en orden FIFO: permite simular comandos cuya
        respuesta cambia con el estado del nodo (p. ej. `STAT` antes y
        despues de `INITF`).
        """
        self._queued.setdefault(command, deque()).append(list(lines))

    @property
    def name(self) -> str:
        return "FAKE"

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def write_line(self, line: str) -> None:
        self.sent.append(line)
        queued = self._queued.get(line)
        if queued:
            self._pending.extend(queued.popleft())
            return
        response = self.script.get(line)
        if response is None:
            first_word = line.split(maxsplit=1)[0] if line.strip() else line
            response = self.script.get(first_word)
        if response is not None:
            self._pending.extend(response)

    def read_line(self, timeout_s: float) -> str | None:
        if self._pending:
            return self._pending.popleft()
        if self.notifications:
            return self.notifications.popleft()
        return None

    def read_notification_line(self, timeout_s: float) -> str | None:
        """Mismo canal que `read_line` (ver `Transport.read_notification_line`);
        despacha por `self` para que subclases que sobrescriben `read_line`
        queden cubiertas automaticamente."""
        return self.read_line(timeout_s)

    def push_lines(self, lines: Iterable[str]) -> None:
        """Encola lineas arbitrarias como si llegaran del nodo."""
        self._pending.extend(lines)


# Duplicado a proposito (no se importa imop_measure.transport.ble_link
# aca): ese modulo importa `bleak` a nivel de modulo, y fakes.py lo usan
# tambien tests que no necesitan el extra `bleak` instalado. Debe coincidir
# con ble_link.NUS_TX_CHAR_UUID / STREAM_DATA_CHAR_UUID.
_NUS_TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
_STREAM_DATA_CHAR_UUID = "36a9a2d9-a035-440f-8e59-ff0a72b2ba51"


class FakeBleakClient:
    """Doble de `bleak.BleakClient` para tests de `BleTransport` sin hardware.

    Args:
        address: direccion BLE (recibida igual que un `BleakClient` real).
        disconnected_callback: igual que en `BleakClient`.
        script: mapa de texto de comando **sin** el prefijo `"qorvo "` ni
            el `\\n` final -> lista de fragmentos `bytes` a entregar como
            notificaciones separadas (para simular la fragmentacion
            arbitraria real de las notificaciones BLE).
        mtu_size: valor fijo a reportar en `mtu_size`.
        fail_connect: si es `True`, `connect()` siempre lanza (simula una
            falla persistente, no transitoria).
        fail_connect_times: cuantas veces seguidas `connect()` falla antes
            de tener exito (simula la falla transitoria real de bleak/
            WinRT en Windows — ver docs/protocolo-ble-qorvo.md).
        fail_connect_exception: tipo de excepcion a lanzar mientras falla;
            default `BleakError`. Usar `OSError` para simular el caso real
            observado contra hardware (`OSError: [WinError -2147483629]
            Se cerro el objeto`, no una `BleakError`).
    """

    def __init__(
        self,
        address: str,
        disconnected_callback: Callable[["FakeBleakClient"], None] | None = None,
        services: Iterable[str] | None = None,
        *,
        winrt: dict[str, object] | None = None,
        script: dict[str, list[bytes]] | None = None,
        mtu_size: int = 247,
        fail_connect: bool = False,
        fail_connect_times: int = 0,
        fail_connect_exception: type[Exception] | None = None,
    ) -> None:
        self.address = address
        self._disconnected_callback = disconnected_callback
        self._connected = False
        self._notify_callbacks: dict[str, Callable[[object, bytearray], None]] = {}
        self.script = dict(script or {})
        self.mtu_size = mtu_size
        self.fail_connect = fail_connect
        self.fail_connect_times = fail_connect_times
        self.fail_connect_exception = fail_connect_exception
        self.connect_attempts = 0
        self.sent: list[bytes] = []
        # Para que los tests puedan verificar con que opciones se construyo
        # este cliente (p. ej. si BleTransport pidio el cache de servicios).
        self.requested_services = list(services) if services is not None else None
        self.winrt_args = dict(winrt or {})

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def _notify_callback(self) -> Callable[[object, bytearray], None] | None:
        """Compat: alias al callback de la caracteristica de comandos (NUS
        TX) — la mayoria de los tests existentes simula trafico en ese unico
        canal, de antes del canal de streaming dedicado. Para simular datos
        de ese canal nuevo, usar `simulate_stream_data`."""
        return self._notify_callbacks.get(_NUS_TX_CHAR_UUID)

    async def connect(self) -> None:
        from bleak.exc import BleakError

        self.connect_attempts += 1
        if self.fail_connect or self.connect_attempts <= self.fail_connect_times:
            exc_type = self.fail_connect_exception or BleakError
            raise exc_type(f"fake: fallo de conexion simulado (intento {self.connect_attempts})")
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def start_notify(
        self, char_specifier: str, callback: Callable[[object, bytearray], None]
    ) -> None:
        self._notify_callbacks[char_specifier] = callback

    async def stop_notify(self, char_specifier: str) -> None:
        self._notify_callbacks.pop(char_specifier, None)

    async def write_gatt_char(
        self, char_specifier: str, data: bytes, response: bool | None = None
    ) -> None:
        self.sent.append(bytes(data))
        text = bytes(data).decode("ascii").rstrip("\n")
        assert text.startswith("qorvo "), f"se esperaba el prefijo 'qorvo ': {text!r}"
        command = text[len("qorvo ") :]
        chunks = self.script.get(command)
        nus_callback = self._notify_callbacks.get(_NUS_TX_CHAR_UUID)
        stream_callback = self._notify_callbacks.get(_STREAM_DATA_CHAR_UUID)
        # Emula el firmware del puente >= 0.3.0 (I-mop-nrf52840-fw): las
        # respuestas de comandos viajan por NUS TX (canal de comandos) y las
        # notificaciones SESSION_INFO_NTF por la caracteristica dedicada de
        # streaming (ver `simulate_stream_data`). Dentro de la respuesta de
        # un comando, todo chunk desde el primero que contiene
        # "SESSION_INFO_NTF" (inclusive sus fragmentos de continuacion) se
        # considera dato de streaming.
        in_stream = False
        for chunk in chunks or []:
            if not in_stream and b"SESSION_INFO_NTF" in chunk:
                in_stream = True
            if in_stream:
                if stream_callback is not None:
                    stream_callback(None, bytearray(chunk))
            elif nus_callback is not None:
                nus_callback(None, bytearray(chunk))

    def simulate_stream_data(self, chunk: bytes) -> None:
        """Simula datos entrantes por la caracteristica dedicada de streaming
        (`STREAM_DATA_CHAR_UUID`), separada del canal de comandos."""
        callback = self._notify_callbacks.get(_STREAM_DATA_CHAR_UUID)
        assert callback is not None, "no suscripto a la caracteristica de streaming"
        callback(None, bytearray(chunk))

    def simulate_disconnect(self) -> None:
        """Simula un corte de conexion espontaneo (ej. el timeout de inactividad real)."""
        self._connected = False
        if self._disconnected_callback is not None:
            self._disconnected_callback(self)
