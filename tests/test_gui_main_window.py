"""Test minimo de imop_measure.gui.main_window.MainWindow — no requiere hardware.

Solo confirma que la ventana se construye y expone sus controles basicos.
Interaccion mas profunda (click en "Ejecutar", flujo completo) queda sin
cubrir por ahora -- las vistas son la parte mas costosa de testear de una
GUI Qt, mismo criterio que el repo hermano (ver docs/plan-implementacion.md
Fase F7).
"""

from imop_measure.gui.main_window import MainWindow
from imop_measure.report.build import DEFAULT_REVIEW_THRESHOLD_CM, DEFAULT_TOLERANCE_CM


def test_main_window_constructs_with_expected_defaults(qtbot: object) -> None:
    window = MainWindow()
    qtbot.addWidget(window)  # type: ignore[attr-defined]

    assert window.windowTitle() == "imop-measure — Medición de distancia UWB"
    assert window._environment_edit.text() == "environments/sala_20.toml"
    assert window._samples_spin.value() == 30
    assert window._tolerance_spin.value() == DEFAULT_TOLERANCE_CM
    assert window._review_threshold_spin.value() == DEFAULT_REVIEW_THRESHOLD_CM
    assert window._run_btn.isEnabled()
