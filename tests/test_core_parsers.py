"""Tests de imop_measure.core.parsers — no requieren hardware.

Casos portados de i-mop-qorvo-CLI-script/tests/test_parsers.py (commit
ad7079aab0d32b603b4f83ce8be9ac5ce49bd0bd), con capturas reales de
firmware 1.1.0.
"""

from pathlib import Path

import pytest

from imop_measure.core.parsers import (
    is_ok,
    parse_calkey_line,
    parse_decaid,
    parse_listcal,
    parse_range_diagnostics,
    parse_session_info,
    parse_stat,
)

FIXTURES = Path(__file__).parent / "fixtures"
STAT_REAL = (FIXTURES / "stat_fw110_real.txt").read_text(encoding="utf-8").splitlines()
RANGE_DIAGNOSTICS_REAL_LINES = (
    (FIXTURES / "range_diagnostics_ntf_fw110_real.txt").read_text(encoding="utf-8").splitlines()
)


def test_is_ok_true_when_ok_present() -> None:
    assert is_ok(["algo", "ok"]) is True


def test_is_ok_false_without_ok() -> None:
    assert is_ok(["algo", "KO"]) is False


def test_parse_stat_real_capture() -> None:
    info = parse_stat(STAT_REAL)

    assert info.mode == "NONE"
    assert info.current_app == "NONE"
    assert info.version == "1.1.0"
    assert info.device == "DWM3001CDK - DW3_QM33_SDK - FreeRTOS"
    assert info.apps == ("LISTENER", "RESPF", "INITF")


def test_parse_stat_derives_mode_from_current_app_without_mode_line() -> None:
    lines = [
        'JS0080{"Info":{"Device":"X","Current App":"INITF","Version":"1.1.0",'
        '"Build":"B","Apps":["LISTENER","RESPF","INITF"],"Driver":"D","UWB stack":"S"}}',
        "ok",
    ]

    info = parse_stat(lines)

    assert info.mode == "INITF"


def test_parse_stat_tolerates_echo_glued_without_separator() -> None:
    lines = ['STAT\rJS0109{"Info":{"Device":"X","Current App":"NONE"}}', "ok"]

    info = parse_stat(lines)

    assert info.mode == "NONE"


def test_parse_stat_missing_json_block_raises() -> None:
    with pytest.raises(ValueError, match="JSxxxx"):
        parse_stat(["ok"])


def test_parse_calkey_line() -> None:
    cal_key = parse_calkey_line("ant0.ch9.ant_delay: 0x4015 (len: 4)")

    assert cal_key.name == "ant0.ch9.ant_delay"
    assert cal_key.value == 0x4015
    assert cal_key.length_bytes == 4


def test_parse_listcal_ignores_echo_and_ok() -> None:
    keys = parse_listcal(["LISTCAL", "xtal_trim: 0x32 (len: 1)", "", "ok"])

    assert keys["xtal_trim"].value == 0x32
    assert len(keys) == 1


def test_parse_session_info_success() -> None:
    line = (
        "SESSION_INFO_NTF: {session_handle=1, sequence_number=0, block_index=0,"
        ' n_measurements=1 [mac_address=0x0001, status="SUCCESS", distance[cm]=210,'
        " RSSI[dBm]=-78.0]}"
    )

    measurements = parse_session_info(line)

    assert len(measurements) == 1
    measurement = measurements[0]
    assert measurement.status == "SUCCESS"
    assert measurement.distance_cm == 210
    assert measurement.rssi_dbm == pytest.approx(-78.0)
    assert measurement.mac_address == "0x0001"


def test_parse_session_info_failure_has_no_distance() -> None:
    line = (
        "SESSION_INFO_NTF: {session_handle=1, sequence_number=3, block_index=3,"
        ' n_measurements=1 [mac_address=0x0001, status="RX_TIMEOUT"]}'
    )

    measurements = parse_session_info(line)

    assert len(measurements) == 1
    assert measurements[0].status == "RX_TIMEOUT"
    assert measurements[0].distance_cm is None


def test_parse_session_info_one_to_many_returns_one_measurement_per_responder() -> None:
    # Capturado contra hardware real 2026-09-10 (UWB-Node-4 iniciador con
    # -MULTI, UWB-Node-6/UWB-Node-8 respondedores con -MULTI cada uno).
    line = (
        "SESSION_INFO_NTF: {session_handle=1, sequence_number=40, block_index=40,"
        ' n_measurements=2 [mac_address=0x0006, status="SUCCESS", distance[cm]=2];'
        ' [mac_address=0x0008, status="SUCCESS", distance[cm]=19]}'
    )

    measurements = parse_session_info(line)

    assert len(measurements) == 2
    assert [m.mac_address for m in measurements] == ["0x0006", "0x0008"]
    assert [m.distance_cm for m in measurements] == [2, 19]
    assert all(m.sequence_number == 40 and m.block_index == 40 for m in measurements)


def test_parse_session_info_one_to_many_mixed_success_and_timeout() -> None:
    # Tambien capturado contra hardware real: un respondedor puede fallar
    # su ronda mientras el otro mide bien, dentro de la misma notificacion.
    line = (
        "SESSION_INFO_NTF: {session_handle=1, sequence_number=50, block_index=50,"
        ' n_measurements=2 [mac_address=0x0006, status="RX_TIMEOUT"];'
        ' [mac_address=0x0008, status="SUCCESS", distance[cm]=19]}'
    )

    measurements = parse_session_info(line)

    assert len(measurements) == 2
    assert measurements[0].status == "RX_TIMEOUT"
    assert measurements[0].distance_cm is None
    assert measurements[1].status == "SUCCESS"
    assert measurements[1].distance_cm == 19


def test_parse_session_info_rejects_non_notification() -> None:
    with pytest.raises(ValueError, match="No es una notificacion"):
        parse_session_info("algo random")


def test_parse_range_diagnostics_real_capture() -> None:
    # Capturado contra hardware real 2026-09-10 (N8 iniciador -> N10
    # respondedor, DIAG 1 activo) — mismo formato de reensamblado que
    # DwmCliClient.read_notifications (lineas no vacias unidas con " ").
    joined = " ".join(line.strip() for line in RANGE_DIAGNOSTICS_REAL_LINES if line.strip())

    diagnostics = parse_range_diagnostics(joined)

    assert len(diagnostics.reports) == 6
    assert [r.msg_id for r in diagnostics.reports] == [
        "CONTROL",
        "RANGING_INITIATION",
        "RANGING_RESPONSE",
        "RANGING_FINAL",
        "MEASUREMENT_REPORT",
        "RESULT_REPORT",
    ]
    assert diagnostics.any_wifi_coex is False
    assert diagnostics.any_grant_duration_exceeded is False
    ranging_response = diagnostics.reports[2]
    assert ranging_response.action == "RX"
    assert ranging_response.frame_success is True
    assert ranging_response.cfo_present is True
    assert ranging_response.cfo_ppm == pytest.approx(-1.17)
    control = diagnostics.reports[0]
    assert control.cfo_present is False
    assert control.cfo_ppm is None


def test_parse_range_diagnostics_detects_wifi_coex() -> None:
    text = (
        "RANGE_DIAGNOSTICS_NTF: {n_reports=1 "
        "[msg_id=RANGING_RESPONSE, action=RX, antenna_set=0, "
        "frame_status={SUCCESS: 1, WIFI_COEX: 1, GRANT_DURATION_EXCEEDED: 0}, "
        "cfo_present=0, nb_aoa=0]}"
    )

    diagnostics = parse_range_diagnostics(text)

    assert diagnostics.any_wifi_coex is True
    assert diagnostics.any_grant_duration_exceeded is False


def test_parse_range_diagnostics_rejects_non_notification() -> None:
    with pytest.raises(ValueError, match="No es una notificacion"):
        parse_range_diagnostics("algo random")


def test_parse_range_diagnostics_rejects_block_without_reports() -> None:
    with pytest.raises(ValueError, match="sin reportes reconocibles"):
        parse_range_diagnostics("RANGE_DIAGNOSTICS_NTF: {n_reports=0}")


def test_parse_decaid() -> None:
    chip_id = parse_decaid(
        [
            "Qorvo Device ID = 0xdeca0304",
            "Qorvo Lot ID    = 0x0000503639463438",
            "Qorvo Part ID   = 0x8124d5b7",
            "Qorvo SoC ID    = 00005036394634388124d5b7",
            "ok",
        ]
    )

    assert chip_id.device_id == "0xdeca0304"
