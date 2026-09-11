"""Tests de imop_measure.report.write.write_reports — no requieren hardware."""

import json
from pathlib import Path

from imop_measure.report.models import PairResult
from imop_measure.report.write import write_reports

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
FAIL_RESULT = PairResult(
    initiator="UWB-Node-11",
    responder="UWB-Node-12",
    distance_calc_m=5.0,
    distance_measured_m=5.4,
    diff_m=0.4,
    diff_pct=8.0,
    n_samples_success=10,
    n_samples_requested=10,
    estado="FAIL",
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
    detalle="sin mediciones SUCCESS recibidas",
)


def test_write_reports_creates_both_files_with_expected_names(tmp_path: Path) -> None:
    json_path, md_path = write_reports([PASS_RESULT], sala_id="20", report_dir=tmp_path)

    assert json_path.exists()
    assert md_path.exists()
    assert json_path.name.startswith("medicion-20-")
    assert json_path.suffix == ".json"
    assert md_path.suffix == ".md"
    assert json_path.stem == md_path.stem


def test_write_reports_json_content(tmp_path: Path) -> None:
    json_path, _ = write_reports(
        [PASS_RESULT, ERROR_RESULT],
        sala_id="20",
        sala_nombre="Sala 20 - Configuración Real",
        samples=10,
        tolerance_cm=5.0,
        report_dir=tmp_path,
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert payload["ambiente"] == "20"
    assert payload["ambiente_nombre"] == "Sala 20 - Configuración Real"
    assert payload["parametros"] == {"muestras_por_direccion": 10, "tolerancia_cm": 5.0}
    assert payload["resumen"] == {"pass": 1, "fail": 0, "error": 1, "total": 2}
    assert len(payload["resultados"]) == 2
    assert payload["resultados"][0]["initiator"] == "UWB-Node-10"
    assert payload["resultados"][0]["min_measured_m"] == 4.97
    assert payload["resultados"][0]["max_measured_m"] == 5.03
    assert payload["resultados"][0]["mode_measured_m"] == 5.00
    assert payload["resultados"][1]["detalle"] == "sin mediciones SUCCESS recibidas"


def test_write_reports_json_infers_samples_from_first_result_if_not_given(tmp_path: Path) -> None:
    json_path, _ = write_reports([PASS_RESULT], sala_id="20", report_dir=tmp_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert payload["parametros"]["muestras_por_direccion"] == PASS_RESULT.n_samples_requested


def test_write_reports_markdown_has_title_date_and_executive_summary(tmp_path: Path) -> None:
    _, md_path = write_reports(
        [PASS_RESULT], sala_id="20", sala_nombre="Sala 20 - Configuración Real", report_dir=tmp_path
    )

    content = md_path.read_text(encoding="utf-8")

    assert content.startswith("# Reporte de Medición de Distancia UWB")
    assert "Sala 20 - Configuración Real" in content
    assert "**Fecha y hora de generación:**" in content
    assert "## Resumen ejecutivo" in content
    assert "## Detalle de mediciones" in content


def test_write_reports_markdown_shows_calc_measured_and_both_diffs(tmp_path: Path) -> None:
    _, md_path = write_reports([PASS_RESULT], sala_id="20", report_dir=tmp_path)

    content = md_path.read_text(encoding="utf-8")

    assert "UWB-Node-10 → UWB-Node-11" in content
    assert "5.000" in content  # calculada y medida
    assert "+0.000" in content  # diferencia en metros, con signo
    assert "+0.0%" in content  # diferencia en %, con signo


def test_write_reports_markdown_shows_std_min_max_mode(tmp_path: Path) -> None:
    _, md_path = write_reports([PASS_RESULT, ERROR_RESULT], sala_id="20", report_dir=tmp_path)

    content = md_path.read_text(encoding="utf-8")

    assert "Mínimo (m)" in content
    assert "Máximo (m)" in content
    assert "Moda (m)" in content
    assert "Desviación (m)" in content
    assert "4.970" in content  # PASS_RESULT.min_measured_m
    assert "5.030" in content  # PASS_RESULT.max_measured_m
    assert "0.021" in content  # PASS_RESULT.std_measured_m
    # ERROR_RESULT no junto muestras: las columnas muestran "-", no numeros.
    assert "| — | — | — | — | — | — | — | ❌ ERROR |" in content


def test_write_reports_markdown_pass_only_has_no_revision_section(tmp_path: Path) -> None:
    _, md_path = write_reports([PASS_RESULT], sala_id="20", report_dir=tmp_path)

    content = md_path.read_text(encoding="utf-8")

    assert "## Mediciones que requieren revisión" not in content


def test_write_reports_markdown_includes_revision_section_for_errors(tmp_path: Path) -> None:
    _, md_path = write_reports([PASS_RESULT, ERROR_RESULT], sala_id="20", report_dir=tmp_path)

    content = md_path.read_text(encoding="utf-8")

    assert "## Mediciones que requieren revisión" in content
    assert "sin mediciones SUCCESS recibidas" in content


def test_write_reports_markdown_includes_revision_section_for_fail(tmp_path: Path) -> None:
    _, md_path = write_reports([FAIL_RESULT], sala_id="20", report_dir=tmp_path)

    content = md_path.read_text(encoding="utf-8")

    assert "## Mediciones que requieren revisión" in content
    assert "UWB-Node-11 → UWB-Node-12" in content


def test_write_reports_creates_report_dir_if_missing(tmp_path: Path) -> None:
    nested_dir = tmp_path / "no_existe_todavia"

    json_path, _ = write_reports([PASS_RESULT], sala_id="20", report_dir=nested_dir)

    assert json_path.exists()
