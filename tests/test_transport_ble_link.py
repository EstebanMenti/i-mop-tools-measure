"""Tests de imop_measure.transport.ble_link.BleTransport — no requieren hardware.

Portado de i-mop-qorvo-CLI-script/tests/test_ble_link.py (commit
ad7079aab0d32b603b4f83ce8be9ac5ce49bd0bd). Cubre los bugs reales ya
resueltos ahi (buffer colgado sin cierre, fragmentacion arbitraria de
notificaciones, prompt de shell, timeout del puente, reconexion
automatica) para no reintroducirlos al portar el codigo.
"""

from collections.abc import Callable

import pytest

from imop_measure.errors import TransportError
from imop_measure.transport.ble_link import BleTransport
from tests.fakes import FakeBleakClient

ADDRESS = "FD:7A:90:57:CC:9F"


def make_transport(
    fake_client: FakeBleakClient | None = None,
    *,
    connect_retry_attempts: int = 1,
    connect_retry_backoff_s: float = 0.0,
) -> tuple[BleTransport, FakeBleakClient]:
    client = fake_client or FakeBleakClient(ADDRESS)

    def factory(
        address: str, disconnected_callback: Callable[[object], None] | None = None
    ) -> FakeBleakClient:
        client._disconnected_callback = disconnected_callback
        return client

    transport = BleTransport(
        ADDRESS,
        power_on_settle_s=0.0,
        power_drain_s=0.05,
        connect_retry_attempts=connect_retry_attempts,
        connect_retry_backoff_s=connect_retry_backoff_s,
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
