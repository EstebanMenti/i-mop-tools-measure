"""Jerarquia de excepciones propia del proyecto.

Toda excepcion de dominio hereda de `MeasureError` (CLAUDE.md seccion 2).
Las excepciones de transporte/protocolo estan portadas de
`dwm3001c_cli.core.errors` (repo hermano `i-mop-qorvo-CLI-script`, commit
ad7079aab0d32b603b4f83ce8be9ac5ce49bd0bd) — ver docs/arquitectura.md
decision D1.
"""


class MeasureError(Exception):
    """Raiz de toda excepcion de dominio de imop_measure."""


class ConfigError(MeasureError):
    """El archivo de ambiente (environments/sala_XX.toml) es invalido."""


class TransportError(MeasureError):
    """Falla de la capa de transporte BLE.

    Ejemplos: no se pudo conectar, el nodo se desconecto durante una
    operacion, o timeout esperando una operacion BLE.
    """


class CommandTimeoutError(MeasureError):
    """El firmware no respondio ninguna linea dentro del tiempo esperado."""

    def __init__(self, port: str, command: str, timeout_s: float) -> None:
        super().__init__(
            f"Sin respuesta de {port} al comando {command!r} tras {timeout_s:.1f} s de espera"
        )
        self.port = port
        self.command = command
        self.timeout_s = timeout_s


class CommandRejectedError(MeasureError):
    """El firmware respondio con error, o sin ``ok`` cuando se esperaba ``ok``."""


class UnexpectedModeError(MeasureError):
    """El dispositivo no esta en el modo requerido para la operacion.

    Caso tipico: un comando de servicio/IDLE exige modo NONE y el
    dispositivo no llego a NONE tras enviar ``STOP``.
    """


class DeviceDiscoveryError(MeasureError):
    """No se encontro el nodo (direccion BLE invalida o fuera de alcance)."""
