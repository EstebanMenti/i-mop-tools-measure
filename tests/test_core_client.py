"""Tests de imop_measure.core.client.DwmCliClient — no requieren hardware.

Casos portados de i-mop-qorvo-CLI-script/tests/test_client.py (commit
ad7079aab0d32b603b4f83ce8be9ac5ce49bd0bd), adaptados a la API de este
proyecto (sin enable_uart_output/restore, deliberadamente no portados —
ver docs/arquitectura.md decision D1).
"""

from pathlib import Path

import pytest

from imop_measure.core.client import DwmCliClient
from imop_measure.errors import CommandRejectedError, CommandTimeoutError, UnexpectedModeError
from tests.fakes import FakeTransport

FIXTURES = Path(__file__).parent / "fixtures"
STAT_REAL = (FIXTURES / "stat_fw110_real.txt").read_text(encoding="utf-8").splitlines()

STAT_RUNNING_INITF = [
    "STAT",
    'JS0080{"Info":{"Device":"X","Current App":"INITF","Version":"1.1.0",'
    '"Build":"B","Apps":["LISTENER","RESPF","INITF"],"Driver":"D","UWB stack":"S"}}',
    "ok",
]


def ntf_line(n: int, *, distance_cm: int = 200) -> str:
    return (
        f"SESSION_INFO_NTF: {{session_handle=1, sequence_number={n}, block_index={n},"
        f' n_measurements=1 [mac_address=0x0001, status="SUCCESS", distance[cm]={distance_cm}]}}'
    )


def make_client(
    script: dict[str, list[str]] | None = None, notifications: list[str] | None = None
) -> tuple[DwmCliClient, FakeTransport]:
    transport = FakeTransport(script=script, notifications=notifications or [])
    return DwmCliClient(transport, command_timeout_s=0.2), transport


class TestSendCommand:
    def test_discards_echo_and_stops_at_ok(self) -> None:
        client, _ = make_client({"STAT": STAT_REAL})

        lines = client.send_command("STAT")

        assert lines[0].startswith("JS0109")
        assert lines[-1] == "ok"

    def test_silence_raises_timeout_with_context(self) -> None:
        client, _ = make_client({})

        with pytest.raises(CommandTimeoutError) as exc_info:
            client.send_command("STAT", timeout_s=0.05)

        assert exc_info.value.port == "FAKE"
        assert exc_info.value.command == "STAT"

    def test_stops_at_ko_error_marker(self) -> None:
        client, _ = make_client({"CALKEY nada": ["", "Please enter a valid key: nada", "", "KO"]})

        lines = client.send_command("CALKEY nada")

        assert lines[-1] == "KO"

    def test_strips_echo_glued_without_separator(self) -> None:
        client, _ = make_client({"STAT": ['STAT\rJS0109{"Info":{', "ok"]})

        lines = client.send_command("STAT")

        assert lines[0] == 'JS0109{"Info":{'
        assert lines[-1] == "ok"

    def test_does_not_strip_response_that_merely_starts_like_the_command(self) -> None:
        client, _ = make_client({"DIAG": ["DIAG: 0", "ok"]})

        lines = client.send_command("DIAG")

        assert lines[0] == "DIAG: 0"

    def test_quiet_period_ends_collection_without_ok(self) -> None:
        client, _ = make_client({"THREAD": ["linea 1", "linea 2"]})

        assert client.send_command("THREAD") == ["linea 1", "linea 2"]

    def test_quiet_period_without_own_echo_on_ntf_backlog_raises_timeout(self) -> None:
        # Real (2026-09-09, hardware real, firmware puente >= 0.3.0): el
        # STAT de keepalive del respondedor recibio decenas de notificaciones
        # SESSION_INFO_NTF capturadas por la ventana de relay de `qorvo
        # STAT`, cortadas por silencio y sin haber visto nunca el eco de
        # STAT — el "ok" real se perdio. Antes ese backlog se devolvia como
        # si fuera la respuesta y parse_stat fallaba con "Salida de STAT sin
        # bloque JSxxxx"; ahora silencio con contenido pero sin eco propio
        # no se acepta como respuesta: debe vencer por timeout (y el
        # keepalive de pair_runner ignora la falla).
        client, _ = make_client({"STAT": [ntf_line(1), ntf_line(2)]})

        with pytest.raises(CommandTimeoutError):
            client.send_command("STAT")

    def test_discards_stale_backlog_of_another_command(self) -> None:
        # Real (repo hermano, puente BLE): la respuesta rezagada de un
        # comando anterior (con su propio eco y su propio "ok") llego en la
        # cola justo cuando se pidió STAT — debe descartarse y seguir
        # esperando la respuesta real.
        client, transport = make_client({"STAT": STAT_REAL})
        transport.push_lines(["THREAD", "THREAD NAME     \tStack usage", "ok"])

        lines = client.send_command("STAT")

        assert lines[0].startswith("JS0109")
        assert lines[-1] == "ok"
        assert not any(line.startswith("THREAD") for line in lines)

    def test_discards_ntf_backlog_ending_in_foreign_echo(self) -> None:
        # Real (repo hermano, dos placas por Bluetooth): el eco ajeno no
        # estaba en la primera linea sino al final de un backlog largo de
        # notificaciones, seguido del eco+"ok" rezagado de un STOP anterior.
        client, transport = make_client({"STAT": STAT_REAL})
        transport.push_lines([ntf_line(n) for n in range(40)] + ["STOP", "ok"])

        lines = client.send_command("STAT")

        assert lines[0].startswith("JS0109")
        assert lines[-1] == "ok"
        assert not any(line.startswith("SESSION_INFO_NTF") or line == "STOP" for line in lines)


class TestStatAndMode:
    def test_stat_parses_real_output(self) -> None:
        client, _ = make_client({"STAT": STAT_REAL})

        info = client.stat()

        assert info.mode == "NONE"
        assert info.version == "1.1.0"

    def test_ensure_mode_none_when_already_none(self) -> None:
        client, transport = make_client({"STOP": ["ok"], "STAT": STAT_REAL})

        client.ensure_mode_none()

        assert transport.sent == ["STOP", "STAT"]

    def test_ensure_mode_none_raises_if_app_persists(self) -> None:
        client, transport = make_client({"STOP": ["ok"], "STAT": STAT_RUNNING_INITF})

        with pytest.raises(UnexpectedModeError, match="INITF"):
            client.ensure_mode_none()

        assert transport.sent == ["STOP", "STAT", "STOP", "STAT"]

    def test_stop_tolerates_silence(self) -> None:
        client, _ = make_client({})

        client.stop()  # no debe lanzar


class TestCalKeys:
    def test_calkey_read(self) -> None:
        client, _ = make_client(
            {"CALKEY ant0.ch9.ant_delay": ["ant0.ch9.ant_delay: 0x4015 (len: 4)", "ok"]}
        )

        cal_key = client.calkey_read("ant0.ch9.ant_delay")

        assert cal_key.value == 0x4015

    def test_calkey_read_falls_back_to_listcal_on_fw_bug(self) -> None:
        client, transport = make_client(
            {
                "CALKEY ant0.ch9.ant_delay": ["", "Please enter a valid key: ...", "KO"],
                "LISTCAL": ["ant0.ch9.ant_delay: 0x3FF7 (len: 4)", "ok"],
            }
        )

        cal_key = client.calkey_read("ant0.ch9.ant_delay")

        assert cal_key.value == 0x3FF7
        assert "LISTCAL" in transport.sent

    def test_calkey_write_verifies_by_rereading(self) -> None:
        client, transport = make_client(
            {
                "CALKEY xtal_trim 50": ["xtal_trim: 0x32 (len: 1)", "ok"],
                "CALKEY xtal_trim": ["xtal_trim: 0x32 (len: 1)", "ok"],
            }
        )

        written = client.calkey_write("xtal_trim", 50)  # 50 == 0x32

        assert written.value == 50
        assert transport.sent == ["CALKEY xtal_trim 50", "CALKEY xtal_trim"]

    def test_calkey_write_mismatch_raises(self) -> None:
        client, _ = make_client(
            {
                "CALKEY xtal_trim 7": ["xtal_trim: 0x07 (len: 1)", "ok"],
                "CALKEY xtal_trim": ["xtal_trim: 0x32 (len: 1)", "ok"],
            }
        )

        with pytest.raises(CommandRejectedError, match="sospechoso"):
            client.calkey_write("xtal_trim", 7)

    def test_calkey_write_negative_value_raises(self) -> None:
        client, _ = make_client({})

        with pytest.raises(ValueError, match="negativo"):
            client.calkey_write("xtal_trim", -1)


class TestServiceCommands:
    def test_save_requires_ok(self) -> None:
        client, _ = make_client({"SAVE": ["error: not allowed"]})

        with pytest.raises(CommandRejectedError, match="SAVE"):
            client.save()

    def test_diag_sends_numeric_flag(self) -> None:
        client, transport = make_client({"DIAG 1": ["ok"], "DIAG 0": ["ok"]})

        client.diag(True)
        client.diag(False)

        assert transport.sent == ["DIAG 1", "DIAG 0"]

    def test_setapp_validates_app_name(self) -> None:
        client, _ = make_client({})

        with pytest.raises(ValueError, match="invalida"):
            client.setapp("OTRA")

    def test_setapp_normalizes_to_uppercase(self) -> None:
        client, transport = make_client({"SETAPP NONE": ["ok"]})

        client.setapp("none")

        assert transport.sent == ["SETAPP NONE"]


class TestAppCommands:
    def test_initf_builds_full_command_line(self) -> None:
        command = (
            "INITF -CHAN=9 -PRFSET=BPRF4 -SLOT=2400 -BLOCK=200 -ROUND=25 "
            "-RRU=DSTWR -ID=42 -VUPPER=01:02:03:04:05:06:07:08 -ADDR=0 -PADDR=1"
        )
        client, transport = make_client({command: ["ok"]})

        client.start_initf(
            chan=9,
            prfset="BPRF4",
            slot=2400,
            block=200,
            round=25,
            rru="DSTWR",
            id=42,
            vupper="01:02:03:04:05:06:07:08",
            addr=0,
            paddr=1,
        )

        assert transport.sent == [command]

    def test_respf_without_params(self) -> None:
        client, transport = make_client({"RESPF": ["ok"]})

        client.start_respf()

        assert transport.sent == ["RESPF"]

    def test_invalid_channel_raises_before_sending(self) -> None:
        client, transport = make_client({})

        with pytest.raises(ValueError, match="canal 5 o 9"):
            client.start_initf(chan=7)

        assert transport.sent == []

    def test_unknown_option_raises_before_sending(self) -> None:
        client, transport = make_client({})

        with pytest.raises(ValueError, match="desconocidas"):
            client.start_initf(power=5)

        assert transport.sent == []


class TestNotifications:
    def test_reads_up_to_max_count(self) -> None:
        notifications = [ntf_line(i) for i in range(5)]
        client, _ = make_client({"INITF": ["ok"]}, notifications=notifications)

        measurements = client.read_notifications(max_count=3)

        assert [m.sequence_number for m in measurements] == [0, 1, 2]
        assert all(m.distance_cm == 200 for m in measurements)

    def test_ignores_non_notification_lines(self) -> None:
        client, _ = make_client({}, notifications=["basura", ntf_line(1), "otra basura"])

        measurements = client.read_notifications(max_count=10)

        assert len(measurements) == 1

    def test_requires_a_stop_condition(self) -> None:
        client, _ = make_client({})

        with pytest.raises(ValueError, match="duration_s"):
            client.read_notifications()

    def test_reassembles_multiline_notifications_from_fw110(self) -> None:
        client, _ = make_client(
            {},
            notifications=[
                'SESSION_STATUS_NTF: {state="ACTIVE", reason="State change"}',
                "SESSION_INFO_NTF: {session_handle=1, sequence_number=0, block_index=0,"
                " n_measurements=1",
                '\r [mac_address=0x0001, status="SUCCESS", distance[cm]=19]}',
                "SESSION_INFO_NTF: {session_handle=1, sequence_number=1, block_index=1,"
                " n_measurements=1",
                '\r [mac_address=0x0001, status="SUCCESS", distance[cm]=16]}',
            ],
        )

        measurements = client.read_notifications(max_count=5)

        assert [m.distance_cm for m in measurements] == [19, 16]
        assert all(m.status == "SUCCESS" for m in measurements)

    def test_callback_receives_each_measurement(self) -> None:
        received: list[int] = []
        client, _ = make_client({}, notifications=[ntf_line(4)])

        client.read_notifications(
            max_count=1, on_measurement=lambda m: received.append(m.sequence_number)
        )

        assert received == [4]

    def test_attaches_preceding_diagnostics_to_measurement(self) -> None:
        # Con DIAG 1 activo, RANGE_DIAGNOSTICS_NTF llega antes que la
        # SESSION_INFO_NTF de la misma ronda (ver read_notifications).
        client, _ = make_client(
            {},
            notifications=[
                "RANGE_DIAGNOSTICS_NTF: {n_reports=1",
                "[msg_id=RANGING_RESPONSE, action=RX, antenna_set=0,"
                " frame_status={SUCCESS: 1, WIFI_COEX: 1, GRANT_DURATION_EXCEEDED: 0},"
                " cfo_present=0, nb_aoa=0]}",
                ntf_line(0),
            ],
        )

        measurements = client.read_notifications(max_count=1)

        assert len(measurements) == 1
        diagnostics = measurements[0].diagnostics
        assert diagnostics is not None
        assert diagnostics.any_wifi_coex is True

    def test_measurement_without_diag_has_no_diagnostics(self) -> None:
        client, _ = make_client({}, notifications=[ntf_line(0)])

        measurements = client.read_notifications(max_count=1)

        assert measurements[0].diagnostics is None

    def test_unparseable_diagnostics_block_does_not_block_measurement(self) -> None:
        client, _ = make_client(
            {},
            notifications=[
                "RANGE_DIAGNOSTICS_NTF: {n_reports=0}",
                ntf_line(0),
            ],
        )

        measurements = client.read_notifications(max_count=1)

        assert len(measurements) == 1
        assert measurements[0].diagnostics is None
