# Empaquetado como ejecutable de Windows

> **Propósito:** documentar cómo generar `imop-measure-gui.exe`, un
> ejecutable único de Windows que no requiere tener Python ni el `.venv`
> instalados.
> **Alcance:** solo la GUI (`imop-measure-gui`). La CLI (`imop-measure`)
> se sigue distribuyendo vía `pip install`, no se empaqueta.

---

## 1. Dependencia

`pyinstaller` es una dependencia **opcional**, bajo el extra `build`
(`pip install -e .[build]`) — instala también `[gui]`. No se agrega a las
dependencias base ni a `dev` porque solo hace falta para generar el
`.exe`, no para desarrollar o correr los tests (ver CLAUDE.md §4).

## 2. Generar el ejecutable

Con el `.venv` del proyecto activado y el extra `build` instalado:

```
pyinstaller packaging/imop-measure-gui.spec
```

El resultado queda en `dist/imop-measure-gui.exe` (archivo único,
~50 MB). `build/` y `dist/` no se versionan (ver `.gitignore`).

> **Nota:** `environments/` **no** se empaqueta dentro del `.exe` — la
> GUI la sigue leyendo como carpeta externa (campo "Archivo de ambiente"),
> igual que corriendo desde el `.venv`. Para distribuir el `.exe`, copiar
> la carpeta `environments/` al lado.

## 3. Por qué un `.spec` a mano y no `pyinstaller --onefile app.py`

`bleak` (transporte BLE, ver `docs/protocolo-ble-qorvo.md`) usa en
Windows los paquetes `winrt-*` (proyección Python de las APIs WinRT),
que son extensiones nativas compiladas (`.pyd`) por namespace
(`winrt.windows.devices.bluetooth`, `winrt.windows.foundation`, etc.). La
detección automática de imports de PyInstaller no siempre las encuentra
completas, y una falla ahí solo se manifiesta en tiempo de ejecución al
intentar conectar por BLE — no hay forma de probarlo sin hardware real,
así que `packaging/imop-measure-gui.spec` fuerza la inclusión completa
(`collect_all`) de `bleak` y de cada paquete `winrt.*` que su backend usa,
en vez de confiar en la detección automática.

`packaging/run_gui.py` es el punto de entrada que analiza PyInstaller —
más simple de apuntar que el wrapper generado por `console_scripts`.

## 4. Verificación

**[Verificado 2026-09-09]** El `.exe` generado abre la ventana principal
correctamente (formulario, tabla, defaults) contra
`environments/sala_20.toml` copiado al lado. La conexión BLE real desde
el `.exe` empaquetado (no solo desde el `.venv`) queda
**[Por verificar en hardware]** en una próxima campaña.
