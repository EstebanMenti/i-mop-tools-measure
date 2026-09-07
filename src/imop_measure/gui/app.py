"""Punto de entrada de la GUI (`imop-measure-gui`).

Ver docs/plan-implementacion.md Fase F7.
"""

import sys

from PySide6.QtWidgets import QApplication

from imop_measure.gui.main_window import MainWindow


def main_gui() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main_gui()
