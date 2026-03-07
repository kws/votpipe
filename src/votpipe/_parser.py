"""
Streaming VOTable parser. Consumes XML via SAX and emits batches of row tuples.
Supports TABLEDATA, BINARY, and BINARY2 serializations.
"""

from __future__ import annotations

import base64
import gzip
import xml.sax
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import BinaryIO

from votpipe._decode import (
    build_struct_format,
    cast_tabledata_value,
    decode_binary2_row,
    decode_binary_row,
)

DEFAULT_BATCH_SIZE = 8192


@contextmanager
def _open_source(source: str | Path | BinaryIO) -> Iterator[BinaryIO]:
    """Yield a binary stream from a path or existing file-like object.

    If `source` is already a binary stream, it is yielded as-is and not closed here.
    If `source` is a path, it is opened and closed here.
    """
    if hasattr(source, "read"):
        with nullcontext(source):
            yield source
        return

    path = Path(source)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as fh:
        yield fh


class _SAXHandler(xml.sax.ContentHandler):
    """SAX handler that extracts FIELD definitions and emits decoded rows
    as batches of tuples via put_batch(fields, rows)."""

    def __init__(
        self,
        put_batch: Callable[[list[dict], list[tuple]], None],
        batch_size: int,
    ):
        self._put_batch = put_batch
        self._batch_size = batch_size
        self.fields: list[dict] = []
        self.format: str | None = None

        self._batch: list[tuple] = []

        # TABLEDATA state
        self._in_tabledata = False
        self._in_tr = False
        self._in_td = False
        self._current_row: list[str] = []
        self._cell_text: list[str] = []

        # BINARY/BINARY2 state
        self._in_stream = False
        self._b64_buffer = ""
        self._byte_buffer = bytearray()
        self._struct_fmt = ""
        self._null_mask_bytes = 0
        self._row_size = 0

    def _flush_batch(self) -> None:
        if self._batch:
            self._put_batch(self.fields, self._batch)
            self._batch = []

    def _append_row(self, row: tuple) -> None:
        self._batch.append(row)
        if len(self._batch) >= self._batch_size:
            self._flush_batch()

    def startElement(self, name, attrs):  # noqa: N802 (SAX API)
        local = name.split(":")[-1].split("}")[-1]

        if local == "FIELD":
            self.fields.append(
                {
                    "name": attrs.get("name", ""),
                    "datatype": attrs.get("datatype", "int"),
                    "arraysize": attrs.get("arraysize"),
                }
            )
        elif local == "TABLEDATA":
            self.format = "TABLEDATA"
            self._in_tabledata = True
        elif local == "BINARY":
            self.format = "BINARY"
        elif local == "BINARY2":
            self.format = "BINARY2"
        elif local == "TR":
            self._in_tr = True
            self._current_row = []
        elif local == "TD":
            self._in_td = True
            self._cell_text = []
        elif local == "STREAM":
            self._in_stream = True
            binary2 = self.format == "BINARY2"
            self._struct_fmt, self._null_mask_bytes, self._row_size = (
                build_struct_format(self.fields, binary2=binary2)
            )

    def endElement(self, name):  # noqa: N802 (SAX API)
        local = name.split(":")[-1].split("}")[-1]

        if local == "TABLEDATA":
            self._in_tabledata = False
            self._flush_batch()
        elif local == "TR":
            if (
                self._in_tabledata
                and self.format == "TABLEDATA"
                and self.fields
                and len(self._current_row) == len(self.fields)
            ):
                row = tuple(
                    cast_tabledata_value(raw, field["datatype"])
                    for field, raw in zip(self.fields, self._current_row, strict=True)
                )
                self._append_row(row)
            self._in_tr = False
        elif local == "TD":
            self._current_row.append("".join(self._cell_text).strip())
            self._in_td = False
            self._cell_text = []
        elif local == "STREAM":
            self._in_stream = False
            self._flush_batch()

    def characters(self, content):
        if self._in_td:
            self._cell_text.append(content)
        elif self._in_stream:
            self._b64_buffer += "".join(content.split())
            valid_len = (len(self._b64_buffer) // 4) * 4
            if valid_len > 0:
                chunk = self._b64_buffer[:valid_len]
                self._b64_buffer = self._b64_buffer[valid_len:]
                self._byte_buffer += base64.b64decode(chunk)
                self._extract_binary_rows()

    def _extract_binary_rows(self):
        while len(self._byte_buffer) >= self._row_size:
            row_bytes = bytes(self._byte_buffer[: self._row_size])
            self._byte_buffer = self._byte_buffer[self._row_size :]
            if self.format == "BINARY2":
                row = decode_binary2_row(
                    self._struct_fmt,
                    self._null_mask_bytes,
                    row_bytes,
                )
            else:
                row = decode_binary_row(
                    self._struct_fmt,
                    row_bytes,
                )
            self._append_row(row)


def parse_votable(
    source: str | Path | BinaryIO,
    on_batch: Callable[[list[dict], list[tuple]], None],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> None:
    """Parse a VOTable and call on_batch(fields, rows) for each batch.

    Args:
        source: File path, gzipped path, or binary stream.
        on_batch: Called with (fields, rows) where fields is the stable list of
            field dicts and rows is a list of tuples (values in field order).
        batch_size: Max rows per batch (default 8192).
    """
    with _open_source(source) as f:
        handler = _SAXHandler(on_batch, batch_size)
        xml.sax.parse(f, handler)
