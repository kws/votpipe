"""Integration tests for CompiledBatchQuery (compile-on-first-batch, sink forwarding, close)."""

import io

import pytest

from tests.fixtures import BatchCollector, tabledata_vot
from votpipe._parser import parse_votable
from votpipe.query import CompiledBatchQuery


def test_compile_on_first_batch_forwards_transformed_rows():
    """CompiledBatchQuery compiles on first batch and forwards select+where result."""
    xml = tabledata_vot(
        fields=[
            {"name": "id", "datatype": "int"},
            {"name": "ra", "datatype": "double"},
            {"name": "dec", "datatype": "double"},
        ],
        rows=[
            ["1", "10.0", "100.0"],
            ["2", "20.0", "200.0"],
            ["3", "30.0", "300.0"],
        ],
    )
    collector = BatchCollector()
    query = CompiledBatchQuery(
        collector.on_batch,
        select="id,dec",
        where="ra >= 20",
    )
    parse_votable(io.BytesIO(xml), query.on_batch)

    assert collector.fields is not None
    assert [f["name"] for f in collector.fields] == ["id", "dec"]
    assert len(collector.rows) == 2
    assert collector.rows[0] == (2, 200.0)
    assert collector.rows[1] == (3, 300.0)


def test_close_delegation_to_sink():
    """close() is forwarded to sink owner when it has a close method."""
    closed = []

    class SinkWithClose:
        def on_batch(self, fields, rows):
            pass

        def close(self):
            closed.append(True)

    sink = SinkWithClose()
    query = CompiledBatchQuery(sink.on_batch)
    # Compile with a minimal batch so we don't need a real parse
    query.on_batch(
        [{"name": "x", "datatype": "int"}],
        [(1,), (2,)],
    )
    assert len(closed) == 0
    query.close()
    assert len(closed) == 1


def test_no_close_when_sink_has_no_close():
    """When sink has no close method, query.close() does not raise."""
    collector = BatchCollector()
    query = CompiledBatchQuery(collector.on_batch)
    query.close()  # no-op, no error


def test_second_batch_same_schema_forwards_transformed():
    """Second and later batches use compiled transform and same-field check."""
    collector = BatchCollector()
    fields = [
        {"name": "id", "datatype": "int"},
        {"name": "ra", "datatype": "double"},
    ]
    query = CompiledBatchQuery(
        collector.on_batch,
        select="id,ra",
        where="ra >= 15",
    )
    query.on_batch(fields, [(1, 10.0), (2, 20.0)])
    query.on_batch(fields, [(3, 30.0), (4, 5.0)])
    assert [f["name"] for f in collector.fields] == ["id", "ra"]
    assert collector.rows == [(2, 20.0), (3, 30.0)]


def test_field_schema_change_raises():
    """If field definitions change after first batch, ValueError is raised."""
    collector = BatchCollector()
    query = CompiledBatchQuery(collector.on_batch, select="id")
    query.on_batch(
        [{"name": "id", "datatype": "int"}],
        [(1,), (2,)],
    )
    with pytest.raises(ValueError, match="field definitions changed"):
        query.on_batch(
            [{"name": "id", "datatype": "double"}],
            [(1.0,), (2.0,)],
        )


def test_emit_empty_first_batch():
    """With emit_empty_first_batch=True, sink is called even when first batch has no rows after filter."""
    received = []

    class Sink:
        def on_batch(self, fields, rows):
            received.append((fields, rows))

    sink = Sink()
    query = CompiledBatchQuery(
        sink.on_batch,
        where="x > 100",
        emit_empty_first_batch=True,
    )
    # First batch: all rows filtered out
    query.on_batch([{"name": "x", "datatype": "int"}], [(1,), (2,)])
    assert len(received) == 1
    assert received[0][0] == [{"name": "x", "datatype": "int"}]
    assert received[0][1] == []


def test_second_batch_all_filtered_out_does_not_emit():
    """When schema already emitted and second batch has no rows after filter, sink is not called again."""
    received = []

    class Sink:
        def on_batch(self, fields, rows):
            received.append((fields, list(rows)))

    sink = Sink()
    fields = [{"name": "x", "datatype": "int"}]
    query = CompiledBatchQuery(sink.on_batch, where="x >= 10")
    query.on_batch(fields, [(10,), (20,)])  # first batch: emit 2 rows
    assert len(received) == 1
    assert received[0][1] == [(10,), (20,)]
    query.on_batch(fields, [(1,), (2,)])  # second batch: all filtered out
    assert len(received) == 1  # no second call


def test_context_manager_closes_on_exit():
    """Using 'with' calls close() on exit."""
    closed = []

    class SinkWithClose:
        def on_batch(self, fields, rows):
            pass

        def close(self):
            closed.append(True)

    sink = SinkWithClose()
    with CompiledBatchQuery(sink.on_batch) as query:
        query.on_batch(
            [{"name": "a", "datatype": "int"}],
            [(1,)],
        )
    assert len(closed) == 1


def test_discover_close_returns_none_when_close_not_callable():
    """When sink owner has a 'close' attribute that is not callable, close() is no-op."""

    class SinkWithNonCallableClose:
        close = "not a method"

        def on_batch(self, fields, rows):
            pass

    sink = SinkWithNonCallableClose()
    query = CompiledBatchQuery(sink.on_batch)
    query.on_batch([{"name": "x", "datatype": "int"}], [(1,)])
    query.close()  # should not raise; _sink_close is None
