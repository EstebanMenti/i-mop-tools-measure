"""Tests de imop_measure.geometry — no requieren hardware."""

import math
from pathlib import Path

import pytest

from imop_measure.config.loader import load_ambiente
from imop_measure.config.models import Anchor
from imop_measure.geometry.distance import euclidean_distance
from imop_measure.geometry.pairs import all_pairs

ENVIRONMENTS_DIR = Path(__file__).resolve().parent.parent / "environments"


def _anchor(key: str, posicion: tuple[float, float, float]) -> Anchor:
    return Anchor(
        key=key,
        nombre=key,
        mac="00:00:00:00:00:00",
        uwb_addr="00:00",
        posicion=posicion,
        tiempo_prendido="60s",
    )


def test_euclidean_distance_ejes() -> None:
    a = _anchor("a", (0.0, 0.0, 0.0))
    b = _anchor("b", (3.0, 4.0, 0.0))

    assert euclidean_distance(a, b) == pytest.approx(5.0)


def test_euclidean_distance_es_simetrica() -> None:
    a = _anchor("a", (1.0, 2.0, 3.0))
    b = _anchor("b", (4.0, 6.0, 8.0))

    assert euclidean_distance(a, b) == pytest.approx(euclidean_distance(b, a))


def test_all_pairs_sin_repeticion() -> None:
    anchors = [_anchor(k, (float(i), 0.0, 0.0)) for i, k in enumerate(["a", "b", "c"])]

    pairs = all_pairs(anchors)

    assert len(pairs) == 3  # C(3,2)
    pair_keys = {frozenset((p[0].key, p[1].key)) for p in pairs}
    assert pair_keys == {
        frozenset({"a", "b"}),
        frozenset({"a", "c"}),
        frozenset({"b", "c"}),
    }


def test_all_pairs_ambiente_sala_20_real() -> None:
    ambiente = load_ambiente(ENVIRONMENTS_DIR / "sala_20.toml")
    n = len(ambiente.anchors)

    pairs = all_pairs(ambiente.anchors)

    assert len(pairs) == n * (n - 1) // 2

    node_10 = next(a for a in ambiente.anchors if a.key == "uwb_node_10")
    node_11 = next(a for a in ambiente.anchors if a.key == "uwb_node_11")
    distancia = euclidean_distance(node_10, node_11)

    # Posiciones actuales de sala_20.toml (2026-09-09):
    # node_10 (1, 1, 0) y node_11 (0, 2, 0).
    assert distancia == pytest.approx(math.sqrt(1.0**2 + 1.0**2), abs=1e-3)
