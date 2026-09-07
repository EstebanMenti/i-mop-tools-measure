"""Escribe el reporte de medicion en disco (JSON + Markdown).

Ver docs/plan-implementacion.md Fase F5.
"""

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from imop_measure.report.build import summarize
from imop_measure.report.models import PairResult


def write_reports(
    results: list[PairResult], *, sala_id: str, report_dir: Path
) -> tuple[Path, Path]:
    """Escribe `reports/medicion-<sala_id>-<YYYYMMDD-HHMMSS>.json` y `.md`.

    Mismo patrón que `validation/report.py` del repo hermano: encabezado
    con metadata, una línea en negrita con el resumen, una tabla con todos
    los resultados, y una sección aparte solo para los que no son `PASS`.

    Returns:
        `(json_path, md_path)`.
    """
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base_name = f"medicion-{sala_id}-{timestamp}"
    json_path = report_dir / f"{base_name}.json"
    md_path = report_dir / f"{base_name}.md"

    fecha_iso = datetime.now().astimezone().isoformat()
    resumen = summarize(results)

    payload = {
        "ambiente": sala_id,
        "fecha": fecha_iso,
        "resumen": resumen,
        "resultados": [asdict(result) for result in results],
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(
        _render_markdown(results, sala_id=sala_id, fecha_iso=fecha_iso, resumen=resumen),
        encoding="utf-8",
    )
    return json_path, md_path


def _render_markdown(
    results: list[PairResult], *, sala_id: str, fecha_iso: str, resumen: dict[str, int]
) -> str:
    lines = [
        "# Reporte de medición de distancia UWB",
        "",
        f"> **Ambiente:** sala {sala_id} · **Fecha:** {fecha_iso}",
        "",
        f"**{resumen['pass']} PASS · {resumen['fail']} FAIL · "
        f"{resumen['error']} ERROR** (total {resumen['total']})",
        "",
        "| Par | Distancia calculada (m) | Distancia medida (m) | "
        "Error (cm) | Error (%) | Estado |",
        "|---|---|---|---|---|---|",
    ]
    for result in results:
        lines.append(_render_row(result))

    fallos = [result for result in results if result.estado != "PASS"]
    if fallos:
        lines += ["", "## Mediciones con error o fuera de tolerancia", ""]
        for result in fallos:
            lines.append(_render_fallo(result))

    return "\n".join(lines) + "\n"


def _render_row(result: PairResult) -> str:
    par = f"{result.initiator} → {result.responder}"
    medida = f"{result.distance_measured_m:.3f}" if result.distance_measured_m is not None else "—"
    error_cm = f"{result.error_abs_cm:.1f}" if result.error_abs_cm is not None else "—"
    error_pct = f"{result.error_pct:.1f}%" if result.error_pct is not None else "—"
    return (
        f"| {par} | {result.distance_calc_m:.3f} | {medida} | "
        f"{error_cm} | {error_pct} | {result.estado} |"
    )


def _render_fallo(result: PairResult) -> str:
    detalle = f" — {result.detalle}" if result.detalle else ""
    return (
        f"- **{result.initiator} → {result.responder}** ({result.estado}): "
        f"{result.n_samples_success}/{result.n_samples_requested} muestras SUCCESS{detalle}"
    )
