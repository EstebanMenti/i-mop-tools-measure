"""Ventana principal: formulario + tabla en vivo + resumen final.

Ver docs/plan-implementacion.md Fase F7 (alcance de la v1: el equivalente
visual de `imop-measure run`, no un visor de reportes ni un editor del
TOML).
"""

from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from imop_measure.gui.models import CampaignResultsModel
from imop_measure.gui.worker import CampaignWorker, start_worker
from imop_measure.report.build import DEFAULT_REVIEW_THRESHOLD_CM, DEFAULT_TOLERANCE_CM
from imop_measure.report.models import PairResult

_DEFAULT_SAMPLES = 30  # mismo default que app/cli.py (DEFAULT_SAMPLES)
_DEFAULT_ENVIRONMENT = "environments/sala_20.toml"
_DEFAULT_REPORT_DIR = "reports"


class MainWindow(QMainWindow):
    """Corre una campaña de medición completa con progreso en vivo.

    Es dueña del ciclo de vida del `QThread`/`CampaignWorker` de la
    corrida en curso — mantiene referencias a ambos como atributos de
    instancia mientras corren, para que Python no los recolecte antes de
    que terminen (crashea Qt si lo hace).
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("imop-measure — Medición de distancia UWB")
        self.resize(900, 600)

        self._thread: QThread | None = None
        self._worker: CampaignWorker | None = None

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

        self._report_label = QLabel("")
        self._report_label.setWordWrap(True)
        layout.addWidget(self._report_label)

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

        self._review_threshold_spin = QDoubleSpinBox()
        self._review_threshold_spin.setRange(0.0, 10_000.0)
        self._review_threshold_spin.setSuffix(" cm")
        self._review_threshold_spin.setValue(DEFAULT_REVIEW_THRESHOLD_CM)
        form.addRow("Umbral de revisión:", self._review_threshold_spin)

        self._report_dir_edit = QLineEdit(_DEFAULT_REPORT_DIR)
        form.addRow("Carpeta de reportes:", self._report_dir_edit)

        return form

    def _on_browse_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Elegir archivo de ambiente", "environments", "TOML (*.toml)"
        )
        if path:
            self._environment_edit.setText(path)

    def _on_run_clicked(self) -> None:
        self._model.clear()
        self._run_btn.setEnabled(False)
        self._status_label.setText("Midiendo…")
        self._report_label.setText("")

        worker = CampaignWorker(
            environment_path=Path(self._environment_edit.text()),
            samples=self._samples_spin.value(),
            tolerance_cm=self._tolerance_spin.value(),
            review_threshold_cm=self._review_threshold_spin.value(),
            report_dir=Path(self._report_dir_edit.text()),
        )
        thread = start_worker(worker)
        worker.pair_measured.connect(self._model.add_result)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_finished(self, results: list[PairResult], json_path: Path, md_path: Path) -> None:
        self._run_btn.setEnabled(True)
        pass_n = sum(1 for r in results if r.estado == "PASS")
        fail_n = sum(1 for r in results if r.estado == "FAIL")
        error_n = sum(1 for r in results if r.estado == "ERROR")
        revisar_n = sum(1 for r in results if r.necesita_revision)
        self._status_label.setText(
            f"{pass_n} PASS · {fail_n} FAIL · {error_n} ERROR · {revisar_n} a revisar"
        )
        self._report_label.setText(f"Reportes: {json_path} · {md_path}")

    def _on_failed(self, message: str) -> None:
        self._run_btn.setEnabled(True)
        self._status_label.setText(f"Error: {message}")
