"""Tests de imop_measure.ranging.pair_runner.run_pair.

La mayoria no requiere hardware: ejercitan el flujo completo (BleTransport
+ DwmCliClient reales) inyectando un `_transport_factory` que conecta cada
nodo a un `FakeBleakClient` scripteado, en vez de reemplazar
transporte/cliente por dobles de mas alto nivel — asi se prueba el codigo
de produccion real, no una version simplificada de el. Las marcadas
`@pytest.mark.hardware` sí requieren los nodos fisicos de
environments/sala_20.toml, y quedan excluidas por defecto.

`ANCHOR_A` siempre se usa como `responder` y `ANCHOR_B` como `initiator`
en estos tests (arbitrario, para que `RESPF_COMMAND`/`INITF_COMMAND`
queden fijos) — `run_pair` en si es simetrico respecto a cual anda es
cual, ver `ranging/campaign.py` que llama con ambas combinaciones.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from imop_measure.config.loader import load_ambiente
from imop_measure.config.models import Anchor
from imop_measure.ranging.pair_runner import (
    close_initiator,
    open_initiator,
    run_directed_measurement,
    run_pair,
)
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
ANCHOR_C = Anchor(
    key="uwb_node_c",
    nombre="UWB-Node-C",
    mac="CC:CC:CC:CC:CC:CC",
    uwb_addr="00:0C",
    posicion=(2.0, 0.0, 0.0),
    tiempo_prendido="60s",
)

STAT_NONE = (
    b'JS0080{"Info":{"Device":"X","Current App":"NONE","Version":"1.1.0",'
    b'"Build":"B","Apps":["LISTENER","RESPF","INITF"],"Driver":"D","UWB stack":"S"}}\r\nok\r\n'
)

# Comandos exactos que arma imop_measure.core.client._format_app_options
# para SessionParams() con ANCHOR_A=responder (addr=10/paddr=11) y
# ANCHOR_B=initiator (addr=11/paddr=10) — ver ranging/session.py.
RESPF_COMMAND = (
    "RESPF -CHAN=9 -PRFSET=BPRF4 -PCODE=10 -SLOT=2400 -BLOCK=200 -ROUND=25 -RRU=DSTWR -ID=42 "
    "-VUPPER=01:02:03:04:05:06:07:08 -ADDR=10 -PADDR=11"
)
INITF_COMMAND = (
    "INITF -CHAN=9 -PRFSET=BPRF4 -PCODE=10 -SLOT=2400 -BLOCK=200 -ROUND=25 -RRU=DSTWR -ID=42 "
    "-VUPPER=01:02:03:04:05:06:07:08 -ADDR=11 -PADDR=10"
)

# Mismo criterio, para ANCHOR_B=iniciador (addr=11/paddr=12) contra
# ANCHOR_C=respondedor (addr=12/paddr=11) -- usado por el test de reuso de
# conexion del iniciador contra varios respondedores.
RESPF_COMMAND_C = (
    "RESPF -CHAN=9 -PRFSET=BPRF4 -PCODE=10 -SLOT=2400 -BLOCK=200 -ROUND=25 -RRU=DSTWR -ID=42 "
    "-VUPPER=01:02:03:04:05:06:07:08 -ADDR=12 -PADDR=11"
)
INITF_COMMAND_B_VS_C = (
    "INITF -CHAN=9 -PRFSET=BPRF4 -PCODE=10 -SLOT=2400 -BLOCK=200 -ROUND=25 -RRU=DSTWR -ID=42 "
    "-VUPPER=01:02:03:04:05:06:07:08 -ADDR=11 -PADDR=12"
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
            addr: str,
            disconnected_callback: Callable[[object], None] | None = None,
            **kwargs: object,
        ) -> FakeBleakClient:
            fake._disconnected_callback = disconnected_callback
            return fake

        return BleTransport(
            address,
            power_on_settle_s=0.0,
            power_drain_s=0.01,
            connect_retry_attempts=1,
            _client_factory=client_factory,
        )

    return factory


def _make_factory_multi(fakes: dict[str, FakeBleakClient]) -> Callable[[str], BleTransport]:
    """Igual que `_make_factory`, pero para mas de 2 nodos (ver
    `test_initiator_connection_is_reused_across_multiple_responders`)."""

    def factory(address: str) -> BleTransport:
        fake = fakes[address]

        def client_factory(
            addr: str,
            disconnected_callback: Callable[[object], None] | None = None,
            **kwargs: object,
        ) -> FakeBleakClient:
            fake._disconnected_callback = disconnected_callback
            return fake

        return BleTransport(
            address,
            power_on_settle_s=0.0,
            power_drain_s=0.01,
            connect_retry_attempts=1,
            _client_factory=client_factory,
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
        initiator=ANCHOR_B,
        responder=ANCHOR_A,
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
        initiator=ANCHOR_B,
        responder=ANCHOR_A,
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
        initiator=ANCHOR_B,
        responder=ANCHOR_A,
        session=SessionParams(),
        n_samples=1,
        ble_timeouts={},
        _transport_factory=_make_factory(fake_a, fake_b),
    )

    assert result.error == "sin mediciones SUCCESS recibidas"
    assert result.n_success == 0
    assert result.mean_cm is None
    assert result.std_cm is None


def test_run_pair_keeps_successes_when_final_stop_fails() -> None:
    """Reproduce el caso real (UWB-Node-11 como respondedor, 2026-09-08,
    ver reports/medicion-20-20260908-084928.md): el enlace BLE del
    respondedor se cae por inactividad durante el muestreo y, al mandar
    `STOP` al terminar, reconectar falla. Antes del fix, `run_pair`
    descartaba las muestras ya juntadas del iniciador y reportaba 0
    SUCCESS; ahora deben conservarse.
    """
    script_a, script_b = _base_scripts()
    script_a[RESPF_COMMAND] = [b"ok\r\n"]
    script_b[INITF_COMMAND] = [
        b"ok\r\n",
        *_ntf_fragments(0, distance_cm=200),
    ]
    fake_a = FakeBleakClient(ANCHOR_A.mac, script=script_a)  # ANCHOR_A = responder
    fake_b = FakeBleakClient(ANCHOR_B.mac, script=script_b)

    original_write = fake_b.write_gatt_char

    async def write_then_drop_responder(
        char_specifier: str, data: bytes, response: bool | None = None
    ) -> None:
        await original_write(char_specifier, data, response=response)
        text = bytes(data).decode("ascii").rstrip("\n")
        if text == f"qorvo {INITF_COMMAND}":
            # Simula la desconexion por inactividad del respondedor (ver
            # transport/ble_link.py) justo cuando arranca el muestreo, y
            # que la reconexion posterior (para el STOP final) tambien
            # falle -- la falla transitoria real y documentada del backend
            # BLE de Windows.
            fake_a.simulate_disconnect()
            fake_a.fail_connect = True

    fake_b.write_gatt_char = write_then_drop_responder  # type: ignore[method-assign]

    result = run_pair(
        initiator=ANCHOR_B,
        responder=ANCHOR_A,
        session=SessionParams(),
        n_samples=1,
        ble_timeouts={},
        _transport_factory=_make_factory(fake_a, fake_b),
    )

    assert result.error is None
    assert result.n_success == 1
    assert result.distance_cm_samples == [200]


def test_run_pair_connect_failure_marks_error_without_raising() -> None:
    fake_a = FakeBleakClient(ANCHOR_A.mac, fail_connect=True)  # ANCHOR_A = responder
    fake_b = FakeBleakClient(ANCHOR_B.mac)

    result = run_pair(
        initiator=ANCHOR_B,
        responder=ANCHOR_A,
        session=SessionParams(),
        n_samples=1,
        ble_timeouts={},
        _transport_factory=_make_factory(fake_a, fake_b),
    )

    assert result.error is not None
    assert result.n_success == 0
    # El iniciador se conecta primero (open_initiator, ver
    # pair_runner.run_pair); si falla el respondedor, el iniciador ya
    # conectado se cierra igual en el finally, no queda colgado.
    assert fake_b.connect_attempts >= 1
    assert fake_b.is_connected is False


def test_run_pair_initiator_connect_failure_marks_error_without_raising() -> None:
    fake_a = FakeBleakClient(ANCHOR_A.mac)  # ANCHOR_A = responder
    fake_b = FakeBleakClient(ANCHOR_B.mac, fail_connect=True)  # ANCHOR_B = iniciador

    result = run_pair(
        initiator=ANCHOR_B,
        responder=ANCHOR_A,
        session=SessionParams(),
        n_samples=1,
        ble_timeouts={},
        _transport_factory=_make_factory(fake_a, fake_b),
    )

    assert result.error is not None
    assert result.n_success == 0
    # Si el propio iniciador no conecta, el respondedor ni se intenta.
    assert fake_a.connect_attempts == 0


def test_open_initiator_retries_after_transient_connect_failure() -> None:
    """[Verificado 2026-09-09, hardware real] Una falla de conexion
    transitoria al abrir el iniciador (ver `pair_runner._OPEN_RETRY_ATTEMPTS`)
    no debe descartar de entrada las direcciones de todo el nodo: el primer
    intento falla, se cierra ese transporte y se reintenta con uno nuevo,
    que esta vez conecta bien.
    """
    _, script_b = _base_scripts()
    fake_b = FakeBleakClient(ANCHOR_B.mac, script=script_b, fail_connect_times=1)

    handle = open_initiator(
        ANCHOR_B,
        ble_timeouts={},
        _transport_factory=_make_factory(FakeBleakClient(ANCHOR_A.mac), fake_b),
    )
    try:
        assert fake_b.connect_attempts == 2
        assert fake_b.is_connected is True
    finally:
        close_initiator(handle)


def test_run_directed_measurement_retries_responder_after_transient_connect_failure() -> None:
    """Mismo criterio que `test_open_initiator_retries_after_transient_connect_failure`,
    pero para la conexion del respondedor (ver `pair_runner._open_and_confirm_none`,
    usada por ambos roles) — reproduce el caso real de
    reports/medicion-20-20260909-160954.md, donde varios respondedores
    disponibles (confirmado porque midieron bien en otras direcciones de la
    misma campaña) fallaron una vez de forma transitoria y quedaban en
    `ERROR` sin reintentar.
    """
    script_a, script_b = _base_scripts()
    script_a[RESPF_COMMAND] = [b"ok\r\n"]
    script_b[INITF_COMMAND] = [b"ok\r\n", *_ntf_fragments(0, distance_cm=200)]
    fake_a = FakeBleakClient(ANCHOR_A.mac, script=script_a, fail_connect_times=1)
    fake_b = FakeBleakClient(ANCHOR_B.mac, script=script_b)

    result = run_pair(
        initiator=ANCHOR_B,
        responder=ANCHOR_A,
        session=SessionParams(),
        n_samples=1,
        ble_timeouts={},
        _transport_factory=_make_factory(fake_a, fake_b),
    )

    assert result.error is None
    assert result.n_success == 1
    assert fake_a.connect_attempts == 2


def test_run_pair_handles_real_three_fragment_notification() -> None:
    """Captura real (2026-09-07, uwb_node_10 <-> uwb_node_11 fisicos).

    El formato realmente observado en hardware difiere del documentado
    originalmente en el repo hermano (2 lineas, continuacion con `\\r`
    residual): acá llegan **3** lineas — la principal, una linea vacia
    (residuo de un `\\r` suelto), y la continuacion arrancando con un
    espacio (no `\\r`). `read_notifications`/`parse_session_info` lo
    parsean bien de todos modos porque acumulan fragmentos hasta balancear
    llaves, sin asumir una cantidad fija de lineas — este test fija ese
    comportamiento como regresion. Ver docs/protocolo-ble-qorvo.md
    seccion 4.
    """
    script_a, script_b = _base_scripts()
    script_a[RESPF_COMMAND] = [b"ok\r\n"]
    real_capture = (
        b"SESSION_INFO_NTF: {session_handle=1, sequence_number=0, block_index=0,"
        b' n_measurements=1\r\n\r\n [mac_address=0x0001, status="SUCCESS", distance[cm]=337]}\r\n'
    )
    script_b[INITF_COMMAND] = [b"ok\r\n", real_capture]
    fake_a = FakeBleakClient(ANCHOR_A.mac, script=script_a)
    fake_b = FakeBleakClient(ANCHOR_B.mac, script=script_b)

    result = run_pair(
        initiator=ANCHOR_B,
        responder=ANCHOR_A,
        session=SessionParams(),
        n_samples=1,
        ble_timeouts={},
        _transport_factory=_make_factory(fake_a, fake_b),
    )

    assert result.error is None
    assert result.distance_cm_samples == [337]


def test_initiator_connection_is_reused_across_multiple_responders() -> None:
    """`open_initiator` + 2x `run_directed_measurement` + `close_initiator`:
    el iniciador (ANCHOR_B) debe conectarse una sola vez por BLE aunque
    mida contra 2 respondedores distintos en secuencia -- la optimizacion
    que usa `ranging/campaign.py` para no reconectarlo en cada direccion
    (ver docs/arquitectura.md decision D3).
    """
    script_a, script_b = _base_scripts()
    script_a[RESPF_COMMAND] = [b"ok\r\n"]
    script_b[INITF_COMMAND] = [b"ok\r\n", *_ntf_fragments(0, distance_cm=200)]
    script_b[INITF_COMMAND_B_VS_C] = [b"ok\r\n", *_ntf_fragments(0, distance_cm=300)]
    script_c = {"STOP": [b"ok\r\n"], "STAT": [STAT_NONE], RESPF_COMMAND_C: [b"ok\r\n"]}

    fake_a = FakeBleakClient(ANCHOR_A.mac, script=script_a)
    fake_b = FakeBleakClient(ANCHOR_B.mac, script=script_b)
    fake_c = FakeBleakClient(ANCHOR_C.mac, script=script_c)
    factory = _make_factory_multi(
        {ANCHOR_A.mac: fake_a, ANCHOR_B.mac: fake_b, ANCHOR_C.mac: fake_c}
    )

    handle = open_initiator(ANCHOR_B, ble_timeouts={}, _transport_factory=factory)
    try:
        result_a = run_directed_measurement(
            initiator_handle=handle,
            responder=ANCHOR_A,
            session=SessionParams(),
            n_samples=1,
            ble_timeouts={},
            _transport_factory=factory,
        )
        result_c = run_directed_measurement(
            initiator_handle=handle,
            responder=ANCHOR_C,
            session=SessionParams(),
            n_samples=1,
            ble_timeouts={},
            _transport_factory=factory,
        )
    finally:
        close_initiator(handle)

    assert result_a.error is None
    assert result_a.distance_cm_samples == [200]
    assert result_c.error is None
    assert result_c.distance_cm_samples == [300]
    # El iniciador se conecto una sola vez para las 2 mediciones.
    assert fake_b.connect_attempts == 1
    # Los respondedores si se conectan y desconectan cada uno por su lado.
    assert fake_a.connect_attempts == 1
    assert fake_c.connect_attempts == 1
    # close_initiator desconecta al iniciador recien al final del grupo.
    assert fake_b.is_connected is False


@pytest.mark.hardware
def test_run_pair_against_real_nodes() -> None:
    """Corre run_pair contra los nodos fisicos de environments/sala_20.toml.

    Requiere tener ambos nodos encendidos y al alcance de BLE. Verificado
    manualmente el 2026-09-07 con uwb_node_10 como respondedor y
    uwb_node_11 como iniciador (reales): 15/15 muestras SUCCESS, media
    341.9 cm, desvio 2.1 cm. La direccion inversa (node_10 iniciador,
    node_11 respondedor) la ejercita
    test_ranging_campaign.py::test_run_campaign_against_real_nodes.
    """
    toml_path = Path(__file__).resolve().parent.parent / "environments" / "sala_20.toml"
    ambiente = load_ambiente(toml_path)
    node_responder, node_initiator = ambiente.anchors[0], ambiente.anchors[1]

    result = run_pair(
        initiator=node_initiator,
        responder=node_responder,
        session=SessionParams(),
        n_samples=10,
        ble_timeouts=ambiente.ble_timeouts,
    )

    assert result.error is None, result.error
    # Al menos la mitad de las muestras pedidas, mismo criterio que
    # dwm3001c_cli.calibration.sampler.collect_samples (enlace malo si no).
    assert result.n_success >= result.n_requested / 2
    assert result.mean_cm is not None
    assert 0 < result.mean_cm < 5000  # rango fisicamente plausible en interiores (< 50 m)
