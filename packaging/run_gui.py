"""Punto de entrada para PyInstaller (ver packaging/imop-measure-gui.spec).

PyInstaller analiza este script en vez de apuntar directamente al wrapper
generado por `console_scripts` (`imop-measure-gui.exe` del venv) -- mas
fragil de referenciar para el analisis estatico de imports.
"""

from imop_measure.gui.app import main_gui

if __name__ == "__main__":
    main_gui()
