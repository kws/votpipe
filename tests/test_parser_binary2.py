"""Tests for parse_votable with BINARY2 serialization (null mask)."""

import io
import struct

from tests.fixtures import BatchCollector, binary2_vot
from votpipe import parse_votable


def _binary2_row(null_mask: bytes, *values, fmt: str = ">ii"):
    """Pack null mask + struct-packed values for one BINARY2 row."""
    return null_mask + struct.pack(fmt, *values)


def test_binary2_two_int_no_nulls():
    """BINARY2 with two ints, no nulls."""
    fields = [
        {"name": "a", "datatype": "int"},
        {"name": "b", "datatype": "int"},
    ]
    mask = bytes([0])
    row1 = _binary2_row(mask, 1, 2)
    row2 = _binary2_row(mask, 10, 20)
    xml = binary2_vot(fields, [row1, row2])

    collector = BatchCollector()
    parse_votable(io.BytesIO(xml), on_batch=collector.on_batch)

    assert len(collector.rows) == 2
    assert collector.rows[0] == (1, 2)
    assert collector.rows[1] == (10, 20)
    assert collector.get_field("a")["datatype"] == fields[0]["datatype"]
    assert collector.get_field("b")["datatype"] == fields[1]["datatype"]
    assert collector.calls == 1


def test_binary2_first_column_null():
    """BINARY2 with first column null (MSB set in mask)."""
    fields = [
        {"name": "a", "datatype": "int"},
        {"name": "b", "datatype": "int"},
    ]
    mask = bytes([0x80])  # bit 7 = column 0 null
    row = _binary2_row(mask, 0, 99)
    xml = binary2_vot(fields, [row])

    collector = BatchCollector()
    parse_votable(io.BytesIO(xml), on_batch=collector.on_batch)

    assert len(collector.rows) == 1
    assert collector.rows[0][0] is None
    assert collector.rows[0][1] == 99
    assert collector.get_field("a")["datatype"] == fields[0]["datatype"]
    assert collector.get_field("b")["datatype"] == fields[1]["datatype"]
    assert collector.calls == 1


def test_binary2_second_column_null():
    """BINARY2 with second column null (bit 6 set)."""
    fields = [
        {"name": "a", "datatype": "int"},
        {"name": "b", "datatype": "int"},
    ]
    mask = bytes([0x40])  # bit 6 = column 1 null
    row = _binary2_row(mask, 42, 0)
    xml = binary2_vot(fields, [row])

    collector = BatchCollector()
    parse_votable(io.BytesIO(xml), on_batch=collector.on_batch)

    assert len(collector.rows) == 1
    assert collector.rows[0][0] == 42
    assert collector.rows[0][1] is None
    assert collector.get_field("a")["datatype"] == fields[0]["datatype"]
    assert collector.get_field("b")["datatype"] == fields[1]["datatype"]
    assert collector.calls == 1


def test_binary2_multiple_rows_mixed_nulls():
    """BINARY2 multiple rows with mixed null patterns."""
    fields = [
        {"name": "id", "datatype": "int"},
        {"name": "val", "datatype": "int"},
    ]
    rows_bytes = [
        _binary2_row(bytes([0]), 1, 10),
        _binary2_row(bytes([0x80]), 0, 20),
        _binary2_row(bytes([0]), 3, 30),
    ]
    xml = binary2_vot(fields, rows_bytes)

    collector = BatchCollector()
    parse_votable(io.BytesIO(xml), on_batch=collector.on_batch)

    assert len(collector.rows) == 3
    assert collector.rows[0] == (1, 10)
    assert collector.rows[1][0] is None and collector.rows[1][1] == 20
    assert collector.rows[2] == (3, 30)
    assert collector.get_field("id")["datatype"] == fields[0]["datatype"]
    assert collector.get_field("val")["datatype"] == fields[1]["datatype"]
    assert collector.calls == 1


def test_binary2_variable_length_char_with_null():
    """BINARY2 with a variable-length char column and a null mask."""
    fields = [
        {"name": "id", "datatype": "int"},
        {"name": "flags", "datatype": "char", "arraysize": "*"},
    ]
    row1 = bytes([0]) + struct.pack(">i", 1) + struct.pack(">i", 4) + b"keep"
    row2 = bytes([0x40]) + struct.pack(">i", 2) + struct.pack(">i", 0)
    xml = binary2_vot(fields, [row1, row2])

    collector = BatchCollector()
    parse_votable(io.BytesIO(xml), on_batch=collector.on_batch)

    assert collector.rows == [(1, "keep"), (2, None)]
    assert collector.get_field("flags")["arraysize"] == "*"
    assert collector.calls == 1
