# -*- mode: python ; coding: utf-8 -*-
"""Spec de PyInstaller para empaquetar imop-measure-gui como .exe unico
(onefile) para Windows.

Uso (con el venv del proyecto activado, extra [build] instalado):

    pyinstaller packaging/imop-measure-gui.spec

El resultado queda en dist/imop-measure-gui.exe. environments/ NO se
empaqueta adentro del .exe -- se sigue leyendo como carpeta externa en
tiempo de ejecucion (ver el campo "Archivo de ambiente" de la GUI), asi
que hay que copiarla a mano junto al .exe distribuido.
"""

import os

from PyInstaller.utils.hooks import collect_all

_SRC_DIR = os.path.join(SPECPATH, "..", "src")  # noqa: F821 (SPECPATH lo inyecta PyInstaller)
_ENTRY_SCRIPT = os.path.join(SPECPATH, "run_gui.py")  # noqa: F821

datas: list[tuple[str, str]] = []
binaries: list[tuple[str, str]] = []
hiddenimports: list[str] = []

# bleak (transporte BLE) y los paquetes `winrt` que usa su backend en
# Windows (ver docs/protocolo-ble-qorvo.md, docs/arquitectura.md decision
# D1) son extensiones nativas compiladas (.pyd) que la deteccion
# automatica de imports de PyInstaller no siempre encuentra -- se fuerza
# su inclusion completa con collect_all para no romper el ranging BLE en
# el .exe empaquetado (no hay forma de probar esto sin hardware real, asi
# que se prefiere sobre-incluir a que falle en silencio).
_PACKAGES_TO_COLLECT = [
    "bleak",
    "winrt.runtime",
    "winrt.system",
    "winrt.windows.devices.bluetooth",
    "winrt.windows.devices.bluetooth.advertisement",
    "winrt.windows.devices.bluetooth.genericattributeprofile",
    "winrt.windows.devices.enumeration",
    "winrt.windows.devices.radios",
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
    "winrt.windows.storage.streams",
]
for _package in _PACKAGES_TO_COLLECT:
    _datas, _binaries, _hiddenimports = collect_all(_package)
    datas += _datas
    binaries += _binaries
    hiddenimports += _hiddenimports

a = Analysis(  # noqa: F821 (inyectado por PyInstaller al ejecutar el spec)
    [_ENTRY_SCRIPT],
    pathex=[_SRC_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="imop-measure-gui",
    console=False,
)
