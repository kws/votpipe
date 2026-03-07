"""
Compiled batch query / mutator for streaming VOTable pipelines.

Intended usage:

    parquet = ParquetAdapter(...)
    query = CompiledBatchQuery(
        parquet.on_batch,
        select="source_id,ra,dec,parallax",
        where="parallax > 10 and phot_g_mean_mag < 15",
    )

    parse_votable(source, query.on_batch)
    query.close()

Design goals:
- compile once on first batch, after FIELD definitions are known
- bind column names to tuple indices once
- generate a single fused batch function for filter + projection
- avoid per-row dict creation or name lookups
- keep the supported expression language deliberately small and safe

Supported `where` syntax:
- column names, e.g. parallax
- numeric / string / bool / None constants
- boolean operators: and, or, not
- comparisons: ==, !=, <, <=, >, >=, is None, is not None
- chained comparisons: 0 < parallax <= 10

Notes:
- comparisons against nullable columns are compiled null-safe:
    parallax > 10
  becomes effectively:
    (row[idx] is not None) and (row[idx] > 10)
- use `is None` / `is not None` rather than `== None`
- arithmetic is intentionally not supported in this first version
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from votpipe._compile import compile_row_transform

Field = dict[str, Any]
Row = tuple[Any, ...]
BatchCallback = Callable[[list[Field], list[Row]], None]


class CompiledBatchQuery:
    """
    Compile select/where once against parser FIELD metadata, then apply
    the compiled transform to each incoming batch of row tuples.

    Parameters
    ----------
    sink_on_batch:
        Downstream callback receiving transformed (fields, rows).
        Typically something like `parquet.on_batch`.
    select:
        Comma-separated column list, e.g. "source_id,ra,dec".
        If omitted, all columns are passed through.
    where:
        Restricted expression string, e.g. "parallax > 10 and phot_g_mean_mag < 15".
        If omitted, no filtering is applied.
    emit_empty_first_batch:
        If True, the downstream sink is called once on the first batch even if the
        transformed rows are empty. Useful only if a sink needs output-field metadata
        even when no rows survive filtering.
    """

    def __init__(
        self,
        sink_on_batch: BatchCallback,
        *,
        select: str | None = None,
        where: str | None = None,
        emit_empty_first_batch: bool = False,
    ) -> None:
        self._sink_on_batch = sink_on_batch
        self._sink_close = _discover_close(sink_on_batch)

        self._select = select
        self._where = where
        self._emit_empty_first_batch = emit_empty_first_batch

        self._compiled = False
        self._schema_emitted = False

        self._field_signature: tuple[tuple[str, str, str | None], ...] | None = None
        self._out_fields: list[Field] | None = None
        self._transform_batch: Callable[[list[Row]], list[Row]] | None = None

    def on_batch(self, fields: list[Field], rows: list[Row]) -> None:
        """Receive parser batches, compile on first batch, then forward transformed rows."""
        if not self._compiled:
            self._compile(fields)
        else:
            self._check_fields_unchanged(fields)

        assert self._out_fields is not None
        assert self._transform_batch is not None

        out_rows = self._transform_batch(rows)

        if out_rows or not self._schema_emitted and self._emit_empty_first_batch:
            self._sink_on_batch(self._out_fields, out_rows)
            self._schema_emitted = True

    def close(self) -> None:
        """Forward close() to the downstream sink owner if available."""
        if self._sink_close is not None:
            self._sink_close()

    def _compile(self, fields: list[Field]) -> None:
        self._field_signature = _make_field_signature(fields)
        self._out_fields, self._transform_batch = compile_row_transform(
            fields,
            select=self._select,
            where=self._where,
        )
        self._compiled = True

    def _check_fields_unchanged(self, fields: list[Field]) -> None:
        sig = _make_field_signature(fields)
        if sig != self._field_signature:
            raise ValueError(
                "Incoming field definitions changed after query compilation"
            )

    def __enter__(self) -> CompiledBatchQuery:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def _make_field_signature(
    fields: list[Field],
) -> tuple[tuple[str, str, str | None], ...]:
    return tuple(
        (
            str(field.get("name", "")),
            str(field.get("datatype", "")),
            field.get("arraysize"),
        )
        for field in fields
    )


def _discover_close(sink_on_batch: BatchCallback) -> Callable[[], None] | None:
    owner = getattr(sink_on_batch, "__self__", None)
    if owner is None:
        return None
    close = getattr(owner, "close", None)
    return close if callable(close) else None
