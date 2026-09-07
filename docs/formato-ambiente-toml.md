# Formato del archivo de ambiente (`environments/sala_XX.toml`)

> **Propósito:** documentar el esquema de los archivos `environments/sala_XX.toml`,
> única fuente de verdad sobre qué nodos existen en un ambiente y dónde
> están ubicados.
> **Alcance:** describe el formato tal como lo consume `config/loader.py`.
> No describe el protocolo BLE/Qorvo (ver
> [protocolo-ble-qorvo.md](protocolo-ble-qorvo.md)).

## 1. Ubicación y nombre de archivo

Los archivos de ambiente viven en `environments/`, uno por sala/espacio
físico, nombrados `sala_<id>.toml` (ej. `environments/sala_20.toml`). El
`id` del nombre de archivo debe coincidir con `[sala].id` dentro del propio
archivo.

## 2. Secciones

### `[sala]`

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | string | Identificador de sala, debe coincidir con el nombre de archivo. |
| `nombre` | string (opcional) | Nombre descriptivo, solo documentación. |

### `[dimensions]`

`x`, `y`, `z` en metros — dimensiones del espacio. Se usan para
validación/plotting, no entran en el cálculo de distancia entre nodos
(que se calcula directamente entre posiciones de anclas).

### `[[anchors]]` (una tabla por nodo)

| Campo | Tipo | Descripción |
|---|---|---|
| `key` | string | Identificador único del nodo dentro del archivo (ej. `"uwb_node_2"`). |
| `nombre` | string | Nombre legible (ej. `"UWB-Node-2"`). |
| `mac` | string, `AA:BB:CC:DD:EE:FF` | MAC BLE completa — se usa para conectar/desconectar por BLE. |
| `uwb_addr` | string, `XX:YY` (2 bytes hex) | Dirección corta UWB — se usa en la sesión de ranging (`-ADDR=`/`-PADDR=`) y para matchear las notificaciones `SESSION_INFO_NTF` (`mac_address=0x....`). **Es un campo distinto de `mac` y no se deriva de él** — hay que cargar ambos. |
| `posicion` | array de 3 floats `[x, y, z]` | Posición del nodo en metros, usada para calcular la distancia geométrica de referencia. |
| `tiempo_prendido` | string, `<entero><s\|m>` | Tiempo sugerido de encendido (ej. `"120s"`). Informativo; el timeout real de comandos se controla en `[ble_timeouts]`. |

Anclas comentadas (`#[[anchors]]`) se tratan como **inactivas** — no
participan en el cálculo de pares ni en la campaña de medición.

### `[ble_timeouts]` (opcional — se usan defaults si se omite)

Timeouts específicos de BLE para el ambiente. Ver comentarios inline en
`environments/sala_20.toml` para la lista completa
(`connection_timeout`, `command_timeout`, `mtu_negotiation_wait`,
`mtu_retry_wait`, `mtu_retry_attempts`, `session_end_timeout`,
`power_off_connection_timeout`, `max_concurrent_connections`,
`monitor_interval`, `qorvo_command_timeout`). Estos mismos nombres y
valores por defecto son los que usa `i-mop-qorvo-CLI-script`, así que se
reusan tal cual — no reinventar otro esquema de timeouts.

## 3. Mapeo `uwb_addr` → `ADDR`/`PADDR` decimal

El firmware Qorvo espera `-ADDR=`/`-PADDR=` como **enteros decimales**, pero
el TOML guarda `uwb_addr` como dos bytes hexadecimales separados por `:`
(ej. `"00:02"`). La conversión es:

```
uwb_addr = "00:02"
→ bytes = [0x00, 0x02]
→ entero = (0x00 << 8) | 0x02 = 2
```

En Python:

```python
def uwb_addr_to_int(uwb_addr: str) -> int:
    high, low = uwb_addr.split(":")
    return (int(high, 16) << 8) | int(low, 16)
```

Esta función vive en `ranging/addressing.py` (ver
[arquitectura.md](arquitectura.md) §2.3).

## 4. Ejemplo mínimo

```toml
[sala]
id = "20"
nombre = "Sala 20 - Configuración Real"

[dimensions]
x = 6.0
y = 8.0
z = 3.0

[[anchors]]
key             = "uwb_node_2"
nombre          = "UWB-Node-2"
mac             = "00:00:00:00:00:02"
uwb_addr        = "00:02"
posicion        = [0.03, 0.03, 0.26]
tiempo_prendido = "120s"

[[anchors]]
key             = "uwb_node_3"
nombre          = "UWB-Node-3"
mac             = "00:00:00:00:00:03"
uwb_addr        = "00:03"
posicion        = [0.03, 2.6, 0.82]
tiempo_prendido = "120s"
```

Con dos o más anclas activas, `geometry/pairs.py` genera todos los pares
sin repetición (para 5 anclas activas como en `sala_20.toml` actual: 10
pares) y `geometry/distance.py` calcula la distancia euclídea 3D de cada
uno a partir de `posicion`.
