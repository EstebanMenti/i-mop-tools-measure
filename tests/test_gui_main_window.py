"""Test minimo de imop_measure.gui.main_window.MainWindow — no requiere hardware.

Solo confirma que la ventana se construye y expone sus controles basicos.
Interaccion mas profunda (click en "Ejecutar", flujo completo) queda sin
cubrir por ahora -- las vistas son la parte mas costosa de testear de una
GUI Qt, mismo criterio que el repo hermano (ver docs/plan-implementacion.md
Fase F7).
"""

import time
from pathlib import Path

from imop_measure import __version__
from imop_measure.gui.main_window import MainWindow, _format_duration
from imop_measure.gui.worker import CampaignWorker
from imop_measure.report.build import DEFAULT_TOLERANCE_CM


def test_main_window_constructs_with_expected_defaults(qtbot: object) -> None:
    window = MainWindow()
    qtbot.addWidget(window)  # type: ignore[attr-defined]

    assert window.windowTitle() == f"imop-measure — Medición de distancia UWB (v{__version__})"
    assert window._environment_edit.text() == "environments/sala_20.toml"
    assert window._samples_spin.value() == 30
    assert window._tolerance_spin.value() == DEFAULT_TOLERANCE_CM
    assert window._report_dir_edit.text() == "reports"
    assert window._run_btn.isEnabled()


def test_browse_report_dir_updates_field(qtbot: object, monkeypatch: object) -> None:
    window = MainWindow()
    qtbot.addWidget(window)  # type: ignore[attr-defined]

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "imop_measure.gui.main_window.QFileDialog.getExistingDirectory",
        lambda *args, **kwargs: "C:/otra/carpeta",
    )

    window._on_browse_report_dir_clicked()

    assert window._report_dir_edit.text() == "C:/otra/carpeta"


def test_browse_report_dir_keeps_field_on_cancel(qtbot: object, monkeypatch: object) -> None:
    window = MainWindow()
    qtbot.addWidget(window)  # type: ignore[attr-defined]

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "imop_measure.gui.main_window.QFileDialog.getExistingDirectory",
        lambda *args, **kwargs: "",
    )

    window._on_browse_report_dir_clicked()

    assert window._report_dir_edit.text() == "reports"


def test_format_duration() -> None:
    assert _format_duration(0) == "0m 00s"
    assert _format_duration(65) == "1m 05s"
    assert _format_duration(-5) == "0m 00s"


def test_action_label_starts_empty(qtbot: object) -> None:
    window = MainWindow()
    qtbot.addWidget(window)  # type: ignore[attr-defined]

    assert window._action_label.text() == ""


def test_action_label_updates_from_worker_status_signal(qtbot: object) -> None:
    """Misma conexion que hace `_on_run_clicked` (`worker.status_update.connect(
    self._action_label.setText)`), sin arrancar el hilo real -- `Signal.emit`
    alcanza para probar el cableado en el mismo hilo de test.
    """
    window = MainWindow()
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    worker = CampaignWorker(
        environment_path=Path("environments/sala_20.toml"),
        samples=1,
        tolerance_cm=DEFAULT_TOLERANCE_CM,
        report_dir=Path("reports"),
    )
    worker.status_update.connect(window._action_label.setText)

    worker.status_update.emit("Conectando a UWB-Node-4...")

    assert window._action_label.text() == "Conectando a UWB-Node-4..."


def test_progress_bar_starts_empty(qtbot: object) -> None:
    window = MainWindow()
    qtbot.addWidget(window)  # type: ignore[attr-defined]

    assert window._progress_bar.value() == 0
    assert window._time_label.text() == ""


def test_pair_progress_updates_bar_and_percentage(qtbot: object) -> None:
    window = MainWindow()
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window._total_directions = 4
    window._completed_directions = 0
    window._campaign_start = time.monotonic()

    window._on_pair_progress(None)  # type: ignore[arg-type]

    assert window._completed_directions == 1
    assert window._progress_bar.value() == 25
    assert window._progress_bar.format() == "%p% (1/4)"


def test_time_label_uses_initial_estimate_before_first_result(qtbot: object) -> None:
    window = MainWindow()
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window._total_directions = 4
    window._completed_directions = 0
    window._initial_estimate_s = 300.0
    window._campaign_start = time.monotonic()

    window._update_time_label()

    assert "Estimado total: 5m 00s" in window._time_label.text()


def test_time_label_switches_to_adaptive_estimate_after_a_result(qtbot: object) -> None:
    window = MainWindow()
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window._total_directions = 4
    window._completed_directions = 1
    window._initial_estimate_s = 300.0
    window._campaign_start = time.monotonic() - 10.0  # 1 direccion tardo ~10s

    window._update_time_label()

    # Adaptativo: 10s/direccion * 4 direcciones = 40s totales estimados,
    # no el valor inicial fijo de 300s.
    assert "Estimado total: 0m 40s" in window._time_label.text()
