try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError as exc:
    raise ImportError(
        "votpipe.parquet requires the optional dependency 'pyarrow'. "
        "Install it with: pip install votpipe[parquet]"
    ) from exc


class ParquetAdapter:
    """
    Accepts batches of row tuples from the parser and writes them to a Parquet file.
    Use as the on_batch callback: parse_votable(source, adapter.on_batch).
    """

    def __init__(self, filename, *, compression="zstd"):
        self.filename = filename
        self.compression = compression
        self._field_names = None
        self._writer = None

    def on_batch(self, fields, rows):
        if not rows:
            return
        if self._field_names is None:
            self._field_names = [f["name"] for f in fields]
        columns = {
            name: [row[i] for row in rows] for i, name in enumerate(self._field_names)
        }
        table = pa.Table.from_pydict(columns)
        if self._writer is None:
            self._writer = pq.ParquetWriter(
                self.filename, table.schema, compression=self.compression
            )
        self._writer.write_table(table)

    def close(self):
        if self._writer is not None:
            self._writer.close()
            self._writer = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
