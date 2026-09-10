"""Modelos de datos tipados del protocolo Qorvo.

Portado de `dwm3001c_cli.core.models` (repo hermano
`i-mop-qorvo-CLI-script`, commit ad7079aab0d32b603b4f83ce8be9ac5ce49bd0bd)
— ver docs/arquitectura.md decision D1. Dataclasses inmutables que
representan las respuestas parseadas del firmware CLI; todas conservan la
entrada cruda (`raw`) cuando aplica, para diagnostico.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceInfo:
    """Informacion reportada por `STAT`.

    `mode` se toma de la linea `MODE:` si el firmware la emite; si no
    (caso del firmware 1.1.0 real), se deriva del campo `Current App`.
    """

    mode: str
    device: str
    current_app: str
    version: str
    build: str
    apps: tuple[str, ...]
    driver: str
    uwb_stack: str
    raw: str


@dataclass(frozen=True)
class CalKey:
    """Una clave de calibracion, segun la salida de `CALKEY`/`LISTCAL`."""

    name: str
    value: int
    length_bytes: int
    raw: str


@dataclass(frozen=True)
class RangeDiagnosticReport:
    """Un reporte de una notificacion `RANGE_DIAGNOSTICS_NTF` (requiere
    `DIAG 1` activo) sobre un mensaje puntual del intercambio DS-TWR de una
    ronda de ranging (ej. `RANGING_RESPONSE`, `RANGING_FINAL`).

    `wifi_coex` y `grant_duration_exceeded` en `True` indican un problema a
    nivel radio/protocolo (interferencia de coexistencia con WiFi, o un
    problema de scheduling), no un problema de propagacion geometrica
    (NLOS) — ver docs/protocolo-ble-qorvo.md.
    """

    msg_id: str
    action: str
    frame_success: bool
    wifi_coex: bool
    grant_duration_exceeded: bool
    cfo_present: bool
    cfo_ppm: float | None
    raw: str


@dataclass(frozen=True)
class RangeDiagnostics:
    """Diagnostico completo de una ronda de ranging (`RANGE_DIAGNOSTICS_NTF`,
    requiere `DIAG 1` activo): un `RangeDiagnosticReport` por mensaje del
    intercambio DS-TWR (`CONTROL`, `RANGING_INITIATION`, `RANGING_RESPONSE`,
    `RANGING_FINAL`, `MEASUREMENT_REPORT`, `RESULT_REPORT` — orden y
    cantidad verificados contra hardware real 2026-09-10, pero no fijos: se
    parsean todos los reportes presentes en el bloque).
    """

    reports: tuple[RangeDiagnosticReport, ...]
    raw: str

    @property
    def any_wifi_coex(self) -> bool:
        """Si algun mensaje de la ronda reporto interferencia de coexistencia WiFi."""
        return any(report.wifi_coex for report in self.reports)

    @property
    def any_grant_duration_exceeded(self) -> bool:
        """Si algun mensaje de la ronda reporto un problema de scheduling."""
        return any(report.grant_duration_exceeded for report in self.reports)


@dataclass(frozen=True)
class Measurement:
    """Una medicion de una notificacion `SESSION_INFO_NTF`.

    `distance_cm` y `rssi_dbm` pueden faltar: la distancia no se reporta
    si la ronda fallo, y el RSSI solo aparece con `DIAG 1` habilitado.

    `diagnostics` acompaña la medicion con el `RangeDiagnostics` de la
    misma ronda cuando `DIAG 1` esta activo (ver
    `DwmCliClient.read_notifications`); `None` si DIAG esta apagado o no
    llego un `RANGE_DIAGNOSTICS_NTF` para esta ronda. El firmware no incluye
    numero de secuencia/ronda en `RANGE_DIAGNOSTICS_NTF`
    [Por verificar en hardware], asi que la asociacion es por orden de
    llegada (la notificacion de diagnostico de una ronda llega antes que su
    `SESSION_INFO_NTF`, verificado contra hardware real 2026-09-10).
    """

    sequence_number: int
    block_index: int
    mac_address: str
    status: str
    distance_cm: int | None
    rssi_dbm: float | None
    raw: str
    diagnostics: RangeDiagnostics | None = None


@dataclass(frozen=True)
class RangingStats:
    """Estadisticas de un lote de mediciones TWR."""

    n_requested: int
    n_received: int
    n_success: int
    mean_cm: float
    std_cm: float
    min_cm: int
    max_cm: int


@dataclass(frozen=True)
class ChipId:
    """Identificacion del chip UWB reportada por `DECAID`."""

    device_id: str
    lot_id: str
    part_id: str
    soc_id: str
