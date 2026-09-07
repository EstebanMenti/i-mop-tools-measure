"""Generacion de pares de anclas para medicion."""

from itertools import combinations

from imop_measure.config.models import Anchor


def all_pairs(anchors: list[Anchor]) -> list[tuple[Anchor, Anchor]]:
    """Todas las combinaciones sin repeticion ni orden entre anclas."""
    return list(combinations(anchors, 2))
