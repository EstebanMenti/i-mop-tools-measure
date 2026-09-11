"""Tests de imop_measure.app.cli — no requieren hardware."""

import json
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from imop_measure.app.cli import app
from imop_measure.config.models import Ambiente, Anchor
from imop_measure.errors import ConfigError
from imop_measure.ranging.pair_runner import MeasuredPair
from imop_measure.ranging.session import SessionParams

runner = CliRunner()

ENVIRONMENT_TOML = """
[sala]
id = "99"

[[anchors]]
key = "a"
nombre = "A"
mac = "00:00:00:00:00:01"
uwb_addr = "00:01"
posicion = [0.0, 0.0, 0.0]
tiempo_prendido = "60s"

[[anchors]]
key = "b"
nombre = "B"
mac = "00:00:00:00:00:02"
uwb_addr = "00:02"
posicion = [3.0, 4.0, 0.0]
tiempo_prendido = "60s"
"""


def _fake_measured(initiator: Anchor, responder: Anchor) -> MeasuredPair:
    return MeasuredPair(
        initiator=initiator,
        responder=responder,
        distance_cm_samples=[500],
        mean_cm=500.0,
        std_cm=0.0,
        n_success=1,
        n_requested=1,
        error=None,
    )


def _fake_run_campaign(
    ambiente: Ambiente,
    *,
    session: SessionParams,
    n_samples: int,
    on_pair_done: Callable[[MeasuredPair], None] | None = None,
) -> list[MeasuredPair]:
    results = []
    for initiator, responder in [
        (ambiente.anchors[0], ambiente.anchors[1]),
        (ambiente.anchors[1], ambiente.anchors[0]),
    ]:
        result = _fake_measured(initiator, responder)
        if on_pair_done is not None:
            on_pair_done(result)
        results.append(result)
    return results


def test_run_generates_report(tmp_path: Path) -> None:
    toml_path = tmp_path / "sala_99.toml"
    toml_path.write_text(ENVIRONMENT_TOML, encoding="utf-8")
    report_dir = tmp_path / "reports"

    with patch("imop_measure.app.cli.run_campaign", side_effect=_fake_run_campaign):
        result = runner.invoke(
            app, ["run", "--environment", str(toml_path), "--report-dir", str(report_dir)]
        )

    assert result.exit_code == 0, result.output
    json_files = list(report_dir.glob("medicion-99-*.json"))
    assert len(json_files) == 1
    payload = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert payload["ambiente"] == "99"
    assert payload["resumen"]["total"] == 2
    assert payload["resumen"]["pass"] == 2  # distancia calculada 5.0m == medida 5.0m


def test_run_one_to_many_flag_uses_one_to_many_campaign(tmp_path: Path) -> None:
    """`--one-to-many` debe llamar `run_campaign_one_to_many`, no
    `run_campaign` -- puramente de enrutamiento, no reimplementa nada."""
    toml_path = tmp_path / "sala_99.toml"
    toml_path.write_text(ENVIRONMENT_TOML, encoding="utf-8")
    report_dir = tmp_path / "reports"

    with (
        patch(
            "imop_measure.app.cli.run_campaign_one_to_many", side_effect=_fake_run_campaign
        ) as mock_one_to_many,
        patch("imop_measure.app.cli.run_campaign") as mock_default,
    ):
        result = runner.invoke(
            app,
            [
                "run",
                "--environment",
                str(toml_path),
                "--report-dir",
                str(report_dir),
                "--one-to-many",
            ],
        )

    assert result.exit_code == 0, result.output
    mock_one_to_many.assert_called_once()
    mock_default.assert_not_called()


def test_run_missing_environment_file_fails(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", "--environment", str(tmp_path / "no_existe.toml")])

    assert result.exit_code != 0


def test_run_translates_measure_error_to_exit_code_1(tmp_path: Path) -> None:
    toml_path = tmp_path / "sala_99.toml"
    toml_path.write_text('[sala]\nid = "otra"\n', encoding="utf-8")  # id no coincide -> ConfigError

    result = runner.invoke(app, ["run", "--environment", str(toml_path)])

    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "no coincide con el nombre de archivo" in result.output


def test_run_verbose_reraises_original_exception(tmp_path: Path) -> None:
    toml_path = tmp_path / "sala_99.toml"
    toml_path.write_text('[sala]\nid = "otra"\n', encoding="utf-8")

    result = runner.invoke(app, ["run", "--environment", str(toml_path), "--verbose"])

    assert result.exit_code != 0
    assert isinstance(result.exception, ConfigError)


def test_run_respects_custom_tolerance(tmp_path: Path) -> None:
    toml_path = tmp_path / "sala_99.toml"
    toml_path.write_text(ENVIRONMENT_TOML, encoding="utf-8")
    report_dir = tmp_path / "reports"

    def fake_run_campaign_slightly_off(
        ambiente: Ambiente, *, session: SessionParams, n_samples: int, on_pair_done: object = None
    ) -> list[MeasuredPair]:
        # Distancia calculada real: 5.0m = 500cm. Medimos 510cm (10cm de error).
        return [
            MeasuredPair(
                initiator=ambiente.anchors[0],
                responder=ambiente.anchors[1],
                distance_cm_samples=[510],
                mean_cm=510.0,
                std_cm=0.0,
                n_success=1,
                n_requested=1,
                error=None,
            )
        ]

    with patch("imop_measure.app.cli.run_campaign", side_effect=fake_run_campaign_slightly_off):
        result = runner.invoke(
            app,
            [
                "run",
                "--environment",
                str(toml_path),
                "--report-dir",
                str(report_dir),
                "--tolerance-cm",
                "20",
            ],
        )

    assert result.exit_code == 0, result.output
    json_files = list(report_dir.glob("medicion-99-*.json"))
    payload = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert payload["resultados"][0]["estado"] == "PASS"  # 10cm de error, tolerancia 20cm
