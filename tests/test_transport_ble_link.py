"""Tests de imop_measure.transport.ble_link.BleTransport — no requieren hardware.

Portado de i-mop-qorvo-CLI-script/tests/test_ble_link.py (commit
ad7079aab0d32b603b4f83ce8be9ac5ce49bd0bd). Cubre los bugs reales ya
resueltos ahi (buffer colgado sin cierre, fragmentacion arbitraria de
notificaciones, prompt de shell, timeout del puente, reconexion
automatica) para no reintroducirlos al portar el codigo.
"""

from collections.abc import Callable

import pytest
from bleak.exc import BleakError

from imop_measure.errors import TransportError
from imop_measure.transport import ble_link as ble_link_module
from imop_measure.transport.ble_link import BleTransport
from tests.fakes import FakeBleakClient

ADDRESS = "FD:7A:90:57:CC:9F"


def make_transport(
    fake_client: FakeBleakClient | None = None,
    *,
    connect_retry_attempts: int = 1,
    connect_retry_backoff_s: float = 0.0,
    power_on_hold_s: float | None = None,
) -> tuple[BleTransport, FakeBleakClient]:
    client = fake_client or FakeBleakClient(ADDRESS)

    def factory(
        address: str,
        disconnected_callback: Callable[[object], None] | None = None,
        services: object = None,
        *,
        winrt: dict[str, object] | None = None,
        **_kwargs: object,
    ) -> FakeBleakClient:
        client._disconnected_callback = disconnected_callback
        client.requested_services = list(services) if services is not None else None  # type: ignore[arg-type]
        client.winrt_args = dict(winrt or {})
        return client

    transport = BleTransport(
        ADDRESS,
        power_on_settle_s=0.0,
        power_drain_s=0.05,
        power_cycle_off_settle_s=0.0,
        connect_retry_attempts=connect_retry_attempts,
        connect_retry_backoff_s=connect_retry_backoff_s,
        power_on_hold_s=power_on_hold_s,
        _client_factory=factory,
    )
    return transport, client


class TestLifecycle:
    def test_open_connects_and_powers_on_module(self) -> None:
        transport, client = make_transport()

        with transport:
            assert client.is_connected

        assert b"qorvo on\n" in client.sent
        assert not client.is_connected

    def test_power_cycle_sends_off_then_on(self) -> None:
        transport, client = make_transport()

        with transport:
            client.sent.clear()
            transport.power_cycle()

        assert client.sent == [b"qorvo off\n", b"qorvo on\n"]

    def test_open_applies_power_on_hold_s_as_safety_auto_off(self) -> None:
        """Si se construye con `power_on_hold_s`, `open()` enciende el
        modulo con `-t` -- apagado automatico de seguridad (ver
        `SAFETY_AUTO_OFF_HOLD_S`), no un `qorvo on` sin limite."""
        transport, client = make_transport(power_on_hold_s=1500.0)

        with transport:
            pass

        assert b"qorvo on -t 1500s\n" in client.sent

    def test_power_cycle_reapplies_power_on_hold_s(self) -> None:
        """El power-cycle de cada direccion tambien debe re-armar el
        apagado automatico de seguridad, no solo el `open()` inicial."""
        transport, client = make_transport(power_on_hold_s=1500.0)

        with transport:
            client.sent.clear()
            transport.power_cycle()

        assert client.sent == [b"qorvo off\n", b"qorvo on -t 1500s\n"]

    def test_open_without_power_on_hold_s_keeps_plain_on(self) -> None:
        """`power_on_hold_s=None` (default) preserva el comportamiento
        anterior, sin limite de tiempo."""
        transport, client = make_transport()

        with transport:
            pass

        assert b"qorvo on\n" in client.sent

    def test_connect_failure_raises_transport_error(self) -> None:
        fake = FakeBleakClient(ADDRESS, fail_connect=True)
        transport, _ = make_transport(fake)

        with pytest.raises(TransportError):
            transport.open()

        transport.close()  # no debe fallar aunque nunca haya llegado a conectar

    def test_name_is_filename_safe(self) -> None:
        transport, _ = make_transport()

        assert transport.name == "BLE-FD7A9057CC9F"
        assert ":" not in transport.name


class TestWriteLine:
    def test_prefixes_with_qorvo_and_newline(self) -> None:
        transport, client = make_transport()

        with transport:
            transport.write_line("STAT")

        assert b"qorvo STAT\n" in client.sent

    def test_reconnects_automatically_after_disconnect(self) -> None:
        fake = FakeBleakClient(ADDRESS)
        transport, client = make_transport(fake)

        with transport:
            client.simulate_disconnect()
            assert not client.is_connected

            transport.write_line("STAT")

            assert client.is_connected
            assert b"qorvo STAT\n" in client.sent

    def test_resets_leftover_partial_line_before_new_command(self) -> None:
        # Una notificacion BLE perdida (Notify no tiene ACK/retry) puede
        # dejar un fragmento sin "\n" de cierre colgado en el buffer para
        # siempre. write_line() debe descartar cualquier resto antes de
        # mandar el siguiente comando.
        fake = FakeBleakClient(ADDRESS)
        fake.script["STAT"] = [b"stat\r\nJS0109{}\r\n\r\nok\r\n"]
        transport, client = make_transport(fake)

        with transport:
            assert client._notify_callback is not None
            client._notify_callback(None, bytearray(b"CALKEY leftover_sin_cierre"))

            transport.write_line("STAT")
            lines: list[str] = []
            while (line := transport.read_line(0.2)) is not None:
                lines.append(line)

        assert "leftover_sin_cierre" not in " ".join(lines)
        assert lines == ["stat", "JS0109{}", "", "ok"]


class TestReadLine:
    def test_reassembles_fragments_and_filters_shell_prompt(self) -> None:
        fake = FakeBleakClient(ADDRESS)
        fake.script["STAT"] = [
            b"\r\n",
            b"stat\r\nJS0109",
            b'{"a":1}\r\n\r\nok\r\n\r\nbt_nus:~$ \r\n',
        ]
        transport, _ = make_transport(fake)

        with transport:
            transport.write_line("STAT")
            lines: list[str] = []
            while (line := transport.read_line(0.2)) is not None:
                lines.append(line)

        assert lines == ["", "stat", 'JS0109{"a":1}', "", "ok", ""]
        assert "bt_nus:~$ " not in lines

    def test_bridge_timeout_marker_raises_transport_error(self) -> None:
        fake = FakeBleakClient(ADDRESS)
        fake.script["STAT"] = [
            b"Error: sin respues",
            b"ta del modulo Qorvo (timeout)\r\n",
        ]
        transport, _ = make_transport(fake)

        with transport:
            transport.write_line("STAT")
            with pytest.raises(TransportError, match="timeout"):
                transport.read_line(0.5)

    def test_returns_none_on_timeout_without_data(self) -> None:
        transport, _ = make_transport()

        with transport:
            assert transport.read_line(0.1) is None


class TestPower:
    def test_power_on_with_hold_formats_time_option(self) -> None:
        transport, client = make_transport()

        with transport:
            transport.power_on(hold_s=60)

        assert b"qorvo on -t 60s\n" in client.sent

    def test_power_off(self) -> None:
        transport, client = make_transport()

        with transport:
            transport.power_off()

        assert b"qorvo off\n" in client.sent


class TestConnectRetry:
    """Mitiga fallas transitorias conocidas del backend BLE de Windows
    (BleakError u OSError nativo — ver `_CONNECT_RETRY_ATTEMPTS` en
    ble_link.py) reintentando la conexion. Investigado y agregado a pedido
    del usuario tras encontrarlo contra hardware real (2026-09-07)."""

    def test_retries_transient_bleak_error_and_succeeds(self) -> None:
        fake = FakeBleakClient(ADDRESS, fail_connect_times=2)
        transport, _ = make_transport(fake, connect_retry_attempts=3, connect_retry_backoff_s=0.0)

        with transport:
            assert fake.is_connected

        assert fake.connect_attempts == 3

    def test_retries_raw_oserror_from_winrt_backend(self) -> None:
        # Caso real observado contra hardware: el backend WinRT de bleak
        # a veces filtra un OSError crudo en vez de BleakError (ej.
        # "[WinError -2147483629] Se cerro el objeto").
        fake = FakeBleakClient(ADDRESS, fail_connect_times=1, fail_connect_exception=OSError)
        transport, _ = make_transport(fake, connect_retry_attempts=2, connect_retry_backoff_s=0.0)

        with transport:
            assert fake.is_connected

        assert fake.connect_attempts == 2

    def test_gives_up_after_max_attempts_and_wraps_as_transport_error(self) -> None:
        fake = FakeBleakClient(ADDRESS, fail_connect=True)
        transport, _ = make_transport(fake, connect_retry_attempts=2, connect_retry_backoff_s=0.0)

        with pytest.raises(TransportError):
            transport.open()

        assert fake.connect_attempts == 2

    def test_gives_up_wraps_raw_oserror_as_transport_error(self) -> None:
        fake = FakeBleakClient(ADDRESS, fail_connect=True, fail_connect_exception=OSError)
        transport, _ = make_transport(fake, connect_retry_attempts=2, connect_retry_backoff_s=0.0)

        with pytest.raises(TransportError, match="error BLE"):
            transport.open()


class TestServiceCache:
    """Descubrimiento GATT acotado a los servicios usados + cache de
    servicios de Windows en el primer intento de conexion (portado del
    repo hermano, commit 125568b)."""

    def test_first_connect_requests_scoped_service_and_cache(self) -> None:
        # [Mitigacion 2026-09-09] Reduce el tiempo muerto de una reconexion:
        # limitar el descubrimiento a los servicios usados (NUS + streaming)
        # y pedirle a Windows que reuse su cache de servicios ya conocido.
        transport, client = make_transport()

        with transport:
            assert client.requested_services == [
                ble_link_module.NUS_SERVICE_UUID,
                ble_link_module.STREAM_SERVICE_UUID,
            ]
            assert client.winrt_args == {"use_cached_services": True}

    def test_connect_falls_back_to_uncached_services_after_failure(self) -> None:
        # Si el camino rapido (cache de servicios de Windows) falla, la
        # conexion igual debe completarse — prefiriendo una reconexion mas
        # lenta (sin cache, redescubriendo todo el GATT) a que la
        # optimizacion bloquee el proceso.
        calls: list[FakeBleakClient] = []

        class FailsWithCachedServices(FakeBleakClient):
            async def connect(self) -> None:
                if self.winrt_args.get("use_cached_services"):
                    raise BleakError("fake: cache de servicios desactualizado")
                await super().connect()

        def factory(
            address: str,
            disconnected_callback: Callable[[object], None] | None = None,
            **kwargs: object,
        ) -> FakeBleakClient:
            client = FailsWithCachedServices(address, **kwargs)  # type: ignore[arg-type]
            client._disconnected_callback = disconnected_callback
            calls.append(client)
            return client

        transport = BleTransport(
            ADDRESS,
            power_on_settle_s=0.0,
            power_drain_s=0.05,
            power_cycle_off_settle_s=0.0,
            connect_timeout_s=5.0,
            _client_factory=factory,
        )
        with transport:
            assert transport._client is calls[-1]
            assert calls[-1].is_connected

        # El primer intento pidio cache y fallo; el siguiente lo desactivo y
        # conecto con exito — el proceso termino conectando, no se bloqueo.
        assert len(calls) >= 2
        assert calls[0].winrt_args == {"use_cached_services": True}
        assert calls[-1].winrt_args == {"use_cached_services": False}


class TestStreaming:
    """Canal BLE dedicado de streaming (`STREAM_SERVICE_UUID` /
    `STREAM_DATA_CHAR_UUID`), separado del canal de comandos (NUS TX) —
    ver comentario junto a `STREAM_SERVICE_UUID` en `ble_link.py` para el
    motivo (el canal de comandos suspendia el UART tras 8s de ranging
    continuo, sin este canal dedicado)."""

    def test_open_subscribes_to_stream_and_enables_it(self) -> None:
        transport, client = make_transport()

        with transport:
            assert ble_link_module.STREAM_DATA_CHAR_UUID in client._notify_callbacks
            assert b"qorvo stream on\n" in client.sent

    def test_read_notification_line_reads_from_dedicated_stream_channel(self) -> None:
        transport, client = make_transport()

        with transport:
            client.simulate_stream_data(
                b"SESSION_INFO_NTF: {session_handle=1, sequence_number=0, block_index=0,"
                b' n_measurements=1 [mac_address=0x0001, status="SUCCESS", distance[cm]=200]}\r\n'
            )
            assert transport.read_notification_line(0.2) == (
                "SESSION_INFO_NTF: {session_handle=1, sequence_number=0, block_index=0,"
                ' n_measurements=1 [mac_address=0x0001, status="SUCCESS", distance[cm]=200]}'
            )

    def test_stream_data_never_reaches_command_channel(self) -> None:
        # El motivo de tener dos colas separadas: un STAT de keepalive
        # durante el muestreo no debe comerse (ni contaminarse con)
        # notificaciones de ranging en curso, y viceversa.
        transport, client = make_transport()

        with transport:
            client.simulate_stream_data(b"SESSION_INFO_NTF: {algo}\r\n")
            assert transport.read_line(0.2) is None
            assert transport.read_notification_line(0.2) == "SESSION_INFO_NTF: {algo}"

    def test_command_response_never_reaches_stream_channel(self) -> None:
        fake = FakeBleakClient(ADDRESS, script={"STAT": [b"mode: NONE\r\nok\r\n"]})
        transport, _ = make_transport(fake)

        with transport:
            transport.write_line("STAT")
            assert transport.read_line(0.2) == "mode: NONE"
            assert transport.read_notification_line(0.1) is None

    def test_reenables_stream_after_automatic_reconnect(self) -> None:
        # [Bug real, 2026-09-09, hardware real, repo hermano] El streaming se
        # apaga solo al desconectarse el BLE (a diferencia del encendido
        # fisico del Qorvo, que es un GPIO persistente). Antes de este fix,
        # una reconexion automatica (p. ej. el timeout de inactividad de
        # ~7-8s cayendo justo antes de arrancar el ranging) dejaba el
        # streaming apagado sin que nada lo notara: "0 notificaciones
        # recibidas en 100s" con el enlace BLE sano el resto del tiempo.
        fake = FakeBleakClient(ADDRESS)
        transport, client = make_transport(fake)

        with transport:
            stream_on_before = client.sent.count(b"qorvo stream on\n")
            client.simulate_disconnect()

            transport.write_line("STAT")  # dispara la reconexion automatica

            assert client.sent.count(b"qorvo stream on\n") == stream_on_before + 1
