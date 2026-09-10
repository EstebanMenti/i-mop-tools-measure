"""Transporte Bluetooth Low Energy: `BleTransport` sobre el puente nRF52840.

Portado de `dwm3001c_cli.transport.ble_link` (repo hermano
`i-mop-qorvo-CLI-script`, commit ad7079aab0d32b603b4f83ce8be9ac5ce49bd0bd,
mas el canal de streaming dedicado de ese repo, commit
125568b4f3a420c3f053d4d78157b1dcc5810d5b — requerido por el firmware del
puente I-mop-nrf52840-fw >= 0.3.0, que agrego el servicio GATT "Qorvo
Stream"), donde esta validado contra hardware real — ver
docs/arquitectura.md decision D1. Cualquier bug de protocolo BLE que se
descubra en el futuro en ese repo hermano debe portarse tambien aca a
mano: este proyecto ya no depende de esa instalacion, es una copia
adaptada e independiente.

Implementa el contrato `Transport` (ver `transport/base.py`), asi que
`core/client.py` lo usa sin ningun cambio.

Protocolo (Nordic UART Service, firmware puente implementado en el repo
hermano `I-mop-nrf52840-fw`): cada linea de comando se envia como
`qorvo <linea>\\n` por la caracteristica RX; el puente reenvia el texto tal
cual por UART al Qorvo y retransmite su respuesta cruda por la
caracteristica TX — el formato de linea que ve `core/parsers.py` es el
mismo que por USB directo.

Hallazgos verificados contra hardware real (repo hermano, ver
`docs/protocolo-ble-qorvo.md` y
`../i-mop-qorvo-CLI-script/docs/rama-hardware-ble.md` para el detalle):

- MTU negociado 247 en Windows/WinRT; sin truncado en respuestas largas.
- Pairing Just Works sin dialogo de Windows.
- Las notificaciones BLE llegan fragmentadas en cualquier punto (no
  alineadas a lineas) — se reensamblan con `LineAssembler`.
- El shell de Zephyr intercala un prompt literal (`bt_nus:~$ `) al final de
  cada respuesta — se filtra antes de encolar lineas.
- La conexion BLE se cierra sola ~7-8 s despues de la ultima actividad —
  comportamiento normal del puente, no un fallo. Por eso `write_line`
  reconecta automaticamente si hace falta.
"""

import asyncio
import logging
import queue
import re
import threading
import time
from collections.abc import Callable, Coroutine
from concurrent.futures import TimeoutError as FutureTimeoutError
from types import TracebackType
from typing import Any, Protocol, Self, cast

from bleak import BleakClient
from bleak.exc import BleakError

from imop_measure.errors import TransportError
from imop_measure.transport.base import LineAssembler

logger = logging.getLogger(__name__)

NUS_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # PC -> nRF (write)
NUS_TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # nRF -> PC (notify)

# [Firmware del puente >= 0.3.0, I-mop-nrf52840-fw] Servicio "Qorvo Stream"
# (doc/00_BLE_Protocol_Specification.md §5.4/§7.7 del firmware): canal BLE
# dedicado, solo Notify, para streaming continuo de SESSION_INFO_NTF durante
# una sesion de ranging activa — reemplaza depender de NUS TX para esto.
# Motivo: el canal de comandos shell-NUS (`qorvo <cmd>`) es
# peticion/respuesta con una ventana acotada (silencio 400ms / timeout duro
# 8000ms) y, al vencer esa ventana, el puente suspendia el UART hacia el
# Qorvo incondicionalmente — con SESSION_INFO_NTF llegando cada ~200ms
# durante el ranging, el silencio nunca se cumplia, asi que la ventana corria
# siempre hasta los 8000ms y todo lo que el Qorvo transmitia despues se
# perdia hasta el proximo comando (confirmado contra hardware real en el
# repo hermano: rafagas de ~40 notificaciones y silencio total despues, sin
# ninguna desconexion BLE de por medio). Activado con `enable_stream()`
# (comando reservado `qorvo stream on`, igual mecanismo que `power_on()`).
STREAM_SERVICE_UUID = "019dad38-2b03-4df9-ac87-70ce530540fb"
STREAM_DATA_CHAR_UUID = "36a9a2d9-a035-440f-8e59-ff0a72b2ba51"  # nRF -> PC (notify)

# Prompt del shell de Zephyr tras cada respuesta (ej. "bt_nus:~$ "); no es
# contenido del Qorvo, hay que descartarlo antes de que lo vea DwmCliClient.
_PROMPT_RE = re.compile(r"^\S*:~\$\s*$")

# Texto real emitido por el puente cuando su limite duro de 8000 ms vence
# sin respuesta del Qorvo. Se compara por prefijo, no exacto, porque llega
# fragmentado en varias notificaciones y el firmware del puente podria
# variar ligeramente el resto del mensaje entre versiones.
_BRIDGE_TIMEOUT_MARKER = "Error: sin respuesta del modulo Qorvo"

# Tiempo de arranque del Qorvo tras "qorvo on" antes de que responda de
# forma confiable (verificado en el repo hermano).
_POWER_ON_SETTLE_S = 3.0

# Tiempo de espera entre "qorvo off" y "qorvo on" en power_cycle(), para
# asegurar que el modulo pierda de verdad su estado DS-TWR interno antes de
# volver a encenderlo (pedido explicito del usuario, ver docstring de
# power_cycle()).
_POWER_CYCLE_OFF_SETTLE_S = 2.0

# El backend WinRT de bleak (bluetooth en Windows) tiene fallas de conexion
# transitorias y conocidas, sin arreglo de fondo en bleak todavia (ver
# docs/protocolo-ble-qorvo.md, seccion "Fallas conocidas del backend BLE
# de Windows"): tanto BleakError como OSError nativos (ej. "[WinError
# -2147483629] Se cerro el objeto"), confirmado contra hardware real
# 2026-09-07. Reintentar la conexion (con un cliente nuevo cada vez, no el
# mismo objeto que ya fallo) resuelve la mayoria de los casos observados.
_CONNECT_RETRY_ATTEMPTS = 3
_CONNECT_RETRY_BACKOFF_S = 2.0


class _BleakClientLike(Protocol):
    """Subconjunto de la API de `BleakClient` que usa `BleTransport`.

    Permite inyectar un doble de prueba en los tests sin depender de
    `bleak` en los tests que no necesitan hardware ni el backend real.
    """

    @property
    def is_connected(self) -> bool: ...

    @property
    def mtu_size(self) -> int: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def start_notify(self, char_specifier: str, callback: object) -> None: ...

    async def stop_notify(self, char_specifier: str) -> None: ...

    async def write_gatt_char(
        self, char_specifier: str, data: bytes, response: bool | None = None
    ) -> None: ...


class BleTransport:
    """Transporte `Transport` sobre el puente Bluetooth nRF52840 (NUS).

    Uso tipico::

        with BleTransport("FD:7A:90:57:CC:9F") as link:
            link.write_line("STAT")
            line = link.read_line(timeout_s=10.0)

    Corre un hilo dedicado con su propio event loop de asyncio (requisito
    del backend WinRT de `bleak`: todas las llamadas de una misma conexion
    deben hacerse desde el mismo hilo); los metodos publicos son sincronos
    y despachan corutinas a ese hilo.

    Args:
        address: direccion BLE del nodo (campo `mac` del ambiente TOML).
        connect_timeout_s: tiempo maximo para conectar (incluye
            negociacion de MTU y pairing).
        write_timeout_s: tiempo maximo para que se complete una escritura
            GATT.
        power_on_settle_s: espera tras encender el modulo Qorvo en
            `open()`.
        connect_retry_attempts: intentos de `connect()` ante una falla
            transitoria conocida del backend BLE de Windows (ver arriba)
            antes de darse por vencido.
        connect_retry_backoff_s: espera entre intentos de conexion.
    """

    NUS_SERVICE_UUID = NUS_SERVICE_UUID
    NUS_RX_CHAR_UUID = NUS_RX_CHAR_UUID
    NUS_TX_CHAR_UUID = NUS_TX_CHAR_UUID
    STREAM_SERVICE_UUID = STREAM_SERVICE_UUID
    STREAM_DATA_CHAR_UUID = STREAM_DATA_CHAR_UUID

    def __init__(
        self,
        address: str,
        *,
        connect_timeout_s: float = 20.0,
        write_timeout_s: float = 5.0,
        power_on_settle_s: float = _POWER_ON_SETTLE_S,
        power_drain_s: float = 2.0,
        power_cycle_off_settle_s: float = _POWER_CYCLE_OFF_SETTLE_S,
        connect_retry_attempts: int = _CONNECT_RETRY_ATTEMPTS,
        connect_retry_backoff_s: float = _CONNECT_RETRY_BACKOFF_S,
        _client_factory: Callable[..., _BleakClientLike] | None = None,
    ) -> None:
        self._address = address
        # report/write.py arma nombres de archivo con Transport.name; una
        # direccion BLE trae ":" (MAC), invalido en nombres de archivo de
        # Windows — se lo reemplaza aca, no en cada consumidor.
        self._name = f"BLE-{address.replace(':', '')}"
        self._connect_timeout_s = connect_timeout_s
        self._write_timeout_s = write_timeout_s
        self._power_on_settle_s = power_on_settle_s
        self._power_drain_s = power_drain_s
        self._power_cycle_off_settle_s = power_cycle_off_settle_s
        self._connect_retry_attempts = connect_retry_attempts
        self._connect_retry_backoff_s = connect_retry_backoff_s
        self._client_factory: Callable[..., _BleakClientLike] = _client_factory or cast(
            "Callable[..., _BleakClientLike]", BleakClient
        )
        self._client: _BleakClientLike | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._assembler = LineAssembler()
        self._rx_queue: queue.Queue[str] = queue.Queue()
        # Canal separado para el streaming de ranging (caracteristica "Qorvo
        # Stream Data"): nunca comparte cola con las respuestas de comando
        # (_rx_queue), para que un STAT de keepalive no se coma (ni
        # contamine) notificaciones SESSION_INFO_NTF en curso, ni viceversa.
        self._stream_assembler = LineAssembler()
        self._stream_queue: queue.Queue[str] = queue.Queue()
        self._pending_error: str | None = None
        # Copias planas de estado, actualizadas solo desde el hilo dedicado
        # de bleak (self._thread) — nunca leer self._client.is_connected/
        # .mtu_size directamente desde otro hilo (p. ej. un hilo de GUI que
        # llame read_line()): es un objeto COM/WinRT con afinidad de hilo,
        # y tocarlo desde otro hilo crashea el proceso entero sin ninguna
        # traza de Python (bug real, confirmado contra hardware real en el
        # repo hermano).
        self._connected = False
        self._mtu_size: int | None = None

    @property
    def name(self) -> str:
        return self._name

    # ------------------------------------------------------------- ciclo de vida

    def open(self) -> None:
        """Conecta, habilita notificaciones, enciende el modulo Qorvo
        (`qorvo on`) y activa el streaming continuo de ranging
        (`qorvo stream on`, ver `enable_stream`)."""
        if self._thread is not None:
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name=f"ble-{self._address}", daemon=True
        )
        self._thread.start()
        self._run_coro(self._connect(), timeout_s=self._connect_timeout_s)
        self.power_on()
        time.sleep(self._power_on_settle_s)
        # El Qorvo debe estar encendido antes de aceptar el comando (misma
        # precondicion que cualquier otro `qorvo <cmd>`, ver power_on()).
        self.enable_stream()

    def close(self) -> None:
        if self._loop is None:
            return
        try:
            self._run_coro(self._disconnect(), timeout_s=5.0)
        except TransportError:
            logger.warning("%s: fallo al desconectar limpiamente", self.name, exc_info=True)
        finally:
            loop = self._loop
            loop.call_soon_threadsafe(loop.stop)
            if self._thread is not None:
                self._thread.join(timeout=5.0)
            self._loop = None
            self._thread = None
            self._client = None

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # --------------------------------------------------------------- Transport

    def write_line(self, line: str) -> None:
        self._ensure_connected()
        self._reset_pending()
        self._run_coro(self._send_raw(line), timeout_s=self._write_timeout_s)

    def _reset_pending(self) -> None:
        """Descarta cualquier fragmento/linea que haya quedado de la respuesta
        anterior antes de mandar un comando nuevo.

        Las notificaciones BLE (caracteristica NUS TX, modo "Notify") no
        tienen ACK ni retransmision a nivel GATT: una notificacion perdida
        es normal y posible. Cuando la linea que contenia el `\\n` de
        cierre es justo la que se pierde, el fragmento parcial queda
        indefinidamente en el buffer del `LineAssembler` (bug real,
        confirmado con hardware real en el repo hermano). No se puede
        recuperar el dato perdido, pero si se limpia el buffer antes de
        cada comando nuevo, lo peor que pasa es un timeout honesto en el
        comando que perdio su notificacion, en vez de corromper
        silenciosamente la respuesta de otro comando.
        """
        while True:
            try:
                self._rx_queue.get_nowait()
            except queue.Empty:
                break
        self._assembler = LineAssembler()
        self._pending_error = None

    def read_line(self, timeout_s: float) -> str | None:
        """Devuelve la proxima linea de respuesta de comando, o `None` si
        vencio `timeout_s`. Ver `_read_from_queue`."""
        return self._read_from_queue(self._rx_queue, timeout_s, what="respuesta")

    def read_notification_line(self, timeout_s: float) -> str | None:
        """Devuelve la proxima linea del canal de streaming BLE dedicado
        (caracteristica "Qorvo Stream Data", ver `STREAM_DATA_CHAR_UUID` y
        `enable_stream`), o `None` si vencio `timeout_s`. Ver
        `_read_from_queue`.
        """
        return self._read_from_queue(self._stream_queue, timeout_s, what="datos de streaming")

    def _read_from_queue(
        self, source: queue.Queue[str], timeout_s: float, *, what: str
    ) -> str | None:
        """Logica de lectura compartida por `read_line` y
        `read_notification_line`: cada una sobre su propia cola
        (`_rx_queue`/`_stream_queue` — nunca se mezclan, ver comentario en
        `__init__`).

        Sondea en pasos cortos (no un unico `queue.get` bloqueante) para
        poder detectar una desconexion o un timeout del puente mientras se
        espera, en vez de esperar el `timeout_s` completo a ciegas.
        """
        deadline = time.monotonic() + timeout_s
        poll_s = 0.05
        while True:
            if self._pending_error is not None:
                error = self._pending_error
                self._pending_error = None
                raise TransportError(f"{self.name}: {error}")
            remaining = deadline - time.monotonic()
            try:
                return source.get(timeout=min(poll_s, max(0.0, remaining)))
            except queue.Empty:
                pass
            if self._client is not None and not self._connected:
                raise TransportError(f"{self.name}: conexion BLE perdida esperando {what}")
            if time.monotonic() >= deadline:
                return None

    # --------------------------------------------------- extensiones propias BLE

    def power_on(self, hold_s: float | None = None) -> None:
        """`qorvo on`: enciende el modulo Qorvo (fuera del contrato `Transport`).

        No es un comando de la CLI del Qorvo, es una palabra reservada del
        firmware puente que controla el GPIO de alimentacion del modulo —
        por eso no pasa por `write_line` (que seria indistinguible de un
        comando real reenviado al Qorvo).
        """
        text = "on" if hold_s is None else f"on -t {hold_s:g}s"
        self._ensure_connected()
        self._run_coro(self._send_raw(text), timeout_s=self._write_timeout_s)
        self._drain_response()

    def power_off(self, hold_s: float | None = None) -> None:
        """`qorvo off`: apaga el modulo Qorvo (ver `power_on`)."""
        text = "off" if hold_s is None else f"off -t {hold_s:g}s"
        self._ensure_connected()
        self._run_coro(self._send_raw(text), timeout_s=self._write_timeout_s)
        self._drain_response()

    def power_cycle(self) -> None:
        """Apaga y vuelve a prender el modulo Qorvo (`qorvo off` + espera +
        `qorvo on`), para garantizar un estado DS-TWR interno limpio antes
        de arrancar una sesion nueva.

        [Verificado 2026-09-10 contra hardware real]: reenviar `INITF` con
        un `-PADDR=` distinto sobre un modulo que ya venia corriendo una
        sesion anterior (solo `STOP` + `INITF` nuevo, sin apagarlo) **no
        actualiza el peer** — el modulo sigue devolviendo `SESSION_INFO_NTF`
        con el `mac_address`/distancia del primer respondedor contra el que
        midio, para todos los destinos siguientes (reproducido de forma
        consistente con UWB-Node-11 contra 3 respondedores distintos en la
        misma conexion). Un power-cycle completo antes de cada direccion
        nueva lo arregla (confirmado: los 3 destinos dieron el
        `mac_address` correcto tras agregar este power-cycle). Ver
        `ranging.pair_runner.run_directed_measurement`, que lo llama antes
        de cada direccion tanto para el iniciador reusado como para el
        respondedor recien conectado.

        El streaming (`enable_stream`) no necesita reactivarse despues: es
        estado de la sesion GATT (se apaga solo al caerse la conexion BLE),
        no del encendido fisico del Qorvo — ver comentario junto a
        `STREAM_SERVICE_UUID`.
        """
        self.power_off()
        time.sleep(self._power_cycle_off_settle_s)
        self.power_on()
        time.sleep(self._power_on_settle_s)

    def enable_stream(self) -> None:
        """`qorvo stream on`: activa el streaming continuo de ranging por la
        caracteristica dedicada (`STREAM_DATA_CHAR_UUID`, ver comentario
        junto a esa constante).

        Palabra reservada del firmware puente, igual mecanismo que
        `power_on` (no pasa por `write_line`): la confirmacion
        ("Qorvo streaming: ON") llega por el canal de comandos normal
        (NUS TX), sin marcador `ok` — se drena igual que la de `power_on`.
        """
        self._ensure_connected()
        self._run_coro(self._send_raw("stream on"), timeout_s=self._write_timeout_s)
        self._drain_response()

    def disable_stream(self) -> None:
        """`qorvo stream off` (ver `enable_stream`).

        No es obligatorio llamarlo antes de desconectar — el streaming se
        apaga solo con la conexion BLE (ver doc del firmware puente) — pero
        es buena practica hacerlo si se lo va a reactivar mas adelante sobre
        la misma conexion.
        """
        self._ensure_connected()
        self._run_coro(self._send_raw("stream off"), timeout_s=self._write_timeout_s)
        self._drain_response()

    def _drain_response(self, quiet_s: float | None = None) -> None:
        """Lee y descarta hasta que no llegue nada nuevo por `quiet_s`.

        `qorvo on`/`qorvo off` no tienen un marcador de fin de respuesta
        tipo `ok` (el firmware puente solo manda
        `"Qorvo status changed to: ..."` y el prompt del shell, que ya se
        filtra en `_on_notify`). Sin drenar aca, esa linea queda en la cola
        y el siguiente comando real (p. ej. `STOP`) la toma como si fuera
        su propia respuesta (bug real, confirmado con hardware real en el
        repo hermano).
        """
        effective_quiet_s = quiet_s if quiet_s is not None else self._power_drain_s
        while True:
            line = self.read_line(effective_quiet_s)
            if line is None:
                return
            logger.debug("%s: descartada tras encender/apagar: %r", self.name, line)

    @property
    def mtu_size(self) -> int | None:
        return self._mtu_size

    # ---------------------------------------------------------------- internos

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_coro(self, coro: Coroutine[Any, Any, None], *, timeout_s: float) -> None:
        if self._loop is None:
            raise TransportError(f"{self.name}: transporte no abierto (llamar open() primero)")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            future.result(timeout_s)
        except FutureTimeoutError as exc:
            raise TransportError(f"{self.name}: timeout esperando una operacion BLE") from exc
        except (BleakError, OSError) as exc:
            # El backend WinRT de bleak en Windows a veces filtra errores
            # nativos como OSError crudo en vez de BleakError (ej.
            # "[WinError -2147483629] Se cerro el objeto", confirmado
            # contra hardware real) — se envuelven igual para que nada
            # aguas arriba (core.client.DwmCliClient, ranging.pair_runner)
            # tenga que distinguir el tipo de excepcion nativa.
            raise TransportError(f"{self.name}: error BLE: {exc}") from exc

    def _ensure_connected(self) -> None:
        if self._loop is None:
            raise TransportError(f"{self.name}: transporte no abierto (llamar open() primero)")
        if self._client is not None and self._connected:
            return
        # La conexion se cierra sola ~7-8s despues de la ultima actividad;
        # no es un error, es el comportamiento normal del puente. Reconectar
        # aca es deliberado (ver docs/protocolo-ble-qorvo.md).
        logger.warning("%s: reconectando (conexion BLE inactiva o caida)", self.name)
        self._run_coro(self._connect(), timeout_s=self._connect_timeout_s)
        # [Bug real, 2026-09-09, hardware real, repo hermano] El streaming
        # (ver enable_stream()) se apaga solo al desconectarse el BLE — es
        # estado de la conexion GATT, no algo persistente como el encendido
        # fisico del Qorvo (power_on(), que es un GPIO y no hace falta
        # reafirmar aca). Antes de este fix, una reconexion automatica
        # (p. ej. el timeout de inactividad de ~7-8s cayendo justo antes de
        # arrancar el ranging) dejaba el streaming apagado sin que nada lo
        # notara: las notificaciones de esa sesion no llegaban por ningun
        # canal — "0 notificaciones recibidas en 100s" con el enlace BLE
        # sano el resto del tiempo.
        self.enable_stream()

    async def _connect(self) -> None:
        client = await self._connect_with_retry()
        await client.start_notify(NUS_TX_CHAR_UUID, self._on_notify)
        await client.start_notify(STREAM_DATA_CHAR_UUID, self._on_stream_notify)
        self._client = client
        self._connected = True
        self._mtu_size = client.mtu_size
        logger.debug("%s: conectado, MTU=%s", self.name, self._mtu_size)

    async def _connect_with_retry(self) -> _BleakClientLike:
        """Reintenta `connect()` ante una falla transitoria conocida del
        backend BLE de Windows (ver `_CONNECT_RETRY_ATTEMPTS` arriba).

        Arma un cliente **nuevo** en cada intento (no reintenta sobre el
        mismo objeto que ya fallo) — reportes de la comunidad de `bleak`
        indican que reusar el mismo `BleakClient` tras una falla de este
        tipo puede dejar el objeto WinRT nativo en un estado invalido.
        """
        last_error: BleakError | OSError | None = None
        # [Mitigacion 2026-09-09, repo hermano] Cada reconexion completa
        # re-enumera todos los servicios/caracteristicas del puente por
        # defecto — costo evitable, ya que solo se usan NUS y "Qorvo
        # Stream". Se limita el descubrimiento a esos servicios y se le pide
        # a Windows reusar su cache de servicios ya conocido
        # (`use_cached_services`), lo que acelera la reconexion tras uno de
        # los cortes espontaneos del puente. Riesgo: si el catalogo GATT del
        # puente cambiara entre conexiones (p. ej. reflasheo de su firmware
        # a mitad de sesion), el cache quedaria desactualizado y esa
        # conexion fallaria. Por eso el cache es solo el camino rapido del
        # primer intento: cualquier fallo lo desactiva para el resto de los
        # intentos de esta llamada, priorizando terminar de conectar (mas
        # lento, sin cache) por sobre la velocidad.
        use_cached_services = True
        for attempt in range(1, self._connect_retry_attempts + 1):
            client = self._client_factory(
                self._address,
                disconnected_callback=self._on_disconnect,
                services=[NUS_SERVICE_UUID, STREAM_SERVICE_UUID],
                winrt={"use_cached_services": use_cached_services},
            )
            try:
                await client.connect()
                return client
            except (BleakError, OSError) as exc:
                last_error = exc
                logger.warning(
                    "%s: fallo de conexion BLE (intento %d/%d, cache de servicios=%s): %s",
                    self.name,
                    attempt,
                    self._connect_retry_attempts,
                    use_cached_services,
                    exc,
                )
                use_cached_services = False
                if attempt < self._connect_retry_attempts:
                    await asyncio.sleep(self._connect_retry_backoff_s)
        assert last_error is not None  # el loop corrio al menos una vez
        raise last_error

    async def _disconnect(self) -> None:
        if self._client is None:
            return
        try:
            if self._connected:
                await self._client.stop_notify(NUS_TX_CHAR_UUID)
                await self._client.stop_notify(STREAM_DATA_CHAR_UUID)
                await self._client.disconnect()
        finally:
            self._client = None
            self._connected = False
            self._mtu_size = None

    async def _send_raw(self, text: str) -> None:
        if self._client is None:
            raise TransportError(f"{self.name}: no conectado")
        payload = f"qorvo {text}\n".encode("ascii")
        logger.debug("TX %s: %s", self.name, payload)
        await self._client.write_gatt_char(NUS_RX_CHAR_UUID, payload, response=False)

    def _on_disconnect(self, _client: object) -> None:
        # Corre en el hilo dedicado de bleak (self._thread), como todo lo
        # que toca self._client — seguro escribir aca el mismo atributo
        # plano que lee read_line() desde cualquier otro hilo.
        self._connected = False
        logger.warning("%s: conexion BLE cerrada", self.name)

    def _on_notify(self, _sender: object, data: bytearray) -> None:
        for line in self._assembler.feed(bytes(data)):
            if _PROMPT_RE.match(line):
                logger.debug("%s: prompt de shell descartado: %r", self.name, line)
                continue
            if line.startswith(_BRIDGE_TIMEOUT_MARKER):
                logger.warning("%s: el puente reporto timeout hacia el Qorvo: %s", self.name, line)
                self._pending_error = line
                continue
            logger.debug("RX %s: %s", self.name, line)
            self._rx_queue.put(line)

    def _on_stream_notify(self, _sender: object, data: bytearray) -> None:
        """Callback de la caracteristica dedicada de streaming (ver
        `STREAM_DATA_CHAR_UUID`) — cola separada de `_on_notify`, sin el
        filtro de prompt de shell ni el marcador de timeout del puente: este
        canal es un passthrough del UART del Qorvo, no pasa por el shell de
        comandos (ver comentario junto a `STREAM_SERVICE_UUID`).
        """
        for line in self._stream_assembler.feed(bytes(data)):
            logger.debug("STREAM %s: %s", self.name, line)
            self._stream_queue.put(line)
