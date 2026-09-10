"""Parsers de las salidas del firmware CLI del Qorvo.

Portado de `dwm3001c_cli.core.parsers` (repo hermano
`i-mop-qorvo-CLI-script`, commit ad7079aab0d32b603b4f83ce8be9ac5ce49bd0bd)
— ver docs/arquitectura.md decision D1 y docs/protocolo-ble-qorvo.md.

Funciones puras: reciben lineas de texto crudas y devuelven modelos
tipados. Ante entrada no reconocible lanzan `ValueError` con la linea
ofensiva; la capa superior decide como tratarlo.
"""

import json
import re
from typing import Any

from imop_measure.core.models import (
    CalKey,
    ChipId,
    DeviceInfo,
    Measurement,
    RangeDiagnosticReport,
    RangeDiagnostics,
)

# Prefijo del bloque JSON de STAT: "JS" + longitud en 4 digitos hex + "{...".
# Sin ancla "^": el eco del comando puede llegar pegado sin separador
# delante del bloque (verificado con hardware real, fw 1.1.0).
_JS_PREFIX_RE = re.compile(r"JS[0-9A-Fa-f]{4}(?=\{)")
_MODE_RE = re.compile(r"^MODE:\s*(\S+)")

# "clave: 0xVALOR (len: N)" — claves con puntos y underscores (ej. ant0.ch9.ant_delay).
_CALKEY_RE = re.compile(r"^\s*([A-Za-z0-9_.]+):\s*0x([0-9A-Fa-f]+)\s*\(len:\s*(\d+)\)\s*$")

_SESSION_PREFIX = "SESSION_INFO_NTF"
_SESSION_FIELDS = {
    "sequence_number": re.compile(r"sequence_number=(\d+)"),
    "block_index": re.compile(r"block_index=(\d+)"),
    "mac_address": re.compile(r"mac_address=(0x[0-9A-Fa-f]+)"),
    "status": re.compile(r'status="([^"]*)"'),
    "distance_cm": re.compile(r"distance\[cm\]=(-?\d+)"),
    "rssi_dbm": re.compile(r"RSSI\[dBm\]=(-?\d+(?:\.\d+)?)"),
}

# Prefijo de la notificacion de diagnostico por ronda (requiere `DIAG 1`
# activo, ver `DwmCliClient.diag`). Un bloque trae varios reportes, uno por
# mensaje del intercambio DS-TWR — verificado contra hardware real
# 2026-09-10 (fw 1.1.0, `n_reports=6`: CONTROL, RANGING_INITIATION,
# RANGING_RESPONSE, RANGING_FINAL, MEASUREMENT_REPORT, RESULT_REPORT).
_RANGE_DIAG_PREFIX = "RANGE_DIAGNOSTICS_NTF"
_DIAG_REPORT_RE = re.compile(
    r"msg_id=(?P<msg_id>\w+),\s*action=(?P<action>\w+),\s*antenna_set=\d+,\s*"
    r"frame_status=\{SUCCESS:\s*(?P<success>[01]),\s*WIFI_COEX:\s*(?P<coex>[01]),\s*"
    r"GRANT_DURATION_EXCEEDED:\s*(?P<exceeded>[01])\},\s*"
    r"cfo_present=(?P<cfo_present>[01])(?:,\s*cfo_ppm=(?P<cfo_ppm>-?\d+(?:\.\d+)?))?,\s*nb_aoa=\d+"
)

_DECAID_FIELDS = {
    "device_id": re.compile(r"Device ID\s*=\s*(\S+)"),
    "lot_id": re.compile(r"Lot ID\s*=\s*(\S+)"),
    "part_id": re.compile(r"Part ID\s*=\s*(\S+)"),
    "soc_id": re.compile(r"SoC ID\s*=\s*(\S+)"),
}


def is_ok(lines: list[str]) -> bool:
    """Indica si alguna linea es el `ok` con que el firmware confirma un comando."""
    return any(line.strip().lower() == "ok" for line in lines)


def parse_stat(lines: list[str]) -> DeviceInfo:
    """Parsea la salida de `STAT`.

    Tolera ambas variantes conocidas:

    - Manual: linea `MODE: NONE` seguida del bloque `JSxxxx{...}`.
    - Firmware 1.1.0 real: sin linea `MODE:`, JSON partido en varias
      lineas y `ok` final; el modo se deriva de `Current App`.
    """
    raw = "\n".join(lines)
    mode: str | None = None
    js_start: int | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if (match := _MODE_RE.match(stripped)) is not None:
            mode = match.group(1)
        if js_start is None and _JS_PREFIX_RE.search(stripped) is not None:
            js_start = index
    if js_start is None:
        raise ValueError(f"Salida de STAT sin bloque JSxxxx: {raw!r}")

    joined = "".join(line.strip() for line in lines[js_start:])
    js_match = _JS_PREFIX_RE.search(joined)
    assert js_match is not None  # ya lo encontramos linea por linea arriba
    json_text = joined[js_match.end() :]
    try:
        decoded, _ = json.JSONDecoder().raw_decode(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON de STAT invalido: {json_text!r}") from exc
    if not isinstance(decoded, dict) or not isinstance(decoded.get("Info"), dict):
        raise ValueError(f"STAT sin objeto 'Info': {json_text!r}")
    info: dict[str, Any] = decoded["Info"]

    def field(key: str) -> str:
        value = info.get(key, "")
        return value if isinstance(value, str) else str(value)

    apps_value = info.get("Apps", [])
    apps = tuple(str(app) for app in apps_value) if isinstance(apps_value, list) else ()

    current_app = field("Current App")
    if mode is None:
        # Firmware 1.1.0: sin linea MODE; con app detenida "Current App" es "NONE".
        mode = current_app
    if not mode:
        raise ValueError(f"STAT sin modo ni 'Current App': {raw!r}")

    return DeviceInfo(
        mode=mode,
        device=field("Device"),
        current_app=current_app,
        version=field("Version"),
        build=field("Build"),
        apps=apps,
        driver=field("Driver"),
        uwb_stack=field("UWB stack"),
        raw=raw,
    )


def parse_calkey_line(line: str) -> CalKey:
    """Parsea una linea `clave: 0xVALOR (len: N)` de `CALKEY`/`LISTCAL`."""
    match = _CALKEY_RE.match(line)
    if match is None:
        raise ValueError(f"Linea de clave de calibracion no reconocida: {line!r}")
    return CalKey(
        name=match.group(1),
        value=int(match.group(2), 16),
        length_bytes=int(match.group(3)),
        raw=line,
    )


def parse_listcal(lines: list[str]) -> dict[str, CalKey]:
    """Parsea la salida de `LISTCAL` en un mapa nombre -> clave.

    Ignora lineas vacias, el eco del comando (una sola palabra en
    mayusculas) y el `ok` final. Cualquier otra linea no reconocida es un
    error.
    """
    keys: dict[str, CalKey] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.lower() == "ok" or stripped.isupper():
            continue
        cal_key = parse_calkey_line(line)
        keys[cal_key.name] = cal_key
    return keys


def parse_session_info(line: str) -> Measurement:
    """Parsea una notificacion `SESSION_INFO_NTF`.

    `distance_cm` y `rssi_dbm` son opcionales; el resto de los campos es
    obligatorio y su ausencia es un error.
    """
    if not line.strip().startswith(_SESSION_PREFIX):
        raise ValueError(f"No es una notificacion {_SESSION_PREFIX}: {line!r}")

    values: dict[str, str | None] = {
        name: (match.group(1) if (match := pattern.search(line)) else None)
        for name, pattern in _SESSION_FIELDS.items()
    }
    for required in ("sequence_number", "block_index", "mac_address", "status"):
        if values[required] is None:
            raise ValueError(f"{_SESSION_PREFIX} sin campo {required}: {line!r}")

    distance = values["distance_cm"]
    rssi = values["rssi_dbm"]
    return Measurement(
        sequence_number=int(values["sequence_number"] or 0),
        block_index=int(values["block_index"] or 0),
        mac_address=values["mac_address"] or "",
        status=values["status"] or "",
        distance_cm=int(distance) if distance is not None else None,
        rssi_dbm=float(rssi) if rssi is not None else None,
        raw=line,
    )


def parse_range_diagnostics(text: str) -> RangeDiagnostics:
    """Parsea una notificacion `RANGE_DIAGNOSTICS_NTF` (requiere `DIAG 1`).

    [Por verificar en hardware]: el bloque no trae numero de
    secuencia/ronda propio, asi que la asociacion con la `SESSION_INFO_NTF`
    de la misma ronda es por orden de llegada — ver
    `DwmCliClient.read_notifications`.
    """
    if not text.strip().startswith(_RANGE_DIAG_PREFIX):
        raise ValueError(f"No es una notificacion {_RANGE_DIAG_PREFIX}: {text!r}")
    reports = tuple(
        RangeDiagnosticReport(
            msg_id=match.group("msg_id"),
            action=match.group("action"),
            frame_success=match.group("success") == "1",
            wifi_coex=match.group("coex") == "1",
            grant_duration_exceeded=match.group("exceeded") == "1",
            cfo_present=match.group("cfo_present") == "1",
            cfo_ppm=float(match.group("cfo_ppm")) if match.group("cfo_ppm") is not None else None,
            raw=match.group(0),
        )
        for match in _DIAG_REPORT_RE.finditer(text)
    )
    if not reports:
        raise ValueError(f"{_RANGE_DIAG_PREFIX} sin reportes reconocibles: {text!r}")
    return RangeDiagnostics(reports=reports, raw=text)


def parse_decaid(lines: list[str]) -> ChipId:
    """Parsea la salida de `DECAID`."""
    text = "\n".join(lines)
    values: dict[str, str] = {}
    for name, pattern in _DECAID_FIELDS.items():
        match = pattern.search(text)
        if match is None:
            raise ValueError(f"Salida de DECAID sin campo {name}: {text!r}")
        values[name] = match.group(1)
    return ChipId(**values)
