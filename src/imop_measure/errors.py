"""Jerarquia de excepciones propia del proyecto.

Ver CLAUDE.md seccion 2: toda excepcion de dominio hereda de `MeasureError`,
analogo a `Dwm3001cError` en el repo hermano `i-mop-qorvo-CLI-script`.
"""


class MeasureError(Exception):
    """Raiz de toda excepcion de dominio de imop_measure."""


class ConfigError(MeasureError):
    """El archivo de ambiente (environments/sala_XX.toml) es invalido."""
