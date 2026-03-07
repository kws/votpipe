"""Tests for gzipped VOTable input (.vot.gz file path)."""

import gzip
import struct

from tests.fixtures import BatchCollector, binary2_vot, tabledata_vot
from votpipe import parse_votable


def test_gzip_tabledata_via_path(tmp_path):
    """Parse a .vot.gz file from path (TABLEDATA)."""
    xml = tabledata_vot(rows=[["1", "10.0"], ["2", "20.0"]])
    gz_path = tmp_path / "table.vot.gz"
    with gzip.open(gz_path, "wb") as f:
        f.write(xml)

    collector = BatchCollector()
    parse_votable(gz_path, on_batch=collector.on_batch)

    assert len(collector.rows) == 2
    assert collector.rows[0] == (1, 10.0)
    assert collector.rows[1] == (2, 20.0)
    assert collector.get_field("id")["datatype"] == "int"
    assert collector.get_field("ra")["datatype"] == "double"
    assert collector.calls == 1


def test_gzip_binary2_via_path(tmp_path):
    """Parse a .vot.gz file with BINARY2 content."""
    fields = [
        {"name": "a", "datatype": "int"},
        {"name": "b", "datatype": "int"},
    ]
    mask = bytes([0])
    row_bytes = mask + struct.pack(">ii", 7, 8)
    xml = binary2_vot(fields, [row_bytes])
    gz_path = tmp_path / "data.vot.gz"
    with gzip.open(gz_path, "wb") as f:
        f.write(xml)

    collector = BatchCollector()
    parse_votable(gz_path, on_batch=collector.on_batch)

    assert len(collector.rows) == 1
    assert collector.rows[0] == (7, 8)
    assert collector.get_field("a")["datatype"] == fields[0]["datatype"]
    assert collector.get_field("b")["datatype"] == fields[1]["datatype"]
    assert collector.calls == 1


def test_plain_vot_via_path(tmp_path):
    """Parse a non-gzipped .vot file from path."""
    xml = tabledata_vot(rows=[["99", "1.5"]])
    vot_path = tmp_path / "plain.vot"
    vot_path.write_bytes(xml)

    collector = BatchCollector()
    parse_votable(vot_path, on_batch=collector.on_batch)

    assert len(collector.rows) == 1
    assert collector.rows[0] == (99, 1.5)
    assert collector.get_field("id")["datatype"] == "int"
    assert collector.get_field("ra")["datatype"] == "double"
    assert collector.calls == 1
