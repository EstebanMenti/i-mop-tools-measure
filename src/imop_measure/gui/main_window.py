"""Ventana principal: formulario + tabla en vivo + resumen final.

Ver docs/plan-implementacion.md Fase F7 (alcance de la v1: el equivalente
visual de `imop-measure run`, no un visor de reportes ni un editor del
TOML).
"""

import time
from pathlib import Path

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from imop_measure import __version__
from imop_measure.config.loader import load_ambiente
from imop_measure.errors import MeasureError
from imop_measure.gui.models import CampaignResultsModel
from imop_measure.gui.worker import CampaignWorker, start_worker
from imop_measure.report.build import DEFAULT_TOLERANCE_CM
from imop_measure.report.models import PairResult

_DEFAULT_SAMPLES = 30  # mismo default que app/cli.py (DEFAULT_SAMPLES)
_DEFAULT_ENVIRONMENT = "environments/sala_20.toml"
_DEFAULT_REPORT_DIR = "reports"

# Estimacion de tiempo para la barra de progreso -- valores redondos
# basados en corridas reales contra hardware (5 nodos, con el
# power_cycle() de ranging/pair_runner.py activo, ver docs/protocolo-ble-qorvo.md):
# la mayoria de las direcciones tardan ~60-75s, y una reconexion BLE
# transitoria (bastante comun, ver transport/ble_link.py) agrega ~90s mas
# esa direccion. Se usan solo como estimacion INICIAL, antes de tener datos
# reales de la corrida en curso -- ver _estimated_total_s().
_ESTIMATED_S_PER_DIRECTION = 70.0
_ESTIMATED_DISCONNECTS = 5
_ESTIMATED_S_PER_DISCONNECT = 90.0


def _format_duration(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    minutes, secs = divmod(total_seconds, 60)
    return f"{minutes}m {secs:02d}s"


class MainWindow(QMainWindow):
    """Corre una campaña de medición completa con progreso en vivo.

    Es dueña del ciclo de vida del `QThread`/`CampaignWorker` de la
    corrida en curso — mantiene referencias a ambos como atributos de
    instancia mientras corren, para que Python no los recolecte antes de
    que terminen (crashea Qt si lo hace).
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"imop-measure — Medición de distancia UWB (v{__version__})")
        self.resize(900, 600)

        self._thread: QThread | None = None
        self._worker: CampaignWorker | None = None
        self._campaign_start: float | None = None
        self._total_directions = 0
        self._completed_directions = 0
        self._initial_estimate_s = 0.0

        central = QWidget()
        layout = QVBoxLayout(central)
        self.setCentralWidget(central)

        layout.addLayout(self._build_form())

        top_row = QHBoxLayout()
        self._run_btn = QPushButton("Ejecutar campaña")
        self._run_btn.clicked.connect(self._on_run_clicked)
        self._status_label = QLabel("Listo.")
        top_row.addWidget(self._run_btn)
        top_row.addWidget(self._status_label, 1)
        layout.addLayout(top_row)

        self._model = CampaignResultsModel()
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table, 1)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat("Sin corridas todavía")
        layout.addWidget(self._progress_bar)

        self._time_label = QLabel("")
        layout.addWidget(self._time_label)

        self._action_label = QLabel("")
        self._action_label.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(self._action_label)

        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(1000)
        self._progress_timer.timeout.connect(self._update_time_label)

        self._report_label = QLabel("")
        self._report_label.setWordWrap(True)
        layout.addWidget(self._report_label)

        version_label = QLabel(f"imop-measure v{__version__}")
        version_label.setStyleSheet("color: gray;")
        layout.addWidget(version_label)

    def _build_form(self) -> QFormLayout:
        form = QFormLayout()

        self._environment_edit = QLineEdit(_DEFAULT_ENVIRONMENT)
        browse_btn = QPushButton("Examinar…")
        browse_btn.clicked.connect(self._on_browse_clicked)
        environment_row = QHBoxLayout()
        environment_row.addWidget(self._environment_edit, 1)
        environment_row.addWidget(browse_btn)
        form.addRow("Archivo de ambiente:", environment_row)

        self._samples_spin = QSpinBox()
        self._samples_spin.setRange(1, 10_000)
        self._samples_spin.setValue(_DEFAULT_SAMPLES)
        form.addRow("Muestras por dirección:", self._samples_spin)

        self._tolerance_spin = QDoubleSpinBox()
        self._tolerance_spin.setRange(0.0, 10_000.0)
        self._tolerance_spin.setSuffix(" cm")
        self._tolerance_spin.setValue(DEFAULT_TOLERANCE_CM)
        form.addRow("Tolerancia PASS/FAIL:", self._tolerance_spin)

        self._mode_one_to_one = QRadioButton("Uno a uno (una conexión BLE por dirección)")
        self._mode_one_to_one.setChecked(True)
        self._mode_one_to_many = QRadioButton(
            "Uno a muchos (todos los respondedores a la vez — experimental)"
        )
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._mode_one_to_one)
        self._mode_group.addButton(self._mode_one_to_many)
        mode_row = QVBoxLayout()
        mode_row.addWidget(self._mode_one_to_one)
        mode_row.addWidget(self._mode_one_to_many)
        form.addRow("Modo de medición:", mode_row)

        self._report_dir_edit = QLineEdit(_DEFAULT_REPORT_DIR)
        report_dir_browse_btn = QPushButton("Examinar…")
        report_dir_browse_btn.clicked.connect(self._on_browse_report_dir_clicked)
        report_dir_row = QHBoxLayout()
        report_dir_row.addWidget(self._report_dir_edit, 1)
        report_dir_row.addWidget(report_dir_browse_btn)
        form.addRow("Carpeta de reportes:", report_dir_row)

        return form

    def _on_browse_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Elegir archivo de ambiente", "environments", "TOML (*.toml)"
        )
        if path:
            self._environment_edit.setText(path)

    def _on_browse_report_dir_clicked(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Elegir carpeta de reportes", self._report_dir_edit.text()
        )
        if path:
            self._report_dir_edit.setText(path)

    def _on_run_clicked(self) -> None:
        environment_path = Path(self._environment_edit.text())
        try:
            ambiente = load_ambiente(environment_path)
        except MeasureError as exc:
            self._status_label.setText(f"Error: {exc}")
            return

        n_anchors = len(ambiente.anchors)
        self._total_directions = n_anchors * (n_anchors - 1)
        self._completed_directions = 0
        self._initial_estimate_s = (
            self._total_directions * _ESTIMATED_S_PER_DIRECTION
            + _ESTIMATED_DISCONNECTS * _ESTIMATED_S_PER_DISCONNECT
        )
        self._campaign_start = time.monotonic()

        self._model.clear()
        self._run_btn.setEnabled(False)
        self._mode_one_to_one.setEnabled(False)
        self._mode_one_to_many.setEnabled(False)
        self._status_label.setText("Midiendo…")
        self._report_label.setText("")
        self._action_label.setText("")
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat(f"%p% (0/{self._total_directions})")
        self._update_time_label()
        self._progress_timer.start()

        worker = CampaignWorker(
            environment_path=environment_path,
            samples=self._samples_spin.value(),
            tolerance_cm=self._tolerance_spin.value(),
            report_dir=Path(self._report_dir_edit.text()),
            one_to_many=self._mode_one_to_many.isChecked(),
        )
        thread = start_worker(worker)
        worker.pair_measured.connect(self._model.add_result)
        worker.pair_measured.connect(self._on_pair_progress)
        worker.status_update.connect(self._action_label.setText)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_pair_progress(self, _result: PairResult) -> None:
        self._completed_directions += 1
        if self._total_directions:
            pct = int(self._completed_directions / self._total_directions * 100)
            self._progress_bar.setValue(pct)
            self._progress_bar.setFormat(
                f"%p% ({self._completed_directions}/{self._total_directions})"
            )
        self._update_time_label()

    def _update_time_label(self) -> None:
        if self._campaign_start is None:
            return
        elapsed = time.monotonic() - self._campaign_start
        if self._completed_directions > 0 and self._total_directions:
            # Estimacion adaptativa: promedio real de esta corrida (ya
            # incluye cualquier reconexion que haya pasado hasta ahora),
            # en vez del valor inicial fijo -- se auto-corrige a medida
            # que avanza.
            avg_s = elapsed / self._completed_directions
            estimated_total = avg_s * self._total_directions
        else:
            estimated_total = self._initial_estimate_s
        remaining = max(0.0, estimated_total - elapsed)
        self._time_label.setText(
            f"Transcurrido: {_format_duration(elapsed)} · "
            f"Estimado total: {_format_duration(estimated_total)} · "
            f"Restante: {_format_duration(remaining)}"
        )

    def _on_finished(self, results: list[PairResult], json_path: Path, md_path: Path) -> None:
        self._progress_timer.stop()
        self._update_time_label()
        self._progress_bar.setValue(100)
        self._run_btn.setEnabled(True)
        self._mode_one_to_one.setEnabled(True)
        self._mode_one_to_many.setEnabled(True)
        self._action_label.setText("")
        pass_n = sum(1 for r in results if r.estado == "PASS")
        fail_n = sum(1 for r in results if r.estado == "FAIL")
        error_n = sum(1 for r in results if r.estado == "ERROR")
        self._status_label.setText(f"{pass_n} PASS · {fail_n} FAIL · {error_n} ERROR")
        self._report_label.setText(f"Reportes: {json_path} · {md_path}")

    def _on_failed(self, message: str) -> None:
        self._progress_timer.stop()
        self._run_btn.setEnabled(True)
        self._mode_one_to_one.setEnabled(True)
        self._mode_one_to_many.setEnabled(True)
        self._action_label.setText("")
        self._status_label.setText(f"Error: {message}")
