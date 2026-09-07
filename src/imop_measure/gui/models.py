"""Modelo Qt para mostrar resultados de una campana en vivo, fila por fila.

Ver docs/plan-implementacion.md Fase F7.
"""

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QColor

from imop_measure.report.models import PairResult

_HEADERS = (
    "Iniciador",
    "Respondedor",
    "Calculada (m)",
    "Medida (m)",
    "Diferencia (m)",
    "Diferencia (%)",
    "Revisar",
    "Estado",
)

_ESTADO_COLOR = {
    "PASS": QColor("#2e7d32"),
    "FAIL": QColor("#b26a00"),
    "ERROR": QColor("#c62828"),
}


class CampaignResultsModel(QAbstractTableModel):
    """Tabla de `PairResult` de una campana (`ranging.campaign.run_campaign`).

    Se llena fila por fila a medida que llegan los resultados (vía
    `pair_measured`, ver `gui/worker.py`), no de una sola vez al final —
    mismo patrón que `dwm3001c_cli.gui.models.ValidationResultsModel`.
    """

    def __init__(self) -> None:
        super().__init__()
        self._results: list[PairResult] = []

    def add_result(self, result: PairResult) -> None:
        row = len(self._results)
        self.beginInsertRows(QModelIndex(), row, row)
        self._results.append(result)
        self.endInsertRows()

    def clear(self) -> None:
        self.beginResetModel()
        self._results = []
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._results)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_HEADERS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        return _HEADERS[section]

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid():
            return None
        result = self._results[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return _display_value(result, index.column())
        if role == Qt.ItemDataRole.ForegroundRole:
            return _ESTADO_COLOR.get(result.estado)
        return None


def _display_value(result: PairResult, column: int) -> str | None:
    if column == 0:
        return result.initiator
    if column == 1:
        return result.responder
    if column == 2:
        return f"{result.distance_calc_m:.3f}"
    if column == 3:
        if result.distance_measured_m is None:
            return "-"
        return f"{result.distance_measured_m:.3f}"
    if column == 4:
        return f"{result.diff_m:+.3f}" if result.diff_m is not None else "-"
    if column == 5:
        return f"{result.diff_pct:+.1f}%" if result.diff_pct is not None else "-"
    if column == 6:
        return "Si" if result.necesita_revision else "-"
    if column == 7:
        return result.estado
    return None
