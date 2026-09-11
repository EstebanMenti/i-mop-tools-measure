"""imop_measure: mide distancia real entre nodos UWB y la compara contra la
distancia geometrica calculada a partir de sus posiciones declaradas.

Ver docs/arquitectura.md para la separacion en capas (config, geometry,
ranging, report, app) y docs/plan-implementacion.md para el orden de
implementacion.
"""

# Debe coincidir con `version` en pyproject.toml. Constante explicita (no
# `importlib.metadata.version(...)`) porque el .exe empaquetado con
# PyInstaller (ver packaging/imop-measure-gui.spec) no incluye el
# .dist-info del propio proyecto, solo el de sus dependencias -- leerlo en
# tiempo de ejecucion fallaria en el ejecutable distribuido.
__version__ = "0.1.3"
