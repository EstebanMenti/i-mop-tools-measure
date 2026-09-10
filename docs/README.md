# Documentación del proyecto — Índice

> **Propósito:** punto de entrada a toda la documentación de
> `i-mop-tools-measure`.
> **Convención:** todos los documentos se redactan en español, en Markdown,
> con el mismo estilo técnico (títulos numerados, tablas, notas
> `> **Nota**`/`> **Advertencia**`). Lo que no proviene de documentación
> oficial de Qorvo/Nordic o de los repos hermanos se marca
> **[Por verificar en hardware]**.

---

## 1. Documentos del proyecto

| Documento | Contenido | Audiencia |
|---|---|---|
| [../README.md](../README.md) | Qué hace el proyecto, instalación, uso | Usuarios |
| [../CLAUDE.md](../CLAUDE.md) | Reglas de programación, estructura, git, reglas para IA | Desarrolladores / IA |
| [arquitectura.md](arquitectura.md) | Capas, módulos, decisiones de diseño, flujo de datos | Desarrolladores |
| [plan-implementacion.md](plan-implementacion.md) | Fases de implementación (F0..F7), criterios de aceptación | Desarrolladores / IA |
| [protocolo-ble-qorvo.md](protocolo-ble-qorvo.md) | Referencia condensada del protocolo BLE + comandos Qorvo usados por este proyecto | Desarrolladores / IA |
| [formato-ambiente-toml.md](formato-ambiente-toml.md) | Esquema de `environments/sala_XX.toml`, mapeo `uwb_addr` → `ADDR`/`PADDR` | Desarrolladores / Usuarios |
| [formato-reporte.md](formato-reporte.md) | Esquema del reporte JSON/Markdown que genera `imop-measure run` | Desarrolladores / Usuarios |
| [empaquetado-windows.md](empaquetado-windows.md) | Cómo generar `imop-measure-gui.exe` con PyInstaller | Desarrolladores |
| [investigacion-desviaciones-uwb-2026-09-10.md](investigacion-desviaciones-uwb-2026-09-10.md) | Investigación de desviaciones en mediciones reales: hipótesis descartadas, causa confirmada (iniciador sin power-cycle) y fix, problema abierto pendiente | Desarrolladores / IA |

## 2. Documentos de referencia (repos hermanos)

Estos documentos **no viven en este repositorio** — se listan acá porque
`i-mop-tools-measure` depende de ellos para todo lo relacionado a
protocolo/hardware. Ante cualquier duda de detalle que no cubra
[protocolo-ble-qorvo.md](protocolo-ble-qorvo.md), son la fuente autoritativa.

| Documento | Repo | Contenido |
|---|---|---|
| `docs/referencia-comandos-fw110.md` | `../i-mop-qorvo-CLI-script` | Referencia exhaustiva de cada comando de firmware Qorvo (sintaxis, respuesta) |
| `docs/verificacion-comandos-responder-ble.md` | `../i-mop-qorvo-CLI-script` | Validación en hardware real de comandos sobre el puente BLE, incluyendo una sesión de ranging completa |
| `docs/arquitectura.md` | `../i-mop-qorvo-CLI-script` | Arquitectura del cliente BLE/Qorvo original, del que `imop_measure.transport`/`imop_measure.core` son un puerto adaptado |
| `doc/00_BLE_Protocol_Specification.md` | `../I-mop-nrf52840-fw` | Especificación GATT completa del puente BLE (UUIDs, comando `qorvo`, límites) |
| `doc/03_LED_Status_Indicator_Specification.md` | `../I-mop-nrf52840-fw` | Significado del LED de estado del nodo (útil para diagnóstico en campo) |

## 3. Cómo agregar un documento

1. Redactarlo en español siguiendo el estilo de los documentos existentes.
2. Iniciarlo con un encabezado `>` que indique **propósito** y **alcance**.
3. Agregarlo a la tabla correspondiente de este índice en el mismo pull
   request.
