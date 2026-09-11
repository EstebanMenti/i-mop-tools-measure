"""Escribe el reporte de medicion en disco (JSON + Markdown).

Ver docs/plan-implementacion.md Fase F5 y docs/formato-reporte.md para el
esquema completo. Los archivos se escriben con `encoding="utf-8"`
explicito, asi que a diferencia de la salida a terminal (`app/cli.py`,
ver CLAUDE.md seccion 2) pueden usar acentos, flechas y emoji sin
restriccion.
"""

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from imop_measure.report.build import DEFAULT_TOLERANCE_CM, summarize
from imop_measure.report.models import PairResult

_ESTADO_ICONO = {"PASS": "✅", "FAIL": "⚠️", "ERROR": "❌"}


def write_reports(
    results: list[PairResult],
    *,
    sala_id: str,
    sala_nombre: str | None = None,
    samples: int | None = None,
    tolerance_cm: float = DEFAULT_TOLERANCE_CM,
    report_dir: Path,
) -> tuple[Path, Path]:
    """Escribe `reports/medicion-<sala_id>-<YYYYMMDD-HHMMSS>.json` y `.md`.

    `samples`/`tolerance_cm` son solo para mostrar en el encabezado del
    reporte (los parámetros ya se aplicaron antes, en
    `report.build.build_results`) — si se omite `samples`, se toma de la
    primera fila (`n_samples_requested`).

    Returns:
        `(json_path, md_path)`.
    """
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base_name = f"medicion-{sala_id}-{timestamp}"
    json_path = report_dir / f"{base_name}.json"
    md_path = report_dir / f"{base_name}.md"

    ahora = datetime.now().astimezone()
    resumen = summarize(results)
    if samples is None and results:
        samples = results[0].n_samples_requested

    payload = {
        "ambiente": sala_id,
        "ambiente_nombre": sala_nombre,
        "fecha": ahora.isoformat(),
        "parametros": {
            "muestras_por_direccion": samples,
            "tolerancia_cm": tolerance_cm,
        },
        "resumen": resumen,
        "resultados": [asdict(result) for result in results],
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(
        _render_markdown(
            results,
            sala_id=sala_id,
            sala_nombre=sala_nombre,
            fecha=ahora,
            samples=samples,
            tolerance_cm=tolerance_cm,
            resumen=resumen,
        ),
        encoding="utf-8",
    )
    return json_path, md_path


def _render_markdown(
    results: list[PairResult],
    *,
    sala_id: str,
    sala_nombre: str | None,
    fecha: datetime,
    samples: int | None,
    tolerance_cm: float,
    resumen: dict[str, int],
) -> str:
    titulo_sala = f"{sala_nombre} (ID {sala_id})" if sala_nombre else f"Sala {sala_id}"
    fecha_legible = fecha.strftime("%d/%m/%Y %H:%M:%S UTC%z")

    lines = [
        f"# Reporte de Medición de Distancia UWB — {titulo_sala}",
        "",
        f"**Fecha y hora de generación:** {fecha_legible}",
        f"**Ambiente:** {titulo_sala}",
    ]
    if samples is not None:
        lines.append(f"**Muestras por dirección:** {samples}")
    lines.append(f"**Criterios:** tolerancia ±{tolerance_cm:.1f} cm para PASS/FAIL")
    lines += ["", "---", "", "## Resumen ejecutivo", ""]
    lines += _render_resumen_table(resumen)
    lines += ["", "## Detalle de mediciones", ""]
    lines += _render_detalle_table(results)

    a_revisar = [r for r in results if r.estado != "PASS"]
    if a_revisar:
        lines += ["", "## Mediciones que requieren revisión", ""]
        for result in a_revisar:
            lines.append(_render_revision_item(result))

    return "\n".join(lines) + "\n"


def _render_resumen_table(resumen: dict[str, int]) -> list[str]:
    return [
        "| Total mediciones | ✅ PASS | ⚠️ FAIL | ❌ ERROR |",
        "|---|---|---|---|",
        f"| {resumen['total']} | {resumen['pass']} | {resumen['fail']} | {resumen['error']} |",
    ]


def _render_detalle_table(results: list[PairResult]) -> list[str]:
    lines = [
        "| # | Dirección | Calculada (m) | Promedio (m) | Moda (m) | Mínimo (m) | "
        "Máximo (m) | Desviación (m) | Diferencia (m) | Diferencia (%) | Estado |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, result in enumerate(results, start=1):
        lines.append(f"| {i} | {_render_row(result)} |")
    return lines


def _fmt_m(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "—"


def _render_row(result: PairResult) -> str:
    direccion = f"{result.initiator} → {result.responder}"
    diff_m = f"{result.diff_m:+.3f}" if result.diff_m is not None else "—"
    diff_pct = f"{result.diff_pct:+.1f}%" if result.diff_pct is not None else "—"
    icono = _ESTADO_ICONO[result.estado]
    return (
        f"{direccion} | {result.distance_calc_m:.3f} | {_fmt_m(result.distance_measured_m)} | "
        f"{_fmt_m(result.mode_measured_m)} | {_fmt_m(result.min_measured_m)} | "
        f"{_fmt_m(result.max_measured_m)} | {_fmt_m(result.std_measured_m)} | "
        f"{diff_m} | {diff_pct} | {icono} {result.estado}"
    )


def _render_revision_item(result: PairResult) -> str:
    detalle = f" — {result.detalle}" if result.detalle else ""
    return (
        f"- **{result.initiator} → {result.responder}** "
        f"({_ESTADO_ICONO[result.estado]} {result.estado}): "
        f"{result.n_samples_success}/{result.n_samples_requested} muestras SUCCESS"
        f"{detalle}"
    )
