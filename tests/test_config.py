"""Tests de imop_measure.config — no requieren hardware."""

from pathlib import Path

import pytest

from imop_measure.config.loader import load_ambiente
from imop_measure.errors import ConfigError

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

_VALID_TOML = """
[sala]
id = "99"

[[anchors]]
key = "a"
nombre = "A"
mac = "00:00:00:00:00:01"
uwb_addr = "00:01"
posicion = [0.0, 0.0, 0.0]
tiempo_prendido = "60s"

[[anchors]]
key = "b"
nombre = "B"
mac = "00:00:00:00:00:02"
uwb_addr = "00:02"
posicion = [1.0, 0.0, 0.0]
tiempo_prendido = "60s"
"""


def test_load_ambiente_ejemplo_real() -> None:
    """Parsea `tests/fixtures/sala_ejemplo.toml`, un ambiente "real" fijo
    (formato completo: dimensiones, anclas, ble_timeouts) — a diferencia de
    `environments/sala_20.toml`, que es un archivo de trabajo que se edita
    sesion a sesion segun que nodos fisicos esten disponibles, este fixture
    nunca cambia, para que este test no dependa del ambiente de turno.
    """
    ambiente = load_ambiente(FIXTURES_DIR / "sala_ejemplo.toml")

    assert ambiente.id == "ejemplo"
    assert {anchor.key for anchor in ambiente.anchors} == {
        "uwb_node_8",
        "uwb_node_10",
        "uwb_node_11",
    }
    assert len(ambiente.anchors) == 3

    node_11 = next(a for a in ambiente.anchors if a.key == "uwb_node_11")
    assert node_11.posicion == pytest.approx((0.0, 2.0, 0.0))
    assert node_11.uwb_addr == "00:11"
    assert node_11.mac == "E5:A2:2C:DB:14:B9"

    assert ambiente.ble_timeouts["connection_timeout"] == pytest.approx(180.0)
    assert ambiente.ble_timeouts["max_concurrent_connections"] == pytest.approx(5.0)


def test_load_ambiente_valido(tmp_path: Path) -> None:
    toml_path = tmp_path / "sala_99.toml"
    toml_path.write_text(_VALID_TOML, encoding="utf-8")

    ambiente = load_ambiente(toml_path)

    assert ambiente.id == "99"
    assert len(ambiente.anchors) == 2
    assert ambiente.ble_timeouts == {}


def test_id_no_coincide_con_nombre_de_archivo(tmp_path: Path) -> None:
    toml_path = tmp_path / "sala_20.toml"
    toml_path.write_text(_VALID_TOML, encoding="utf-8")  # declara id="99"

    with pytest.raises(ConfigError, match="no coincide con el nombre de archivo"):
        load_ambiente(toml_path)


def test_menos_de_dos_anclas(tmp_path: Path) -> None:
    toml_path = tmp_path / "sala_99.toml"
    toml_path.write_text(
        """
        [sala]
        id = "99"

        [[anchors]]
        key = "a"
        nombre = "A"
        mac = "00:00:00:00:00:01"
        uwb_addr = "00:01"
        posicion = [0.0, 0.0, 0.0]
        tiempo_prendido = "60s"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="al menos 2 anclas"):
        load_ambiente(toml_path)


def test_uwb_addr_mal_formado(tmp_path: Path) -> None:
    toml_path = tmp_path / "sala_99.toml"
    toml_path.write_text(
        _VALID_TOML.replace('uwb_addr = "00:01"', 'uwb_addr = "no-es-hex"'),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="no respeta el formato XX:YY"):
        load_ambiente(toml_path)


def test_claves_de_ancla_duplicadas(tmp_path: Path) -> None:
    toml_path = tmp_path / "sala_99.toml"
    toml_path.write_text(_VALID_TOML.replace('key = "b"', 'key = "a"'), encoding="utf-8")

    with pytest.raises(ConfigError, match="duplicadas"):
        load_ambiente(toml_path)


def test_uwb_addr_duplicado_entre_anclas(tmp_path: Path) -> None:
    """Reproduce el caso real (2026-09-08, uwb_node_11/uwb_node_1 con el
    mismo uwb_addr por un copy-paste sin corregir): colisiona ADDR/PADDR y
    la sesion de ranging falla en silencio (0 muestras). Debe rechazarse
    al cargar el ambiente, no recien durante una campaña.
    """
    toml_path = tmp_path / "sala_99.toml"
    toml_path.write_text(
        _VALID_TOML.replace('uwb_addr = "00:02"', 'uwb_addr = "00:01"'), encoding="utf-8"
    )

    with pytest.raises(ConfigError, match="uwb_addr duplicado"):
        load_ambiente(toml_path)


def test_mac_duplicada_entre_anclas(tmp_path: Path) -> None:
    toml_path = tmp_path / "sala_99.toml"
    toml_path.write_text(
        _VALID_TOML.replace('mac = "00:00:00:00:00:02"', 'mac = "00:00:00:00:00:01"'),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="mac BLE duplicada"):
        load_ambiente(toml_path)


def test_posicion_con_componentes_incorrectos(tmp_path: Path) -> None:
    toml_path = tmp_path / "sala_99.toml"
    toml_path.write_text(
        _VALID_TOML.replace("posicion = [1.0, 0.0, 0.0]", "posicion = [1.0, 0.0]"),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="3 componentes"):
        load_ambiente(toml_path)
