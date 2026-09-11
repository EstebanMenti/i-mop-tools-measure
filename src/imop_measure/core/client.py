"""Cliente del protocolo CLI del Qorvo (DWM3001C/QM33), via BLE.

Portado de `dwm3001c_cli.core.client` (repo hermano
`i-mop-qorvo-CLI-script`, commit ad7079aab0d32b603b4f83ce8be9ac5ce49bd0bd)
— ver docs/arquitectura.md decision D1 y docs/protocolo-ble-qorvo.md.

`DwmCliClient` coordina el envio de comandos y la interpretacion de las
respuestas sobre un `Transport` ya construido. No conoce Typer/Rich (regla
de arquitectura, ver docs/arquitectura.md decision D2) ni abre transportes
por su cuenta.

Comportamientos del firmware contemplados:

- El nodo hace **eco** del comando enviado; se descarta.
- Las respuestas de comandos terminan con una linea `ok`; se usa como
  marcador de fin, con un periodo de silencio como respaldo.
- Los comandos de servicio e IDLE solo funcionan en modo NONE — usar
  `DwmCliClient.ensure_mode_none` antes de invocarlos.
"""

import logging
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import replace

from imop_measure.core.models import CalKey, ChipId, DeviceInfo, Measurement, RangeDiagnostics
from imop_measure.core.parsers import (
    is_ok,
    parse_calkey_line,
    parse_decaid,
    parse_listcal,
    parse_range_diagnostics,
    parse_session_info,
    parse_stat,
)
from imop_measure.errors import (
    CommandRejectedError,
    CommandTimeoutError,
    UnexpectedModeError,
)
from imop_measure.transport.base import Transport

logger = logging.getLogger(__name__)

_VALID_APPS = {"LISTENER", "INITF", "RESPF", "NONE"}

# Vocabulario cerrado de comandos de la CLI (Developer Manual / guia §1.1).
# Usado por send_command para reconocer, cuando la primera linea de una
# respuesta no es el eco del comando propio, si en cambio es el eco de OTRO
# comando de este vocabulario: senal de que todo el bloque es la respuesta
# rezagada de un comando distinto (backlog), no la respuesta del que se acaba
# de enviar (ver nota "puente BLE" en send_command). Portado del repo hermano
# (commits f289ff1 y a67f924, verificados contra hardware real).
_CLI_COMMAND_WORDS = {
    "HELP",
    "STAT",
    "STOP",
    "THREAD",
    "RESTORE",
    "LCFG",
    "DIAG",
    "DECAID",
    "SAVE",
    "SETAPP",
    "GETOTP",
    "UART",
    "CALKEY",
    "LISTCAL",
    "INITF",
    "RESPF",
    "LISTENER",
}

# Tras STOP, el firmware tarda un instante en volver a NONE: un STAT
# inmediato aun reporta la app anterior corriendo.
_STOP_SETTLE_S = 0.3

# Prefijos de notificacion reconocidos en el canal de stream (ver
# read_notifications). RANGE_DIAGNOSTICS_NTF solo llega con DIAG 1 activo
# y, verificado contra hardware real 2026-09-10, precede a la
# SESSION_INFO_NTF de la misma ronda (no trae numero de ronda propio).
_SESSION_NTF_PREFIX = "SESSION_INFO_NTF"
_RANGE_DIAG_NTF_PREFIX = "RANGE_DIAGNOSTICS_NTF"
# Un bloque RANGE_DIAGNOSTICS_NTF (6 reportes en la practica) ocupa muchas
# mas lineas de fragmento que un SESSION_INFO_NTF — margen generoso para no
# descartarlo como "inconcluso" antes de tiempo.
_MAX_FRAGMENT_LINES = 40
_PRFSETS = {"BPRF3", "BPRF4", "BPRF5", "BPRF6"}
_RRUS = {"SSTWR", "DSTWR", "SSTWRNDEF", "DSTWRNDEF"}
_VUPPER_RE = re.compile(r"^([0-9A-Fa-f]{2}:){7}[0-9A-Fa-f]{2}$")

# Orden canonico de emision de opciones de INITF/RESPF.
_OPTION_ORDER = (
    "chan",
    "prfset",
    "pcode",
    "slot",
    "block",
    "round",
    "rru",
    "id",
    "vupper",
    "multi",
    "hop",
    "addr",
    "paddr",
)


def _as_int(name: str, value: object, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError(f"Opcion {name!r}: se espera un entero entre {lo} y {hi}; llego {value!r}")
    return value


def _format_app_options(params: Mapping[str, object]) -> list[str]:
    """Valida y formatea las opciones de INITF/RESPF como `-OPCION=VALOR`.

    Cualquier opcion fuera de la lista conocida, o valor fuera de rango,
    es `ValueError` — nunca se envia al nodo un comando dudoso.
    """
    unknown = set(params) - set(_OPTION_ORDER)
    if unknown:
        raise ValueError(f"Opciones desconocidas: {sorted(unknown)}; validas: {_OPTION_ORDER}")

    parts: list[str] = []
    for name in _OPTION_ORDER:
        if name not in params:
            continue
        value = params[name]
        if name == "chan":
            channel = _as_int(name, value, 5, 9)
            if channel not in (5, 9):
                raise ValueError(f"Opcion 'chan': solo canal 5 o 9; llego {channel}")
            parts.append(f"-CHAN={channel}")
        elif name == "prfset":
            prfset = str(value).upper()
            if prfset not in _PRFSETS:
                raise ValueError(f"Opcion 'prfset': validos {sorted(_PRFSETS)}; llego {value!r}")
            parts.append(f"-PRFSET={prfset}")
        elif name == "pcode":
            parts.append(f"-PCODE={_as_int(name, value, 9, 12)}")
        elif name == "slot":
            parts.append(f"-SLOT={_as_int(name, value, 2400, 65535)}")
        elif name == "block":
            parts.append(f"-BLOCK={_as_int(name, value, 1, 65535)}")
        elif name == "round":
            parts.append(f"-ROUND={_as_int(name, value, 1, 255)}")
        elif name == "rru":
            rru = str(value).upper()
            if rru not in _RRUS:
                raise ValueError(f"Opcion 'rru': validos {sorted(_RRUS)}; llego {value!r}")
            parts.append(f"-RRU={rru}")
        elif name == "id":
            parts.append(f"-ID={_as_int(name, value, 1, 65535)}")
        elif name == "vupper":
            vupper = str(value)
            if _VUPPER_RE.match(vupper) is None:
                raise ValueError(
                    f"Opcion 'vupper': formato XX:XX:XX:XX:XX:XX:XX:XX en hex; llego {value!r}"
                )
            parts.append(f"-VUPPER={vupper}")
        elif name in ("multi", "hop"):
            if not isinstance(value, bool):
                raise ValueError(f"Opcion {name!r}: se espera bool; llego {value!r}")
            if value:
                parts.append(f"-{name.upper()}")
        elif name == "addr":
            parts.append(f"-ADDR={_as_int(name, value, 0, 65535)}")
        elif name == "paddr":
            # En modo uno-a-muchos (-MULTI) el iniciador acepta una lista de
            # respondedores: -PADDR=[1,2,.,.,n] (verificado contra hardware
            # real 2026-09-10, ver Developer Manual QM33SDK-1.1.1 seccion 7,
            # Listing 7.5). El respondedor sigue usando un unico -PADDR=
            # (la direccion del iniciador) incluso con -MULTI activo.
            if isinstance(value, list):
                if not value:
                    raise ValueError(
                        "Opcion 'paddr': la lista de respondedores no puede estar vacia"
                    )
                addrs = [_as_int("paddr[]", item, 0, 65535) for item in value]
                parts.append(f"-PADDR=[{','.join(str(a) for a in addrs)}]")
            else:
                parts.append(f"-PADDR={_as_int(name, value, 0, 65535)}")
    return parts


class DwmCliClient:
    """Cliente de la consola CLI de un nodo (Qorvo, via el puente BLE).

    Args:
        transport: transporte ya construido (`BleTransport` o fake); el
            cliente no lo abre ni lo cierra.
        command_timeout_s: tiempo maximo por defecto para esperar la
            respuesta de un comando.
        quiet_period_s: periodo de silencio por defecto que marca el fin
            de una respuesta sin `ok`/`KO` explicito (ver `send_command`).
            Por BLE se midieron gaps de ~590ms incluso entre fragmentos de
            una respuesta sana en el repo hermano — usar un valor de al
            menos ~1.5s al construir un cliente sobre `BleTransport`
            (default mas bajo, 0.3s, calibrado para USB/serie directo).
    """

    def __init__(
        self,
        transport: Transport,
        *,
        command_timeout_s: float = 2.0,
        quiet_period_s: float = 0.3,
    ) -> None:
        self._transport = transport
        self._command_timeout_s = command_timeout_s
        self._quiet_period_s = quiet_period_s

    @property
    def name(self) -> str:
        return self._transport.name

    # ------------------------------------------------------------------ basicos

    def send_command(
        self,
        cmd: str,
        *,
        quiet_period_s: float | None = None,
        timeout_s: float | None = None,
    ) -> list[str]:
        """Envia un comando y recolecta su respuesta completa.

        Fin de respuesta: linea `ok` (marcador del firmware) o
        `quiet_period_s` sin lineas nuevas tras haber recibido algo. El
        eco del comando se descarta.

        [Verificado 2026-09-09, hardware real, puente BLE con firmware >= 0.3.0]
        Durante una sesion de ranging activa, la ventana de relay de
        `qorvo <cmd>` captura igual la salida del UART del Qorvo: un `STAT`
        de keepalive puede recibir decenas de notificaciones
        `SESSION_INFO_NTF` (con o sin su propia respuesta detras). Antes de
        este fix ese backlog se devolvia como si fuera la respuesta del
        comando y rompia el parseo (`Salida de STAT sin bloque JSxxxx`).
        Ahora, para el corte por `ok`/`ko`: se revisa **cada** linea (no
        solo la primera) buscando el eco de **otro** comando del vocabulario
        cerrado de la CLI (`_CLI_COMMAND_WORDS`) — si aparece, todo el
        bloque se trata como backlog rezagado y se descarta. Para el corte
        por silencio (sin `ok`/`ko`): si el bloque empieza con
        `SESSION_INFO_NTF` y nunca se vio el eco propio, tambien se descarta
        y se sigue esperando, sin exceder `timeout_s` — un timeout franco
        en vez de un dato silenciosamente incorrecto. No se aplica a
        respuestas que no parecen notificaciones (p. ej. un rechazo de SAVE
        sin eco: `"error: not allowed"`), que si deben aceptarse tal cual.
        Portado del repo hermano (commits f289ff1 y a67f924).

        Raises:
            CommandTimeoutError: si no llego ninguna linea dentro del timeout.
        """
        limit = timeout_s if timeout_s is not None else self._command_timeout_s
        quiet_period_s = quiet_period_s if quiet_period_s is not None else self._quiet_period_s
        cmd_upper = cmd.strip().upper()
        own_word = cmd_upper.split(maxsplit=1)[0] if cmd_upper else ""
        self._transport.write_line(cmd)
        deadline = time.monotonic() + limit
        lines: list[str] = []
        received_any = False
        own_echo_seen = False
        foreign_echo = False
        foreign_word = ""
        first_line_pending = True
        notification_backlog = False
        while True:
            if time.monotonic() >= deadline:
                raise CommandTimeoutError(self.name, cmd, limit)
            line = self._transport.read_line(quiet_period_s)
            if line is None:
                if received_any:
                    if own_echo_seen or not notification_backlog:
                        break
                    # Silencio tras recibir *algo* que empieza como backlog
                    # de notificaciones y sin haber visto nunca el eco propio
                    # (ni un ok/ko, que ya habria cortado antes): es backlog
                    # de notificaciones, no la respuesta del comando — se
                    # descarta y se sigue esperando la respuesta real.
                    logger.warning(
                        "%s: se descarto una respuesta sin eco propio de %r "
                        "(silencio, backlog de notificaciones): %r",
                        self.name,
                        cmd,
                        lines,
                    )
                    lines = []
                    received_any = False
                    foreign_echo = False
                    foreign_word = ""
                    first_line_pending = True
                    notification_backlog = False
                continue
            stripped = line.strip()
            if stripped == "":
                # Linea vacia (frecuente como residuo entre comandos): se
                # ignora sin contar para el timeout ni para el eco.
                continue
            received_any = True
            if first_line_pending:
                first_line_pending = False
                notification_backlog = stripped.startswith("SESSION_INFO_NTF")
            if not own_echo_seen and not foreign_echo:
                # Exige que la linea sea *solo* la palabra del comando (eco
                # verdadero de un comando sin parametros): contenido real que
                # meramente empieza con el nombre de un comando (p. ej. el
                # listado de "HELP": "STAT - report status") siempre trae
                # texto pegado a continuacion y no debe confundirse con un
                # eco ajeno. Se revisa en **cada** linea, no solo la primera:
                # notificaciones SESSION_INFO_NTF acumuladas pueden preceder
                # por decenas de lineas al eco ajeno que delata el backlog.
                candidate = stripped.upper()
                if candidate != own_word and candidate in _CLI_COMMAND_WORDS:
                    foreign_echo = True
                    foreign_word = candidate
            if not own_echo_seen:
                if stripped.upper() == cmd_upper:
                    logger.debug("Eco descartado en %s: %s", self.name, line)
                    own_echo_seen = True
                    continue
                after_cmd = (
                    stripped[len(cmd_upper) :] if stripped.upper().startswith(cmd_upper) else None
                )
                # Eco pegado sin separador solo si justo despues del texto
                # del comando hay un caracter de espacio/control (o nada):
                # si sigue un caracter de contenido (p.ej. ":") no es eco,
                # es respuesta real que empieza igual que el comando
                # (ej. "DIAG" -> "DIAG: 0").
                if after_cmd is not None and (after_cmd == "" or after_cmd[0].isspace()):
                    remainder = after_cmd.lstrip()
                    logger.debug("Eco pegado a la respuesta en %s: %s", self.name, line)
                    own_echo_seen = True
                    if not remainder:
                        continue
                    stripped = remainder
                    line = remainder
            lines.append(line)
            # "ok" y "KO" son los marcadores de fin de respuesta del
            # firmware (exito y error respectivamente).
            if stripped.lower() in ("ok", "ko"):
                if own_echo_seen or not foreign_echo:
                    break
                # El bloque contiene, en alguna linea, el eco de OTRO comando
                # de la CLI: es la respuesta rezagada de ese comando — se
                # descarta y se sigue esperando la respuesta real, sin
                # exceder el timeout.
                logger.warning(
                    "%s: se descarto una respuesta ajena a %r (eco de %r, backlog rezagado): %r",
                    self.name,
                    cmd,
                    foreign_word,
                    lines,
                )
                lines = []
                received_any = False
                foreign_echo = False
                foreign_word = ""
                first_line_pending = True
                notification_backlog = False
        return lines

    # ----------------------------------------------------------- estado y modo

    def stat(self) -> DeviceInfo:
        """`STAT`: informacion y modo actual del dispositivo."""
        return parse_stat(self.send_command("STAT"))

    def stop(self) -> None:
        """`STOP`: detiene la aplicacion en curso; tolera silencio (sin app)."""
        try:
            self.send_command("STOP")
        except CommandTimeoutError:
            logger.debug("STOP sin respuesta en %s (¿ya estaba en NONE?)", self.name)

    def ensure_mode_none(self) -> None:
        """Lleva el dispositivo a modo NONE, requisito de los comandos de servicio.

        Envia `STOP` y verifica con `STAT`; reintenta una vez.

        Raises:
            UnexpectedModeError: si tras dos intentos el modo no es NONE.
        """
        info: DeviceInfo | None = None
        for attempt in range(2):
            self.stop()
            time.sleep(_STOP_SETTLE_S)
            info = self.stat()
            if info.mode == "NONE":
                return
            log = logger.warning if attempt else logger.debug
            log("El dispositivo %s sigue en modo %s tras STOP", self.name, info.mode)
        mode = info.mode if info is not None else "?"
        raise UnexpectedModeError(
            f"{self.name}: el dispositivo reporta modo {mode!r} y se requiere NONE"
        )

    # ------------------------------------------------------------- calibracion

    def listcal(self) -> dict[str, CalKey]:
        """`LISTCAL`: todas las claves de calibracion (requiere modo NONE)."""
        return parse_listcal(self.send_command("LISTCAL", timeout_s=5.0))

    def calkey_read(self, key: str) -> CalKey:
        """`CALKEY <key>`: lee una clave de calibracion (requiere modo NONE).

        En fw 1.1.0 la forma de lectura de `CALKEY` esta rota: responde
        `KO` para cualquier clave, incluso las listadas por `LISTCAL`.
        Como respaldo, la clave se lee filtrando `LISTCAL`.
        """
        lines = self.send_command(f"CALKEY {key}")
        for line in lines:
            try:
                cal_key = parse_calkey_line(line)
            except ValueError:
                continue
            if cal_key.name == key:
                return cal_key
        logger.debug("CALKEY %s sin respuesta directa en %s; leyendo via LISTCAL", key, self.name)
        keys = self.listcal()
        if key in keys:
            return keys[key]
        raise CommandRejectedError(
            f"{self.name}: la clave {key} no existe "
            f"(CALKEY respondio {lines!r} y no figura en LISTCAL)"
        )

    def calkey_write(self, key: str, value: int) -> CalKey:
        """`CALKEY <key> <value>`: escribe y **verifica releyendo**.

        El valor se envia en decimal: el firmware interpreta la entrada
        en decimal (escribir `10` produce `0x0a`).

        Raises:
            CommandRejectedError: si la relectura no coincide con lo escrito.
        """
        if value < 0:
            raise ValueError(f"Valor de clave negativo no soportado: {value}")
        self.send_command(f"CALKEY {key} {value}")
        written = self.calkey_read(key)
        if written.value != value:
            raise CommandRejectedError(
                f"{self.name}: se escribio {key}={value} pero la relectura "
                f"devolvio {written.value} — formato de entrada sospechoso"
            )
        return written

    # ---------------------------------------------------------------- servicio

    def save(self) -> None:
        """`SAVE`: persiste la configuracion en NVM (modo NONE; no durante ranging)."""
        lines = self.send_command("SAVE")
        if not is_ok(lines):
            raise CommandRejectedError(f"{self.name}: SAVE no confirmo ok; respuesta: {lines!r}")

    def diag(self, enable: bool) -> None:
        """`DIAG 0|1`: habilita/deshabilita el modo diagnostico (RSSI en ranging)."""
        lines = self.send_command(f"DIAG {int(enable)}")
        if not is_ok(lines):
            raise CommandRejectedError(f"{self.name}: DIAG no confirmo ok; respuesta: {lines!r}")

    def setapp(self, app: str) -> None:
        """`SETAPP`: define la aplicacion por defecto tras reboot (requiere SAVE)."""
        normalized = app.upper()
        if normalized not in _VALID_APPS:
            raise ValueError(f"App invalida {app!r}; validas: {sorted(_VALID_APPS)}")
        lines = self.send_command(f"SETAPP {normalized}")
        if not is_ok(lines):
            raise CommandRejectedError(f"{self.name}: SETAPP no confirmo ok; respuesta: {lines!r}")

    def decaid(self) -> ChipId:
        """`DECAID`: identificacion del chip UWB."""
        return parse_decaid(self.send_command("DECAID"))

    def getotp(self) -> list[str]:
        """`GETOTP`: volcado crudo de la memoria OTP."""
        return self.send_command("GETOTP", timeout_s=5.0)

    def thread(self) -> list[str]:
        """`THREAD`: informacion cruda de hilos y memoria."""
        return self.send_command("THREAD")

    def help_cmd(self, cmd: str | None = None) -> list[str]:
        """`HELP` o `HELP <CMD>`: ayuda cruda del firmware."""
        return self.send_command("HELP" if cmd is None else f"HELP {cmd.upper()}")

    def uart_status(self) -> list[str]:
        """`UART` (solo consulta).

        La escritura `UART 0/1` deliberadamente no se implementa: cambia
        que interfaz fisica recibe la consola del nodo y puede dejarlo
        inalcanzable por BLE — ver docs/protocolo-ble-qorvo.md seccion 5.
        """
        return self.send_command("UART")

    def lcfg(self) -> list[str]:
        """`LCFG`: configuracion cruda de la aplicacion LISTENER."""
        return self.send_command("LCFG")

    # ------------------------------------------------------------ aplicaciones

    def start_initf(self, **params: object) -> None:
        """`INITF`: inicia el rol INITIATOR de una sesion FiRa TWR.

        Acepta solo las opciones documentadas (`chan`, `prfset`, `pcode`,
        `slot`, `block`, `round`, `rru`, `id`, `vupper`, `multi`, `hop`,
        `addr`, `paddr`), validadas antes de enviar. Recordar que pasar
        cualquier parametro resetea los demas a default (ver
        docs/protocolo-ble-qorvo.md seccion 3).
        """
        self._start_app("INITF", params)

    def start_respf(self, **params: object) -> None:
        """`RESPF`: inicia el rol RESPONDER de una sesion FiRa TWR (ver start_initf)."""
        self._start_app("RESPF", params)

    def start_listener(self) -> None:
        """`LISTENER`: inicia el modo sniffer (sin parametros por ahora)."""
        self._start_app("LISTENER", {})

    def _start_app(self, app: str, params: Mapping[str, object]) -> None:
        command = " ".join([app, *_format_app_options(params)])
        lines = self.send_command(command)
        if not is_ok(lines):
            # Algunas apps pueden arrancar sin emitir ok inmediato; no se aborta.
            logger.warning("%s en %s no confirmo ok; respuesta: %r", app, self.name, lines)

    def read_notifications(
        self,
        *,
        duration_s: float | None = None,
        max_count: int | None = None,
        on_measurement: Callable[[Measurement], None] | None = None,
    ) -> list[Measurement]:
        """Lee notificaciones `SESSION_INFO_NTF` durante una sesion de ranging.

        Lee del canal de notificaciones (`Transport.read_notification_line`):
        sobre BLE es el servicio GATT dedicado "Qorvo Stream" del firmware
        del puente (>= 0.3.0), separado del canal de comandos; sobre un
        transporte de un solo canal es el mismo flujo que `read_line`.

        Corta al alcanzar `max_count` mediciones o al vencer `duration_s`
        (al menos uno es obligatorio). Sin `duration_s`, retorna en el
        primer silencio del puerto. Las lineas que no son notificaciones
        se ignoran; las notificaciones mal formadas se loguean y se
        descartan.

        Cada notificacion llega partida en varias lineas (la continuacion
        arranca con un `\\r` residual); se reensambla acumulando lineas
        hasta balancear las llaves `{}`.

        Con `DIAG 1` activo (ver `diag`), tambien llega una notificacion
        `RANGE_DIAGNOSTICS_NTF` por ronda — verificado contra hardware real
        2026-09-10, precede a la `SESSION_INFO_NTF` de esa misma ronda. Se
        parsea y se adjunta como `Measurement.diagnostics` a la siguiente
        medicion (no trae numero de ronda propio para emparejarla de otra
        forma, ver `parse_range_diagnostics`); si DIAG esta apagado nunca
        llega y `diagnostics` queda en `None`.

        En modo uno-a-muchos (`-MULTI`, ver `ranging/session.py`) una sola
        `SESSION_INFO_NTF` trae una medicion por respondedor
        (`parse_session_info` devuelve varias) — cada una se agrega por
        separado a la lista devuelta y dispara su propio `on_measurement`.
        [Por verificar en hardware]: no se confirmo si `RANGE_DIAGNOSTICS_NTF`
        trae un bloque por respondedor o uno combinado en este modo: el
        diagnostico pendiente, si llega, se adjunta solo a la primera
        medicion de la notificacion.
        """
        if duration_s is None and max_count is None:
            raise ValueError("Indicar duration_s y/o max_count")
        deadline = None if duration_s is None else time.monotonic() + duration_s
        measurements: list[Measurement] = []
        fragment: list[str] = []
        fragment_is_diagnostics = False
        pending_diagnostics: RangeDiagnostics | None = None
        while True:
            if max_count is not None and len(measurements) >= max_count:
                break
            if deadline is not None and time.monotonic() >= deadline:
                break
            line = self._transport.read_notification_line(0.5)
            if line is None:
                if deadline is None:
                    break
                continue
            stripped = line.strip()
            if stripped.startswith(_SESSION_NTF_PREFIX):
                fragment = [stripped]
                fragment_is_diagnostics = False
            elif stripped.startswith(_RANGE_DIAG_NTF_PREFIX):
                fragment = [stripped]
                fragment_is_diagnostics = True
            elif fragment:
                fragment.append(stripped)
            else:
                continue
            joined = " ".join(fragment)
            if joined.count("{") > joined.count("}"):
                if len(fragment) > _MAX_FRAGMENT_LINES:
                    logger.warning(
                        "Notificacion inconclusa descartada en %s: %r", self.name, joined
                    )
                    fragment = []
                continue
            fragment = []
            if fragment_is_diagnostics:
                try:
                    pending_diagnostics = parse_range_diagnostics(joined)
                except ValueError:
                    logger.warning("Diagnostico no parseable en %s: %r", self.name, joined)
                continue
            try:
                parsed = parse_session_info(joined)
            except ValueError:
                logger.warning("Notificacion no parseable en %s: %r", self.name, joined)
                continue
            for index, measurement in enumerate(parsed):
                if index == 0 and pending_diagnostics is not None:
                    measurement = replace(measurement, diagnostics=pending_diagnostics)
                    pending_diagnostics = None
                measurements.append(measurement)
                if on_measurement is not None:
                    on_measurement(measurement)
        return measurements
