"""
CLI for converting VOTable to Parquet, CSV, or ECSV with optional select and filter.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from pathlib import Path

import click
from tqdm import tqdm

from votpipe._parser import parse_votable
from votpipe.query import CompiledBatchQuery


def _detect_format(output_path: Path, explicit_format: str) -> str:
    """Return format string: parquet, csv, or ecsv. explicit_format 'auto' uses extension."""
    if explicit_format != "auto":
        return explicit_format
    s = output_path.name.lower()
    if s.endswith(".parquet"):
        return "parquet"
    if s.endswith(".ecsv.gz") or s.endswith(".ecsv.xz") or s.endswith(".ecsv"):
        return "ecsv"
    if s.endswith(".csv.gz") or s.endswith(".csv.xz") or s.endswith(".csv"):
        return "csv"
    click.echo(
        f"Unknown output extension '{output_path.suffix}'; defaulting to parquet.",
        err=True,
    )
    return "parquet"


def _default_output_path(input_path: str, format: str) -> str:
    path = Path(input_path)
    s = str(path)
    if s.endswith(".vot.gz"):
        base = s[:-7]
    elif s.endswith(".vot"):
        base = s[:-4]
    else:
        base = str(path.with_suffix(""))
    if format == "csv":
        return f"{base}.csv"
    if format == "ecsv":
        return f"{base}.ecsv"
    return f"{base}.parquet"


@contextmanager
def _progress_sink(on_batch):
    pbar = tqdm(unit=" rows", unit_scale=True)
    yield (
        lambda fields, rows: (pbar.update(len(rows)) or True) and on_batch(fields, rows)
    )
    pbar.close()


@click.group()
def cli() -> None:
    """VOTable streaming parser and converter."""


@cli.command()
@click.argument("input_file", type=click.Path(exists=True, path_type=Path))
@click.argument("output_file", type=click.Path(path_type=Path), required=False)
@click.option(
    "--select",
    default=None,
    help="Comma-separated column list to keep (e.g. source_id,ra,dec). Default: all columns.",
)
@click.option(
    "--where",
    default=None,
    help="Filter expression (e.g. parallax > 10 and phot_g_mean_mag < 15).",
)
@click.option(
    "--progress/--no-progress",
    default=True,
    help="Show a progress bar (requires tqdm).",
)
@click.option(
    "--format",
    "output_format",
    default="auto",
    type=click.Choice(["auto", "csv", "ecsv", "parquet"]),
    help="Output format (default: auto, detected from output file extension).",
)
@click.option(
    "--compression",
    default="zstd",
    type=click.Choice(["zstd", "snappy", "none"]),
    help="Parquet-only: compression codec (default: zstd). CSV/ECSV use .gz/.xz extension.",
)
@click.option(
    "--batch-size",
    default=8192,
    help="Max rows per batch (default: 8192).",
)
def convert(
    input_file: Path,
    output_file: Path | None,
    select: str | None,
    where: str | None,
    progress: bool,
    output_format: str,
    compression: str,
    batch_size: int,
) -> None:
    """Convert a VOTable to Parquet, CSV, or ECSV with optional column selection and filtering."""
    if output_file is None:
        format_for_path = output_format if output_format != "auto" else "parquet"
        output_file = Path(_default_output_path(str(input_file), format_for_path))
    else:
        output_file = Path(output_file)

    fmt = _detect_format(output_file, output_format)
    click.echo(f"Converting {input_file} -> {output_file} ...")

    with ExitStack() as stack:
        if fmt == "parquet":
            try:
                from votpipe.parquet import ParquetAdapter
            except ImportError as e:
                click.echo(
                    "Parquet output requires pyarrow. Install with: pip install votpipe[parquet]",
                    err=True,
                )
                raise SystemExit(1) from e
            adapter = stack.enter_context(
                ParquetAdapter(str(output_file), compression=compression)
            )
        elif fmt == "ecsv":
            from votpipe.csv import EcsvAdapter

            adapter = stack.enter_context(EcsvAdapter(str(output_file)))
        else:
            from votpipe.csv import CsvAdapter

            adapter = stack.enter_context(CsvAdapter(str(output_file)))

        sink = adapter.on_batch

        if progress:
            sink = stack.enter_context(_progress_sink(sink))

        if select or where:
            query = CompiledBatchQuery(
                sink,
                select=select or None,
                where=where or None,
            )
            stack.enter_context(query)
            sink = query.on_batch

        parse_votable(input_file, sink, batch_size=batch_size)

    click.echo("Done.")
