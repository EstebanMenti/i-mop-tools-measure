"""Tests de imop_measure.ranging.addressing — no requieren hardware."""

import pytest

from imop_measure.errors import ConfigError
from imop_measure.ranging.addressing import uwb_addr_to_int


@pytest.mark.parametrize(
    ("uwb_addr", "expected"),
    [
        ("00:02", 2),
        ("0a:ff", 2815),
        ("00:00", 0),
        ("ff:ff", 65535),
    ],
)
def test_uwb_addr_to_int(uwb_addr: str, expected: int) -> None:
    assert uwb_addr_to_int(uwb_addr) == expected


@pytest.mark.parametrize(
    "uwb_addr",
    ["no-es-hex", "00:0Z", "0002", "00:00:02", "00-02", ""],
)
def test_uwb_addr_to_int_formato_invalido(uwb_addr: str) -> None:
    with pytest.raises(ConfigError, match="no respeta el formato"):
        uwb_addr_to_int(uwb_addr)
