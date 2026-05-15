"""Tests for parse_votable with BINARY serialization (no null mask)."""

import io
import struct

import pytest

from tests.fixtures import BatchCollector, binary_vot
from votpipe import parse_votable


def test_binary_two_int():
    """BINARY with two int columns."""
    fields = [
        {"name": "a", "datatype": "int"},
        {"name": "b", "datatype": "int"},
    ]
    row1 = struct.pack(">ii", 42, 100)
    row2 = struct.pack(">ii", 0, -1)
    xml = binary_vot(fields, [row1, row2])

    collector = BatchCollector()
    parse_votable(io.BytesIO(xml), on_batch=collector.on_batch)

    assert collector.rows == [(42, 100), (0, -1)]
    assert collector.get_field("a")["datatype"] == fields[0]["datatype"]
    assert collector.get_field("b")["datatype"] == fields[1]["datatype"]
    assert collector.calls == 1


def test_binary_double_float():
    """BINARY with double and float."""
    fields = [
        {"name": "ra", "datatype": "double"},
        {"name": "mag", "datatype": "float"},
    ]
    row = struct.pack(">df", 180.5, 12.25)
    xml = binary_vot(fields, [row])

    collector = BatchCollector()
    parse_votable(io.BytesIO(xml), on_batch=collector.on_batch)

    assert len(collector.rows) == 1
    assert collector.rows[0][0] == 180.5
    assert collector.rows[0][1] == pytest.approx(12.25)
    assert collector.get_field("ra")["datatype"] == fields[0]["datatype"]
    assert collector.get_field("mag")["datatype"] == fields[1]["datatype"]
    assert collector.calls == 1


def test_binary_multiple_rows():
    """BINARY with several rows."""
    fields = [{"name": "x", "datatype": "int"}]
    row_bytes_list = [struct.pack(">i", i) for i in range(5)]
    xml = binary_vot(fields, row_bytes_list)

    collector = BatchCollector()
    parse_votable(io.BytesIO(xml), on_batch=collector.on_batch)

    assert len(collector.rows) == 5
    assert [r[0] for r in collector.rows] == [0, 1, 2, 3, 4]
    assert collector.get_field("x")["datatype"] == fields[0]["datatype"]
    assert collector.calls == 1


def test_binary_variable_length_char():
    """BINARY with a variable-length char column."""
    fields = [
        {"name": "id", "datatype": "int"},
        {"name": "flags", "datatype": "char", "arraysize": "*"},
        {"name": "score", "datatype": "double"},
    ]
    row1 = struct.pack(">i", 1) + struct.pack(">i", 5) + b"abc  " + struct.pack(">d", 1.5)
    row2 = struct.pack(">i", 2) + struct.pack(">i", 3) + b"xyz" + struct.pack(">d", 2.5)
    xml = binary_vot(fields, [row1, row2])

    collector = BatchCollector()
    parse_votable(io.BytesIO(xml), on_batch=collector.on_batch, batch_size=1)

    assert collector.rows == [(1, "abc", 1.5), (2, "xyz", 2.5)]
    assert collector.get_field("flags")["arraysize"] == "*"
    assert collector.calls == 2
