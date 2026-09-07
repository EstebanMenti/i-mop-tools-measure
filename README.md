# i-mop-tools-measure

Mide la distancia real entre nodos UWB (Qorvo DW3xxx, vía el puente BLE
nRF52840 de `I-mop-nrf52840-fw`) y la compara contra la distancia
geométrica calculada a partir de las posiciones declaradas en un archivo de
ambiente TOML.

> **Estado:** en planificación/andamiaje (Fase F0 — ver
> [docs/plan-implementacion.md](docs/plan-implementacion.md)). Este README
> se actualiza a medida que cada fase se implementa; lo que describe la
> sección 4 (Uso) es el comportamiento objetivo, no necesariamente lo que
> ya funciona hoy.

## 1. Qué hace este proyecto

| Paso | Descripción |
|---|---|
| 1. Leer ambiente | Carga `environments/sala_XX.toml`: nombre, MAC BLE, dirección UWB y posición de cada nodo. |
| 2. Calcular distancias | Distancia euclídea 3D entre todos los pares de nodos, a partir de sus posiciones declaradas. |
| 3. Medir por BLE/UWB | Para cada par: conecta por BLE a los dos nodos, configura uno como iniciador (`INITF`) y el otro como respondedor (`RESPF`), corre una sesión de ranging y promedia N muestras de distancia real. |
| 4. Repetir | Ídem para todos los pares del ambiente. |
| 5. Reportar | Genera un reporte (JSON + Markdown) con distancia calculada vs. medida, error absoluto y porcentual por par. |

Hoy es un **script/CLI**. El objetivo declarado es que evolucione a una
**herramienta visual** una vez validado el flujo por línea de comandos —
ver Fase F7 en [docs/plan-implementacion.md](docs/plan-implementacion.md).

## 2. Hardware requerido

- N nodos, cada uno una placa nRF52840 (firmware `I-mop-nrf52840-fw`)
  puenteada por UART a un módulo Qorvo DWM3001C/QM33, anunciando por BLE
  como `"UWB Node"`.
- Cada nodo debe haber sido provisionado una vez por USB directo (ver
  `../i-mop-qorvo-CLI-script`) — de fábrica, el Qorvo solo responde por
  USB.
- PC/host con adaptador BLE compatible con `bleak`.

## 3. Instalación

Herramienta independiente: no requiere tener clonado ningún otro repo al
lado (el transporte BLE y el cliente del protocolo Qorvo están portados
dentro de este proyecto — ver [docs/arquitectura.md](docs/arquitectura.md)
decisión D1).

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
```

## 4. Formato del archivo de ambiente

Ver [docs/formato-ambiente-toml.md](docs/formato-ambiente-toml.md).
Ejemplo real: [environments/sala_20.toml](environments/sala_20.toml).

## 5. Uso (objetivo — ver estado real en la tabla de fases)

```powershell
imop-measure run --environment environments/sala_20.toml --samples 30 --tolerance-cm 5
```

Genera `reports/medicion-<sala_id>-<timestamp>.json` y `.md` con la
comparación calculada vs. medida por par de nodos.

## 6. Documentación

| Documento | Contenido |
|---|---|
| [docs/README.md](docs/README.md) | Índice completo de documentación |
| [CLAUDE.md](CLAUDE.md) | Reglas de programación, estructura, flujo de Git, reglas para IA |
| [docs/arquitectura.md](docs/arquitectura.md) | Capas, módulos, decisiones de diseño |
| [docs/plan-implementacion.md](docs/plan-implementacion.md) | Fases de implementación, de andamiaje a herramienta visual |
| [docs/protocolo-ble-qorvo.md](docs/protocolo-ble-qorvo.md) | Comandos BLE/Qorvo usados para configurar nodos y leer distancia |
| [docs/formato-ambiente-toml.md](docs/formato-ambiente-toml.md) | Esquema de `environments/sala_XX.toml` |

## 7. Desarrollo

Convenciones completas en [CLAUDE.md](CLAUDE.md). Gate antes de cada
commit/PR:

```powershell
ruff check
ruff format --check
mypy src
pytest -m "not hardware"
```

Flujo de Git: una rama por fase (`feature/f<N>-<nombre>`), PR contra
`main`, commits en Conventional Commits en español — ver
[CLAUDE.md §7](CLAUDE.md#7-flujo-de-trabajo-con-git).
