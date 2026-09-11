"""CLI de imop_measure (comando `imop-measure`).

Ver docs/plan-implementacion.md Fase F6.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from imop_measure.config.loader import load_ambiente
from imop_measure.errors import MeasureError
from imop_measure.ranging.campaign import run_campaign, run_campaign_one_to_many
from imop_measure.ranging.pair_runner import MeasuredPair
from imop_measure.ranging.session import SessionParams
from imop_measure.report.build import DEFAULT_TOLERANCE_CM, build_results
from imop_measure.report.models import PairResult
from imop_measure.report.write import write_reports

app = typer.Typer(help="Mide distancia real entre nodos UWB y la compara contra la calculada.")
console = Console()

DEFAULT_SAMPLES = 30  # TODO(confirmar-con-usuario): valor sugerido, ver docs/plan-implementacion.md


@app.callback()
def _callback() -> None:
    """Punto de entrada del grupo de comandos.

    Necesario para que Typer exija el nombre del subcomando (`run`) incluso
    mientras haya un único comando registrado — sin esto, Typer colapsa un
    Typer app de un solo comando a invocación directa sin nombre.
    """


@app.command()
def run(
    environment: Annotated[
        Path,
        typer.Option(
            "--environment",
            exists=True,
            dir_okay=False,
            help="Archivo TOML del ambiente (ej. environments/sala_20.toml).",
        ),
    ],
    samples: Annotated[
        int,
        typer.Option("--samples", min=1, help="Muestras SUCCESS a juntar por dirección medida."),
    ] = DEFAULT_SAMPLES,
    tolerance_cm: Annotated[
        float,
        typer.Option("--tolerance-cm", help="Tolerancia de error (cm) para marcar PASS/FAIL."),
    ] = DEFAULT_TOLERANCE_CM,
    report_dir: Annotated[
        Path, typer.Option("--report-dir", help="Carpeta donde escribir el reporte.")
    ] = Path("reports"),
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Muestra el traceback completo ante un error, en vez de un mensaje corto.",
        ),
    ] = False,
    one_to_many: Annotated[
        bool,
        typer.Option(
            "--one-to-many",
            help=(
                "[Experimental] Mide cada nodo iniciador contra todos los demas a la vez "
                "en una sola sesion FiRa uno-a-muchos (-MULTI), en vez de una conexion BLE "
                "por direccion. Mucho mas rapido, pero con muchas menos horas de prueba "
                "contra hardware real que el modo por defecto — ver "
                "docs/investigacion-desviaciones-uwb-2026-09-10.md."
            ),
        ),
    ] = False,
) -> None:
    """Mide la distancia real entre todos los nodos del ambiente (ambas
    direcciones) y genera un reporte comparándola contra la calculada."""
    with _error_boundary(verbose=verbose):
        ambiente = load_ambiente(environment)
        n_directed_pairs = len(ambiente.anchors) * (len(ambiente.anchors) - 1)
        modo = " (modo uno-a-muchos, experimental)" if one_to_many else ""
        console.print(
            f"Ambiente sala {ambiente.id}: {len(ambiente.anchors)} anclas activas, "
            f"{n_directed_pairs} direcciones a medir{modo}."
        )

        def on_pair_done(result: MeasuredPair) -> None:
            estado = "ok" if result.error is None else f"[red]error: {result.error}[/red]"
            console.print(
                f"  {result.initiator.nombre} -> {result.responder.nombre}: "
                f"{result.n_success}/{result.n_requested} muestras - {estado}"
            )

        campaign_fn = run_campaign_one_to_many if one_to_many else run_campaign
        with console.status(f"Midiendo {n_directed_pairs} direcciones..."):
            measured_pairs = campaign_fn(
                ambiente, session=SessionParams(), n_samples=samples, on_pair_done=on_pair_done
            )

        results = build_results(measured_pairs, tolerance_cm=tolerance_cm)
        json_path, md_path = write_reports(
            results,
            sala_id=ambiente.id,
            sala_nombre=ambiente.nombre,
            samples=samples,
            tolerance_cm=tolerance_cm,
            report_dir=report_dir,
        )

        _print_summary(results)
        console.print(f"\nReporte: [bold]{md_path}[/bold] (y {json_path.name})")


def _print_summary(results: list[PairResult]) -> None:
    table = Table(title="Resumen de medición")
    table.add_column("Dirección")
    table.add_column("Calculada (m)", justify="right")
    table.add_column("Promedio (m)", justify="right")
    table.add_column("Moda (m)", justify="right")
    table.add_column("Mínimo (m)", justify="right")
    table.add_column("Máximo (m)", justify="right")
    table.add_column("Desviación (m)", justify="right")
    table.add_column("Diferencia (m)", justify="right")
    table.add_column("Diferencia (%)", justify="right")
    table.add_column("Estado")
    for result in results:
        medida = (
            f"{result.distance_measured_m:.3f}" if result.distance_measured_m is not None else "-"
        )
        minimo = f"{result.min_measured_m:.3f}" if result.min_measured_m is not None else "-"
        maximo = f"{result.max_measured_m:.3f}" if result.max_measured_m is not None else "-"
        moda = f"{result.mode_measured_m:.3f}" if result.mode_measured_m is not None else "-"
        desviacion = f"{result.std_measured_m:.3f}" if result.std_measured_m is not None else "-"
        diff_m = f"{result.diff_m:+.3f}" if result.diff_m is not None else "-"
        diff_pct = f"{result.diff_pct:+.1f}%" if result.diff_pct is not None else "-"
        estilo = {"PASS": "green", "FAIL": "yellow", "ERROR": "red"}[result.estado]
        table.add_row(
            f"{result.initiator} -> {result.responder}",
            f"{result.distance_calc_m:.3f}",
            medida,
            moda,
            minimo,
            maximo,
            desviacion,
            diff_m,
            diff_pct,
            f"[{estilo}]{result.estado}[/{estilo}]",
        )
    console.print(table)


@contextmanager
def _error_boundary(*, verbose: bool) -> Iterator[None]:
    """Traduce `MeasureError` a un mensaje legible y exit code 1.

    Con `--verbose` deja pasar la excepción original (traceback completo)
    en vez de convertirla — útil para diagnosticar un bug, no para uso
    normal.
    """
    try:
        yield
    except MeasureError as exc:
        if verbose:
            raise
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


def main() -> None:
    app()


if __name__ == "__main__":
    main()
