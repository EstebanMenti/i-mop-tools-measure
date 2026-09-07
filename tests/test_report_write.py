"""Tests de imop_measure.report.write.write_reports — no requieren hardware."""

import json
from pathlib import Path

from imop_measure.report.models import PairResult
from imop_measure.report.write import write_reports

PASS_RESULT = PairResult(
    initiator="uwb_node_10",
    responder="uwb_node_11",
    distance_calc_m=5.0,
    distance_measured_m=5.0,
    error_abs_cm=0.0,
    error_pct=0.0,
    n_samples_success=10,
    n_samples_requested=10,
    estado="PASS",
)
ERROR_RESULT = PairResult(
    initiator="uwb_node_11",
    responder="uwb_node_10",
    distance_calc_m=5.0,
    distance_measured_m=None,
    error_abs_cm=None,
    error_pct=None,
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
    json_path, _ = write_reports([PASS_RESULT, ERROR_RESULT], sala_id="20", report_dir=tmp_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert payload["ambiente"] == "20"
    assert payload["resumen"] == {"pass": 1, "fail": 0, "error": 1, "total": 2}
    assert len(payload["resultados"]) == 2
    assert payload["resultados"][0]["initiator"] == "uwb_node_10"
    assert payload["resultados"][1]["detalle"] == "sin mediciones SUCCESS recibidas"


def test_write_reports_markdown_pass_only_has_no_failure_section(tmp_path: Path) -> None:
    _, md_path = write_reports([PASS_RESULT], sala_id="20", report_dir=tmp_path)

    content = md_path.read_text(encoding="utf-8")

    assert "**1 PASS · 0 FAIL · 0 ERROR** (total 1)" in content
    assert "uwb_node_10 → uwb_node_11" in content
    assert "## Mediciones con error o fuera de tolerancia" not in content


def test_write_reports_markdown_includes_failure_section_when_present(tmp_path: Path) -> None:
    _, md_path = write_reports([PASS_RESULT, ERROR_RESULT], sala_id="20", report_dir=tmp_path)

    content = md_path.read_text(encoding="utf-8")

    assert "**1 PASS · 0 FAIL · 1 ERROR** (total 2)" in content
    assert "## Mediciones con error o fuera de tolerancia" in content
    assert "sin mediciones SUCCESS recibidas" in content


def test_write_reports_creates_report_dir_if_missing(tmp_path: Path) -> None:
    nested_dir = tmp_path / "no_existe_todavia"

    json_path, _ = write_reports([PASS_RESULT], sala_id="20", report_dir=nested_dir)

    assert json_path.exists()
