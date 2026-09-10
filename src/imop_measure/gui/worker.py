"""Worker `QObject` para correr una campana de medicion fuera del hilo de UI.

`run_campaign` es bloqueante (conexiones BLE reales, minutos de duracion):
correrlo en el hilo de UI congelaria la ventana. Se mueve a un `QThread`
con `moveToThread` (no una subclase de `QThread`, no `QThreadPool`) porque
necesita señales de progreso continuas, no un resultado unico — mismo
patron que `dwm3001c_cli.gui.workers` del repo hermano. Ver
docs/plan-implementacion.md Fase F7 y docs/arquitectura.md decision D7.
"""

from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QObject, QThread, Signal, Slot

from imop_measure.config.loader import load_ambiente
from imop_measure.ranging.campaign import run_campaign
from imop_measure.ranging.pair_runner import MeasuredPair
from imop_measure.ranging.session import SessionParams
from imop_measure.report.build import build_results
from imop_measure.report.models import PairResult
from imop_measure.report.write import write_reports


class CampaignWorker(QObject):
    """Corre `load_ambiente` -> `run_campaign` -> `write_reports` con
    progreso en vivo por direccion medida.

    Nunca deja escapar una excepcion: cualquier falla (TOML invalido,
    error inesperado de `run_campaign`, error al escribir el reporte) se
    emite por `failed`, nunca se relanza — un worker que deja escapar una
    excepcion en `run()` deja el hilo muerto en silencio y el boton de
    "Ejecutar" de `MainWindow` trabado para siempre, sin ningun mensaje
    (bug real documentado en el repo hermano).
    """

    pair_measured = Signal(object)  # PairResult, uno por direccion medida
    status_update = Signal(str)  # mensaje legible del paso en curso (ver run_campaign)
    finished = Signal(list, object, object)  # list[PairResult], Path json, Path md
    failed = Signal(str)

    def __init__(
        self,
        *,
        environment_path: Path,
        samples: int,
        tolerance_cm: float,
        review_threshold_cm: float,
        report_dir: Path,
    ) -> None:
        super().__init__()
        self._environment_path = environment_path
        self._samples = samples
        self._tolerance_cm = tolerance_cm
        self._review_threshold_cm = review_threshold_cm
        self._report_dir = report_dir

    @Slot()
    def run(self) -> None:
        results: list[PairResult] = []
        try:
            ambiente = load_ambiente(self._environment_path)

            def on_pair_done(measured: MeasuredPair) -> None:
                result = build_results(
                    [measured],
                    tolerance_cm=self._tolerance_cm,
                    review_threshold_cm=self._review_threshold_cm,
                )[0]
                results.append(result)
                self.pair_measured.emit(result)

            run_campaign(
                ambiente,
                session=SessionParams(),
                n_samples=self._samples,
                on_pair_done=on_pair_done,
                on_status=self.status_update.emit,
            )
            json_path, md_path = write_reports(
                results,
                sala_id=ambiente.id,
                sala_nombre=ambiente.nombre,
                samples=self._samples,
                tolerance_cm=self._tolerance_cm,
                review_threshold_cm=self._review_threshold_cm,
                report_dir=self._report_dir,
            )
        except Exception as exc:  # ver docstring: nunca dejar escapar una excepcion
            self.failed.emit(str(exc))
            return
        self.finished.emit(results, json_path, md_path)


class _RunnableWorker(Protocol):
    """Estructura minima que necesita `start_worker`."""

    def run(self) -> None: ...
    def moveToThread(self, thread: QThread, /) -> bool: ...


def start_worker(worker: _RunnableWorker) -> QThread:
    """Corre `worker.run()` en un `QThread` dedicado.

    Devuelve el `QThread` sin iniciar todavia, para que quien llama pueda
    conectar señales adicionales antes de `.start()`. Es responsabilidad
    de quien llama mantener referencias vivas a `worker` y al thread hasta
    que terminen (p. ej. como atributos de instancia) — si Python los
    recolecta antes, Qt puede crashear.
    """
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    thread.finished.connect(thread.deleteLater)
    return thread
