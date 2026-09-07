"""Calculo de distancia euclidea entre anclas."""

import math

from imop_measure.config.models import Anchor


def euclidean_distance(a: Anchor, b: Anchor) -> float:
    """Distancia euclidea 3D entre las posiciones de dos anclas, en metros."""
    ax, ay, az = a.posicion
    bx, by, bz = b.posicion
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2)
