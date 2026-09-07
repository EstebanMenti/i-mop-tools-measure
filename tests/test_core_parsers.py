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
    parse_session_info,
    parse_stat,
)

FIXTURES = Path(__file__).parent / "fixtures"
STAT_REAL = (FIXTURES / "stat_fw110_real.txt").read_text(encoding="utf-8").splitlines()


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

    measurement = parse_session_info(line)

    assert measurement.status == "SUCCESS"
    assert measurement.distance_cm == 210
    assert measurement.rssi_dbm == pytest.approx(-78.0)
    assert measurement.mac_address == "0x0001"


def test_parse_session_info_failure_has_no_distance() -> None:
    line = (
        "SESSION_INFO_NTF: {session_handle=1, sequence_number=3, block_index=3,"
        ' n_measurements=1 [mac_address=0x0001, status="RX_TIMEOUT"]}'
    )

    measurement = parse_session_info(line)

    assert measurement.status == "RX_TIMEOUT"
    assert measurement.distance_cm is None


def test_parse_session_info_rejects_non_notification() -> None:
    with pytest.raises(ValueError, match="No es una notificacion"):
        parse_session_info("algo random")


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
