"""Tests de imop_measure.gui.models.CampaignResultsModel — no requieren hardware."""

from PySide6.QtCore import Qt

from imop_measure.gui.models import CampaignResultsModel
from imop_measure.report.models import PairResult

PASS_RESULT = PairResult(
    initiator="UWB-Node-10",
    responder="UWB-Node-11",
    distance_calc_m=5.0,
    distance_measured_m=5.0,
    diff_m=0.0,
    diff_pct=0.0,
    n_samples_success=10,
    n_samples_requested=10,
    estado="PASS",
    std_measured_m=0.021,
    min_measured_m=4.97,
    max_measured_m=5.03,
    mode_measured_m=5.00,
)
ERROR_RESULT = PairResult(
    initiator="UWB-Node-11",
    responder="UWB-Node-10",
    distance_calc_m=5.0,
    distance_measured_m=None,
    diff_m=None,
    diff_pct=None,
    n_samples_success=0,
    n_samples_requested=10,
    estado="ERROR",
    detalle="timeout",
)


def test_model_starts_empty(qtbot: object) -> None:
    model = CampaignResultsModel()

    assert model.rowCount() == 0
    assert model.columnCount() == 11


def test_add_result_appends_row(qtbot: object) -> None:
    model = CampaignResultsModel()

    model.add_result(PASS_RESULT)

    assert model.rowCount() == 1
    index = model.index(0, 0)
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == "UWB-Node-10"


def test_data_shows_dash_for_missing_measurement(qtbot: object) -> None:
    model = CampaignResultsModel()
    model.add_result(ERROR_RESULT)

    index = model.index(0, 3)  # columna "Medida (m)"

    assert model.data(index) == "-"


def test_data_shows_dash_for_missing_min_max_mode_std(qtbot: object) -> None:
    model = CampaignResultsModel()
    model.add_result(ERROR_RESULT)

    for column in (4, 5, 6, 7):  # Mínimo, Máximo, Moda, Desviación
        assert model.data(model.index(0, column)) == "-"


def test_data_formats_min_max_mode_std(qtbot: object) -> None:
    model = CampaignResultsModel()
    model.add_result(PASS_RESULT)

    assert model.data(model.index(0, 4)) == "4.970"  # Mínimo (m)
    assert model.data(model.index(0, 5)) == "5.030"  # Máximo (m)
    assert model.data(model.index(0, 6)) == "5.000"  # Moda (m)
    assert model.data(model.index(0, 7)) == "0.021"  # Desviación (m)


def test_data_formats_signed_diff(qtbot: object) -> None:
    model = CampaignResultsModel()
    model.add_result(PASS_RESULT)

    diff_m_index = model.index(0, 8)
    diff_pct_index = model.index(0, 9)

    assert model.data(diff_m_index) == "+0.000"
    assert model.data(diff_pct_index) == "+0.0%"


def test_clear_resets_rows(qtbot: object) -> None:
    model = CampaignResultsModel()
    model.add_result(PASS_RESULT)

    model.clear()

    assert model.rowCount() == 0


def test_header_data(qtbot: object) -> None:
    model = CampaignResultsModel()

    assert model.headerData(0, Qt.Orientation.Horizontal) == "Iniciador"
    assert model.headerData(7, Qt.Orientation.Horizontal) == "Desviación (m)"
    assert model.headerData(10, Qt.Orientation.Horizontal) == "Estado"


def test_header_tooltip_explains_std_measured_column(qtbot: object) -> None:
    model = CampaignResultsModel()

    tooltip = model.headerData(7, Qt.Orientation.Horizontal, role=Qt.ItemDataRole.ToolTipRole)

    assert "dispersión" in tooltip
    assert "NO es la diferencia" in tooltip


def test_header_tooltip_present_for_every_column(qtbot: object) -> None:
    model = CampaignResultsModel()

    for column in range(model.columnCount()):
        tooltip = model.headerData(
            column, Qt.Orientation.Horizontal, role=Qt.ItemDataRole.ToolTipRole
        )
        assert tooltip, f"columna {column} sin tooltip"


def test_header_data_returns_none_for_vertical_orientation(qtbot: object) -> None:
    model = CampaignResultsModel()

    assert model.headerData(0, Qt.Orientation.Vertical) is None
    assert model.headerData(0, Qt.Orientation.Vertical, role=Qt.ItemDataRole.ToolTipRole) is None
