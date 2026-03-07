"""
Tests for votpipe.parquet.ParquetAdapter.
Requires pyarrow (optional dependency). Tests are skipped when pyarrow is not installed.
"""

from pathlib import Path

import pytest


@pytest.fixture
def pq():
    pq = pytest.importorskip("pyarrow.parquet")
    from votpipe.parquet import ParquetAdapter

    pq.ParquetAdapter = ParquetAdapter
    return pq


# -----------------------------------------------------------------------------
# Fixtures and helpers
# -----------------------------------------------------------------------------


@pytest.fixture
def parquet_path(tmp_path):
    """Path for a temporary Parquet file."""
    return tmp_path / "out.parquet"


@pytest.fixture
def parquet_adapter(parquet_path, pq):
    """ParquetAdapter writing to tmp_path."""
    return pq.ParquetAdapter(str(parquet_path), compression="zstd")


def _row_dict_from_table(table) -> list[dict]:
    """Convert PyArrow table to list of row dicts (one dict per row)."""
    d = table.to_pydict()
    keys = list(d.keys())
    n = len(d[keys[0]]) if keys else 0
    return [dict(zip(keys, [d[k][i] for k in keys], strict=True)) for i in range(n)]


def read_parquet_rows(path: str | Path, pq) -> list[dict]:
    """Read a Parquet file and return list of row dicts."""
    table = pq.read_table(path)
    return _row_dict_from_table(table)


def rows_equal(expected: dict, actual: dict) -> bool:
    """Compare two row dicts; use pytest.approx for floats."""
    if set(expected) != set(actual):
        return False
    for key in expected:
        e, a = expected[key], actual[key]
        if e is None and a is None:
            continue
        if e is None or a is None:
            return False
        if isinstance(e, float) and isinstance(a, int | float):
            if pytest.approx(e, rel=1e-9) != a:
                return False
            continue
        if isinstance(e, str) and isinstance(a, str):
            if e.strip() != a.strip():
                return False
            continue
        if isinstance(e, bool) and isinstance(a, bool):
            if e != a:
                return False
            continue
        if e != a:
            return False
    return True


# -----------------------------------------------------------------------------
# 1. Import and optional dependency
# -----------------------------------------------------------------------------


def test_import_parquet_with_pyarrow():
    """When pyarrow is installed, from votpipe.parquet import ParquetAdapter succeeds."""
    from votpipe.parquet import ParquetAdapter

    assert ParquetAdapter is not None


# -----------------------------------------------------------------------------
# 2. ParquetAdapter initialization
# -----------------------------------------------------------------------------


def test_adapter_init_defaults(parquet_path, pq):
    """ParquetAdapter(path) stores filename, compression='zstd'; no writer until first batch."""
    adapter = pq.ParquetAdapter(str(parquet_path))
    assert adapter.filename == str(parquet_path)
    assert adapter.compression == "zstd"
    assert adapter._field_names is None
    assert adapter._writer is None


def test_adapter_init_custom_compression(parquet_path, pq):
    """Custom compression is stored and used when writer is created."""
    adapter = pq.ParquetAdapter(str(parquet_path), compression="none")
    assert adapter.compression == "none"
    adapter.on_batch([{"name": "a"}], [(1,)])
    adapter.close()
    assert parquet_path.exists()
    table = pq.read_table(parquet_path)
    assert table.num_rows == 1


# -----------------------------------------------------------------------------
# 3. on_batch and close behavior
# -----------------------------------------------------------------------------


def test_on_batch_writes_and_close(parquet_adapter, parquet_path, pq):
    """Single on_batch with rows; close(); file has those rows."""
    fields = [{"name": "id"}, {"name": "ra"}]
    parquet_adapter.on_batch(fields, [(1, 10.5), (2, 20.0)])
    assert parquet_path.exists()
    parquet_adapter.close()
    rows = read_parquet_rows(parquet_path, pq)
    assert len(rows) == 2
    assert rows[0]["id"] == 1 and rows[0]["ra"] == pytest.approx(10.5)
    assert rows[1]["id"] == 2 and rows[1]["ra"] == pytest.approx(20.0)


def test_on_batch_empty_no_op(parquet_path, pq):
    """on_batch with empty rows does not create file."""
    adapter = pq.ParquetAdapter(str(parquet_path))
    adapter.on_batch([{"name": "a"}], [])
    adapter.on_batch([{"name": "a"}], [])
    assert not parquet_path.exists()
    adapter.close()


def test_close_idempotent(parquet_adapter, parquet_path, pq):
    """Calling close() twice does not raise; second call is safe."""
    parquet_adapter.on_batch([{"name": "a"}], [(1,)])
    parquet_adapter.close()
    parquet_adapter.close()
    rows = read_parquet_rows(parquet_path, pq)
    assert len(rows) == 1


def test_multiple_batches_same_schema(parquet_path, pq):
    """Multiple on_batch calls; all rows present and schema consistent."""
    adapter = pq.ParquetAdapter(str(parquet_path), compression="zstd")
    fields = [{"name": "id"}, {"name": "val"}]
    adapter.on_batch(fields, [(0, 0.0), (1, 10.0)])
    adapter.on_batch(fields, [(2, 20.0), (3, 30.0)])
    adapter.on_batch(fields, [(4, 40.0)])
    adapter.close()
    table = pq.read_table(parquet_path)
    assert table.num_rows == 5
    rows = _row_dict_from_table(table)
    for i, row in enumerate(rows):
        assert row["id"] == i and row["val"] == pytest.approx(i * 10.0)


# -----------------------------------------------------------------------------
# 3b. Context manager
# -----------------------------------------------------------------------------


def test_context_manager_enter_returns_self(parquet_path, pq):
    """__enter__ returns the adapter so it can be used in the with block."""
    with pq.ParquetAdapter(str(parquet_path)) as adapter:
        assert adapter is not None
        adapter.on_batch([{"name": "id"}, {"name": "x"}], [(1, 10)])
    rows = read_parquet_rows(parquet_path, pq)
    assert len(rows) == 1
    assert rows[0]["id"] == 1 and rows[0]["x"] == 10


def test_context_manager_normal_exit_closes(parquet_path, pq):
    """On normal exit, __exit__ calls close(); file is valid."""
    with pq.ParquetAdapter(str(parquet_path), compression="zstd") as adapter:
        adapter.on_batch(
            [{"name": "a"}, {"name": "b"}],
            [(1, 2), (3, 4), (5, 6)],
        )
    assert parquet_path.exists()
    rows = read_parquet_rows(parquet_path, pq)
    assert len(rows) == 3
    assert [r["a"] for r in rows] == [1, 3, 5]
    assert [r["b"] for r in rows] == [2, 4, 6]


def test_context_manager_exception_closes_writer_and_propagates(parquet_path, pq):
    """On exception, __exit__ closes the writer (no leak) and propagates the exception."""
    with (
        pytest.raises(ValueError, match="oops"),
        pq.ParquetAdapter(str(parquet_path)) as adapter,
    ):
        adapter.on_batch([{"name": "x"}], [(1,)])
        raise ValueError("oops")
    adapter.close()


# -----------------------------------------------------------------------------
# 4. Round-trip data integrity
# -----------------------------------------------------------------------------


def test_roundtrip_simple_rows(parquet_path, pq):
    """Write simple rows via on_batch, read back, assert equality."""
    fields = [{"name": "id"}, {"name": "ra"}]
    rows_tuples = [(1, 10.5), (2, 20.0)]
    expected = [{"id": 1, "ra": 10.5}, {"id": 2, "ra": 20.0}]
    adapter = pq.ParquetAdapter(str(parquet_path))
    adapter.on_batch(fields, rows_tuples)
    adapter.close()
    actual = read_parquet_rows(parquet_path, pq)
    assert len(actual) == 2
    for exp, act in zip(expected, actual, strict=True):
        assert rows_equal(exp, act)


def test_roundtrip_mixed_types(parquet_path, pq):
    """int, float, str, bool columns; verify types preserved."""
    fields = [{"name": "id"}, {"name": "x"}, {"name": "name"}, {"name": "flag"}]
    rows_tuples = [
        (1, 1.5, "Alpha", True),
        (2, 2.5, "Beta", False),
    ]
    expected = [
        {"id": 1, "x": 1.5, "name": "Alpha", "flag": True},
        {"id": 2, "x": 2.5, "name": "Beta", "flag": False},
    ]
    adapter = pq.ParquetAdapter(str(parquet_path))
    adapter.on_batch(fields, rows_tuples)
    adapter.close()
    actual = read_parquet_rows(parquet_path, pq)
    assert len(actual) == 2
    for exp, act in zip(expected, actual, strict=True):
        assert rows_equal(exp, act)


def test_roundtrip_none_values(parquet_path, pq):
    """Rows with None; verify nulls round-trip correctly."""
    fields = [{"name": "a"}, {"name": "b"}]
    adapter = pq.ParquetAdapter(str(parquet_path))
    adapter.on_batch(fields, [(1, None), (2, 42)])
    adapter.close()
    actual = read_parquet_rows(parquet_path, pq)
    assert len(actual) == 2
    assert actual[0]["a"] == 1 and actual[0]["b"] is None
    assert actual[1]["a"] == 2 and actual[1]["b"] == 42


def test_roundtrip_votpipe_batch_api(parquet_path, pq):
    """parse_votable -> adapter.on_batch -> parquet; read back and compare."""
    import io

    from tests.fixtures import tabledata_vot
    from votpipe import parse_votable

    xml = tabledata_vot(rows=[["1", "10.5"], ["2", "20.0"], ["3", "30.0"]])
    adapter = pq.ParquetAdapter(str(parquet_path))
    parse_votable(io.BytesIO(xml), adapter.on_batch)
    adapter.close()
    actual = read_parquet_rows(parquet_path, pq)
    assert len(actual) == 3
    assert actual[0]["id"] == 1 and actual[0]["ra"] == pytest.approx(10.5)
    assert actual[1]["id"] == 2 and actual[1]["ra"] == pytest.approx(20.0)
    assert actual[2]["id"] == 3 and actual[2]["ra"] == pytest.approx(30.0)


# -----------------------------------------------------------------------------
# 5. Edge cases
# -----------------------------------------------------------------------------


def test_single_row(parquet_path, pq):
    """One row only; close; file has one row."""
    adapter = pq.ParquetAdapter(str(parquet_path))
    adapter.on_batch([{"name": "id"}, {"name": "ra"}], [(1, 10.0)])
    adapter.close()
    rows = read_parquet_rows(parquet_path, pq)
    assert len(rows) == 1
    assert rows[0]["id"] == 1 and rows[0]["ra"] == pytest.approx(10.0)


def test_zero_rows(parquet_path, pq):
    """Never call on_batch with rows; close() creates no file."""
    adapter = pq.ParquetAdapter(str(parquet_path))
    adapter.close()
    assert not parquet_path.exists()


def test_schema_from_first_batch(parquet_path, pq):
    """First batch defines schema; column names match."""
    adapter = pq.ParquetAdapter(str(parquet_path))
    adapter.on_batch(
        [{"name": "a"}, {"name": "b"}],
        [(1, 2), (3, 4), (5, 6)],
    )
    adapter.close()
    table = pq.read_table(parquet_path)
    assert table.column_names == ["a", "b"]
    assert table.num_rows == 3


# -----------------------------------------------------------------------------
# 6. Compression options
# -----------------------------------------------------------------------------


def test_compression_zstd(parquet_path, pq):
    """Default compression produces valid parquet (readable)."""
    adapter = pq.ParquetAdapter(str(parquet_path), compression="zstd")
    adapter.on_batch([{"name": "x"}], [(1,), (2,)])
    adapter.close()
    table = pq.read_table(parquet_path)
    assert table.num_rows == 2


def test_compression_none(parquet_path, pq):
    """compression='none' produces valid parquet."""
    adapter = pq.ParquetAdapter(str(parquet_path), compression="none")
    adapter.on_batch([{"name": "x"}], [(1,)])
    adapter.close()
    table = pq.read_table(parquet_path)
    assert table.num_rows == 1


def test_compression_snappy(parquet_path, pq):
    """compression='snappy' works if supported."""
    adapter = pq.ParquetAdapter(str(parquet_path), compression="snappy")
    adapter.on_batch([{"name": "x"}], [(1,)])
    adapter.close()
    table = pq.read_table(parquet_path)
    assert table.num_rows == 1


# -----------------------------------------------------------------------------
# 7. Integration with VOTable parser
# -----------------------------------------------------------------------------


def test_vot_to_parquet_pipeline(parquet_path, pq):
    """parse_votable with adapter.on_batch; read parquet and compare to expected."""
    import io

    from tests.fixtures import tabledata_vot
    from votpipe import parse_votable

    xml = tabledata_vot(
        fields=[
            {"name": "source_id", "datatype": "long"},
            {"name": "mag", "datatype": "float"},
        ],
        rows=[["100", "12.5"], ["200", "15.0"], ["300", "14.0"]],
    )
    expected = [
        {"source_id": 100, "mag": 12.5},
        {"source_id": 200, "mag": 15.0},
        {"source_id": 300, "mag": 14.0},
    ]
    adapter = pq.ParquetAdapter(str(parquet_path))
    parse_votable(io.BytesIO(xml), adapter.on_batch)
    adapter.close()
    actual = read_parquet_rows(parquet_path, pq)
    assert len(actual) == len(expected)
    for exp, act in zip(expected, actual, strict=True):
        assert rows_equal(exp, act)
