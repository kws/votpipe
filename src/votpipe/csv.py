from __future__ import annotations

import csv
import gzip
import json
import lzma
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TextIO


def _open_text_output(path: str | Path, *, encoding: str = "utf-8") -> TextIO:
    path = Path(path)
    if path.suffix == ".gz":
        return gzip.open(path, "wt", encoding=encoding, newline="")
    if path.suffix == ".xz":
        return lzma.open(path, "wt", encoding=encoding, newline="")
    return path.open("w", encoding=encoding, newline="")


class DelimitedTextAdapter:
    """
    Shared writer for CSV-like formats. Accepts batches of row tuples from the parser.
    Use as the on_batch callback: parse_votable(source, adapter.on_batch).
    """

    def __init__(
        self,
        filename: str | Path,
        *,
        encoding: str = "utf-8",
        delimiter: str = ",",
    ) -> None:
        self.filename = filename
        self.fieldnames: list[str] | None = None
        self.encoding = encoding
        self.delimiter = delimiter

        self._file: TextIO | None = None
        self._writer: csv.writer | None = None
        self._started = False

    def on_batch(self, fields: list[dict], rows: list[tuple]) -> None:
        if not rows:
            return
        if self.fieldnames is None:
            self.fieldnames = [f["name"] for f in fields]
        if not self._started:
            self._pending_rows = rows
            self._ensure_started()
            self._write_rows(self._pending_rows)
            del self._pending_rows
        else:
            self._write_rows(rows)

    def _ensure_started(self) -> None:
        if self._started:
            return
        if self.fieldnames is None:
            raise RuntimeError("Cannot start writer before fieldnames are known")

        self._file = _open_text_output(self.filename, encoding=self.encoding)
        self._write_preamble()
        self._writer = csv.writer(
            self._file,
            delimiter=self.delimiter,
            lineterminator="\n",
            quoting=csv.QUOTE_MINIMAL,
        )
        self._writer.writerow(self.fieldnames)
        self._started = True

    def _write_preamble(self) -> None:
        """
        Hook for subclasses like ECSV.
        """
        return

    def _format_value(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, dict | list | tuple):
            return json.dumps(value, separators=(",", ":"))
        return str(value)

    def _write_rows(self, rows: list[tuple]) -> None:
        assert self._writer is not None
        for row in rows:
            self._writer.writerow([self._format_value(val) for val in row])

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
            self._writer = None

    def __enter__(self) -> DelimitedTextAdapter:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False


class CsvAdapter(DelimitedTextAdapter):
    pass


class EcsvAdapter(DelimitedTextAdapter):
    def __init__(
        self,
        filename: str | Path,
        *,
        encoding: str = "utf-8",
        delimiter: str = ",",
        schema: str = "astropy-2.0",
        column_meta: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        if delimiter not in {",", " "}:
            raise ValueError("ECSV delimiter must be ',' or ' '")
        super().__init__(
            filename,
            encoding=encoding,
            delimiter=delimiter,
        )
        self.schema = schema
        self.column_meta = {k: dict(v) for k, v in (column_meta or {}).items()}

    def _write_preamble(self) -> None:
        assert self._file is not None
        assert self.fieldnames is not None
        assert hasattr(self, "_pending_rows")

        self._file.write("# %ECSV 1.0\n")
        self._file.write("# ---\n")
        self._file.write(f"# delimiter: {json.dumps(self.delimiter)}\n")
        self._file.write("# datatype:\n")
        for i, name in enumerate(self.fieldnames):
            dtype = self._infer_type(i)
            spec = {"name": name, "datatype": dtype}
            spec.update(self.column_meta.get(name, {}))
            self._file.write(f"# - {self._inline_map(spec)}\n")
        self._file.write(f"# schema: {self.schema}\n")

    def _infer_type(self, field_idx: int) -> str:
        for row in self._pending_rows:
            value = row[field_idx] if field_idx < len(row) else None
            if value is None:
                continue
            if isinstance(value, bool):
                return "bool"
            if isinstance(value, int):
                return "int64"
            if isinstance(value, float):
                return "float64"
            return "string"
        return "string"

    @staticmethod
    def _inline_map(values: Mapping[str, Any]) -> str:
        parts = []
        for key, value in values.items():
            if value is None:
                rendered = "null"
            elif isinstance(value, bool):
                rendered = "true" if value else "false"
            elif isinstance(value, int | float):
                rendered = str(value)
            else:
                rendered = json.dumps(str(value), ensure_ascii=False)
            parts.append(f"{key}: {rendered}")
        return "{{{}}}".format(", ".join(parts))
