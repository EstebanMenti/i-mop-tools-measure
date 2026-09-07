"""Orquestacion de sesiones BLE/UWB: conecta pares de nodos, configura uno
como iniciador (INITF) y otro como respondedor (RESPF), y promedia las
muestras de distancia medida (SESSION_INFO_NTF).

Usa imop_measure.core (cliente de comandos Qorvo) sobre
imop_measure.transport (BLE) — portados de dwm3001c_cli, repo hermano
../i-mop-qorvo-CLI-script, ver docs/arquitectura.md decision D1. No conoce
Typer/Rich (decision D2), para poder reusarse desde una futura GUI. Ver
docs/protocolo-ble-qorvo.md para el protocolo exacto. Implementacion
prevista en las Fases F2-F4 (docs/plan-implementacion.md).
"""
