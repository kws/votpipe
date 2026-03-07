"""Tests for parse_votable with TABLEDATA serialization."""

import io

from tests.fixtures import BatchCollector, tabledata_vot
from votpipe import parse_votable


def test_tabledata_default_fixture():
    """Parse default TABLEDATA fixture (id int, ra double, two rows)."""
    xml = tabledata_vot()
    collector = BatchCollector()
    parse_votable(io.BytesIO(xml), on_batch=collector.on_batch)

    assert len(collector.rows) == 2
    assert collector.rows[0] == (1, 10.5)
    assert collector.rows[1] == (2, 20.0)
    assert collector.get_field("id")["datatype"] == "int"
    assert collector.get_field("ra")["datatype"] == "double"
    assert collector.calls == 1


def test_tabledata_field_names():
    """Row tuples are in column order; field metadata is preserved."""
    fields = [
        {"name": "source_id", "datatype": "long"},
        {"name": "mag", "datatype": "float"},
    ]
    rows_data = [["100", "12.5"], ["200", "15.0"]]
    xml = tabledata_vot(fields=fields, rows=rows_data)
    collector = BatchCollector()
    parse_votable(io.BytesIO(xml), on_batch=collector.on_batch)

    assert collector.rows[0][0] == 100
    assert collector.rows[0][1] == 12.5
    assert collector.rows[1][0] == 200
    assert collector.rows[1][1] == 15.0
    assert collector.get_field("source_id")["datatype"] == "long"
    assert collector.get_field("mag")["datatype"] == "float"
    assert collector.calls == 1


def test_tabledata_multiple_rows():
    """Arbitrary number of rows."""
    rows_data = [[str(i), str(i * 1.5)] for i in range(10)]
    xml = tabledata_vot(rows=rows_data)
    collector = BatchCollector()
    parse_votable(io.BytesIO(xml), on_batch=collector.on_batch)

    assert len(collector.rows) == 10
    assert collector.rows[7] == (7, 10.5)
    assert collector.get_field("id")["datatype"] == "int"
    assert collector.get_field("ra")["datatype"] == "double"
    assert collector.calls == 1


def test_tabledata_string_column():
    """Char/string column passthrough."""
    fields = [
        {"name": "id", "datatype": "int"},
        {"name": "name", "datatype": "char", "arraysize": "10"},
    ]
    rows_data = [["1", "Alpha"], ["2", "Beta"]]
    xml = tabledata_vot(fields=fields, rows=rows_data)
    collector = BatchCollector()
    parse_votable(io.BytesIO(xml), on_batch=collector.on_batch)

    assert collector.rows[0] == (1, "Alpha")
    assert collector.rows[1] == (2, "Beta")
    assert collector.get_field("id")["datatype"] == "int"
    assert collector.get_field("name")["datatype"] == "char"
    assert collector.calls == 1


def test_tabledata_empty_cell_becomes_none():
    """Empty TD is cast to None for numeric type."""
    fields = [
        {"name": "a", "datatype": "int"},
        {"name": "b", "datatype": "int"},
    ]
    rows_data = [["1", ""], ["2", "3"]]
    xml = tabledata_vot(fields=fields, rows=rows_data)
    collector = BatchCollector()
    parse_votable(io.BytesIO(xml), on_batch=collector.on_batch)

    assert collector.rows[0][0] == 1
    assert collector.rows[0][1] is None
    assert collector.rows[1] == (2, 3)
    assert collector.get_field("a")["datatype"] == "int"
    assert collector.get_field("b")["datatype"] == "int"
    assert collector.calls == 1


def test_tabledata_multiple_batches():
    """With batch_size=1, multiple rows produce multiple batch calls."""
    xml = tabledata_vot(rows=[["1", "1.0"], ["2", "2.0"], ["3", "3.0"]])
    collector = BatchCollector()
    parse_votable(io.BytesIO(xml), on_batch=collector.on_batch, batch_size=1)

    assert len(collector.rows) == 3
    assert collector.rows[0] == (1, 1.0)
    assert collector.rows[1] == (2, 2.0)
    assert collector.rows[2] == (3, 3.0)
    assert collector.calls == 3
