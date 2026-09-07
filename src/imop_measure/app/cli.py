"""CLI de imop_measure (comando `imop-measure`).

Esqueleto de la Fase F0 — el comando `run` end-to-end se implementa en la
Fase F6 (ver docs/plan-implementacion.md). Este stub solo deja el entry
point instalable y funcionando.
"""

import typer

app = typer.Typer(help="Mide distancia real entre nodos UWB y la compara contra la calculada.")


@app.callback()
def _callback() -> None:
    """Punto de entrada del grupo de comandos.

    Necesario para que Typer exija el nombre del subcomando (`run`) incluso
    mientras haya un único comando registrado — sin esto, Typer colapsa un
    Typer app de un solo comando a invocación directa sin nombre.
    """


@app.command()
def run() -> None:
    """Corre una campaña de medición completa sobre un ambiente (Fase F6, aún no implementada)."""
    typer.echo("Aún no implementado — ver docs/plan-implementacion.md, Fase F6.")
    raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
