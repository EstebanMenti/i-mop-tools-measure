"""Tests de imop_measure.ranging.pair_runner.run_pair — no requieren hardware.

Ejercita el flujo completo (BleTransport + DwmCliClient reales) inyectando
un `_transport_factory` que conecta cada nodo a un `FakeBleakClient`
scripteado, en vez de reemplazar transporte/cliente por dobles de mas
alto nivel — asi se prueba el codigo de produccion real, no una version
simplificada de el.
"""

from collections.abc import Callable

import pytest

from imop_measure.config.models import Anchor
from imop_measure.ranging.pair_runner import run_pair
from imop_measure.ranging.session import SessionParams
from imop_measure.transport.ble_link import BleTransport
from tests.fakes import FakeBleakClient

ANCHOR_A = Anchor(
    key="uwb_node_a",
    nombre="UWB-Node-A",
    mac="AA:AA:AA:AA:AA:AA",
    uwb_addr="00:0A",
    posicion=(0.0, 0.0, 0.0),
    tiempo_prendido="60s",
)
ANCHOR_B = Anchor(
    key="uwb_node_b",
    nombre="UWB-Node-B",
    mac="BB:BB:BB:BB:BB:BB",
    uwb_addr="00:0B",
    posicion=(1.0, 0.0, 0.0),
    tiempo_prendido="60s",
)

STAT_NONE = (
    b'JS0080{"Info":{"Device":"X","Current App":"NONE","Version":"1.1.0",'
    b'"Build":"B","Apps":["LISTENER","RESPF","INITF"],"Driver":"D","UWB stack":"S"}}\r\nok\r\n'
)

# Comandos exactos que arma imop_measure.core.client._format_app_options
# para SessionParams() con addr=10/paddr=11 (respondedor) y addr=11/paddr=10
# (iniciador) — ver ranging/session.py.
RESPF_COMMAND = (
    "RESPF -CHAN=9 -PRFSET=BPRF4 -PCODE=10 -SLOT=2400 -BLOCK=200 -ROUND=25 -RRU=DSTWR -ID=42 "
    "-VUPPER=01:02:03:04:05:06:07:08 -ADDR=10 -PADDR=11"
)
INITF_COMMAND = (
    "INITF -CHAN=9 -PRFSET=BPRF4 -PCODE=10 -SLOT=2400 -BLOCK=200 -ROUND=25 -RRU=DSTWR -ID=42 "
    "-VUPPER=01:02:03:04:05:06:07:08 -ADDR=11 -PADDR=10"
)


def _ntf_fragments(n: int, *, distance_cm: int | None, status: str = "SUCCESS") -> list[bytes]:
    """Dos fragmentos BLE que reproducen el formato real de SESSION_INFO_NTF
    partido en dos lineas (ver docs/protocolo-ble-qorvo.md seccion 4)."""
    distance_part = f", distance[cm]={distance_cm}" if distance_cm is not None else ""
    line1 = (
        f"SESSION_INFO_NTF: {{session_handle=1, sequence_number={n}, "
        f"block_index={n}, n_measurements=1\r\n"
    )
    line2 = f'\r [mac_address=0x000A, status="{status}"{distance_part}]}}\r\n'
    return [line1.encode("ascii"), line2.encode("ascii")]


def _make_factory(
    fake_a: FakeBleakClient, fake_b: FakeBleakClient
) -> Callable[[str], BleTransport]:
    fakes = {ANCHOR_A.mac: fake_a, ANCHOR_B.mac: fake_b}

    def factory(address: str) -> BleTransport:
        fake = fakes[address]

        def client_factory(
            addr: str, disconnected_callback: Callable[[object], None] | None = None
        ) -> FakeBleakClient:
            fake._disconnected_callback = disconnected_callback
            return fake

        return BleTransport(
            address, power_on_settle_s=0.0, power_drain_s=0.01, _client_factory=client_factory
        )

    return factory


def _base_scripts() -> tuple[dict[str, list[bytes]], dict[str, list[bytes]]]:
    return (
        {"STOP": [b"ok\r\n"], "STAT": [STAT_NONE]},
        {"STOP": [b"ok\r\n"], "STAT": [STAT_NONE]},
    )


def test_run_pair_all_success() -> None:
    script_a, script_b = _base_scripts()
    script_a[RESPF_COMMAND] = [b"ok\r\n"]
    script_b[INITF_COMMAND] = [
        b"ok\r\n",
        *_ntf_fragments(0, distance_cm=200),
        *_ntf_fragments(1, distance_cm=202),
    ]
    fake_a = FakeBleakClient(ANCHOR_A.mac, script=script_a)
    fake_b = FakeBleakClient(ANCHOR_B.mac, script=script_b)

    result = run_pair(
        ANCHOR_A,
        ANCHOR_B,
        session=SessionParams(),
        n_samples=2,
        ble_timeouts={},
        _transport_factory=_make_factory(fake_a, fake_b),
    )

    assert result.error is None
    assert result.n_success == 2
    assert result.n_requested == 2
    assert result.distance_cm_samples == [200, 202]
    assert result.mean_cm == pytest.approx(201.0)


def test_run_pair_mixed_success_and_timeout() -> None:
    script_a, script_b = _base_scripts()
    script_a[RESPF_COMMAND] = [b"ok\r\n"]
    script_b[INITF_COMMAND] = [
        b"ok\r\n",
        *_ntf_fragments(0, distance_cm=None, status="RX_TIMEOUT"),
        *_ntf_fragments(1, distance_cm=210),
    ]
    fake_a = FakeBleakClient(ANCHOR_A.mac, script=script_a)
    fake_b = FakeBleakClient(ANCHOR_B.mac, script=script_b)

    result = run_pair(
        ANCHOR_A,
        ANCHOR_B,
        session=SessionParams(),
        n_samples=1,
        ble_timeouts={},
        _transport_factory=_make_factory(fake_a, fake_b),
    )

    assert result.error is None
    assert result.n_success == 1
    assert result.distance_cm_samples == [210]


def test_run_pair_zero_success_marks_error_without_raising() -> None:
    script_a, script_b = _base_scripts()
    script_a[RESPF_COMMAND] = [b"ok\r\n"]
    script_b[INITF_COMMAND] = [b"ok\r\n"]  # ninguna notificacion de ranging
    fake_a = FakeBleakClient(ANCHOR_A.mac, script=script_a)
    fake_b = FakeBleakClient(ANCHOR_B.mac, script=script_b)

    result = run_pair(
        ANCHOR_A,
        ANCHOR_B,
        session=SessionParams(),
        n_samples=1,
        ble_timeouts={},
        _transport_factory=_make_factory(fake_a, fake_b),
    )

    assert result.error == "sin mediciones SUCCESS recibidas"
    assert result.n_success == 0
    assert result.mean_cm is None
    assert result.std_cm is None


def test_run_pair_connect_failure_marks_error_without_raising() -> None:
    fake_a = FakeBleakClient(ANCHOR_A.mac, fail_connect=True)
    fake_b = FakeBleakClient(ANCHOR_B.mac)

    result = run_pair(
        ANCHOR_A,
        ANCHOR_B,
        session=SessionParams(),
        n_samples=1,
        ble_timeouts={},
        _transport_factory=_make_factory(fake_a, fake_b),
    )

    assert result.error is not None
    assert result.n_success == 0
    assert fake_b.is_connected is False  # nunca se llego a abrir el segundo transporte
