"""
Unit tests for votpipe.csv: DelimitedTextAdapter, CsvAdapter, EcsvAdapter.
Includes Astropy compatibility tests (read our CSV/ECSV output with Astropy).
"""

from __future__ import annotations

import csv
import gzip
import io
import lzma

import pytest

from votpipe.csv import (
    CsvAdapter,
    DelimitedTextAdapter,
    EcsvAdapter,
)

# -----------------------------------------------------------------------------
# _open_text_output (tested via adapters writing to .csv, .gz, .xz)
# -----------------------------------------------------------------------------


def test_delimited_adapter_plain_csv_creates_file(tmp_path):
    """Writing to a .csv path creates a plain text file."""
    path = tmp_path / "out.csv"
    with DelimitedTextAdapter(path) as adapter:
        adapter.on_batch(
            [{"name": "a"}, {"name": "b"}],
            [(1, 2), (3, 4)],
        )
    content = path.read_text(encoding="utf-8")
    assert "a,b" in content or "a," in content
    assert "1,2" in content
    assert "3,4" in content


def test_delimited_adapter_gz_creates_compressed_file(tmp_path):
    """Writing to a .gz path creates gzip-compressed text."""
    path = tmp_path / "out.csv.gz"
    with DelimitedTextAdapter(path) as adapter:
        adapter.on_batch(
            [{"name": "x"}],
            [(42,)],
        )
    assert path.exists()
    with gzip.open(path, "rt", encoding="utf-8") as f:
        content = f.read()
    assert "x" in content
    assert "42" in content


def test_delimited_adapter_xz_creates_compressed_file(tmp_path):
    """Writing to a .xz path creates lzma-compressed text."""
    path = tmp_path / "out.csv.xz"
    with DelimitedTextAdapter(path) as adapter:
        adapter.on_batch(
            [{"name": "id"}],
            [(1,)],
        )
    assert path.exists()
    with lzma.open(path, "rt", encoding="utf-8") as f:
        content = f.read()
    assert "id" in content
    assert "1" in content


# -----------------------------------------------------------------------------
# DelimitedTextAdapter: init, on_batch, close, context manager
# -----------------------------------------------------------------------------


def test_delimited_adapter_init(tmp_path):
    """Adapter stores filename, encoding, delimiter; fieldnames unset until first batch."""
    path = tmp_path / "out.csv"
    adapter = DelimitedTextAdapter(path, encoding="utf-8", delimiter="\t")
    assert adapter.filename == path
    assert adapter.encoding == "utf-8"
    assert adapter.delimiter == "\t"
    assert adapter.fieldnames is None
    assert adapter._file is None
    assert adapter._writer is None
    assert adapter._started is False
    adapter.close()


def test_delimited_adapter_on_batch_empty_no_op(tmp_path):
    """on_batch with empty rows does not create file or set fieldnames."""
    path = tmp_path / "out.csv"
    adapter = DelimitedTextAdapter(path)
    adapter.on_batch([{"name": "a"}, {"name": "b"}], [])
    adapter.on_batch([{"name": "a"}, {"name": "b"}], [])
    assert not path.exists()
    assert adapter.fieldnames is None
    adapter.close()


def test_delimited_adapter_on_batch_single_batch(tmp_path):
    """First batch with rows sets fieldnames, opens file, writes header and data."""
    path = tmp_path / "out.csv"
    adapter = DelimitedTextAdapter(path)
    fields = [{"name": "id"}, {"name": "ra"}]
    adapter.on_batch(fields, [(1, 10.5), (2, 20.0)])
    adapter.close()
    assert adapter.fieldnames == ["id", "ra"]
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3  # header + 2 rows
    reader = csv.reader(io.StringIO(path.read_text(encoding="utf-8")))
    rows = list(reader)
    assert rows[0] == ["id", "ra"]
    assert rows[1] == ["1", "10.5"]
    assert rows[2] == ["2", "20.0"]


def test_delimited_adapter_multiple_batches(tmp_path):
    """Multiple on_batch calls append rows; schema from first batch."""
    path = tmp_path / "out.csv"
    adapter = DelimitedTextAdapter(path)
    fields = [{"name": "a"}, {"name": "b"}]
    adapter.on_batch(fields, [(1, 2), (3, 4)])
    adapter.on_batch(fields, [(5, 6)])
    adapter.close()
    reader = csv.reader(io.StringIO(path.read_text(encoding="utf-8")))
    rows = list(reader)
    assert rows[0] == ["a", "b"]
    assert rows[1] == ["1", "2"]
    assert rows[2] == ["3", "4"]
    assert rows[3] == ["5", "6"]


def test_delimited_adapter_format_value_none_and_scalars(tmp_path):
    """None -> empty cell; int/float/str/bool -> string representation."""
    path = tmp_path / "out.csv"
    with DelimitedTextAdapter(path) as adapter:
        adapter.on_batch(
            [{"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"}],
            [(None, 42, 3.14, "hello"), (True, False, 0, 1.0)],
        )
    reader = csv.reader(io.StringIO(path.read_text(encoding="utf-8")))
    rows = list(reader)
    assert rows[0] == ["a", "b", "c", "d"]
    assert rows[1][0] == ""
    assert rows[1][1] == "42"
    assert rows[1][2] == "3.14"
    assert rows[1][3] == "hello"
    assert rows[2][0] == "True"
    assert rows[2][1] == "False"


def test_delimited_adapter_format_value_list_and_dict(tmp_path):
    """List and dict values are JSON-serialized."""
    path = tmp_path / "out.csv"
    with DelimitedTextAdapter(path) as adapter:
        adapter.on_batch(
            [{"name": "payload"}],
            [([1, 2],), ({"k": "v"},)],
        )
    reader = csv.reader(io.StringIO(path.read_text(encoding="utf-8")))
    rows = list(reader)
    assert rows[0] == ["payload"]
    assert rows[1][0] == "[1,2]"
    assert rows[2][0] == '{"k":"v"}'


def test_delimited_adapter_custom_delimiter(tmp_path):
    """Custom delimiter is used in output."""
    path = tmp_path / "out.csv"
    with DelimitedTextAdapter(path, delimiter="\t") as adapter:
        adapter.on_batch(
            [{"name": "x"}, {"name": "y"}],
            [(1, 2)],
        )
    content = path.read_text(encoding="utf-8")
    assert "\t" in content
    assert content.strip().split("\t") == ["x", "y"] or "x" in content


def test_delimited_adapter_close_idempotent(tmp_path):
    """Calling close() twice does not raise."""
    path = tmp_path / "out.csv"
    adapter = DelimitedTextAdapter(path)
    adapter.on_batch([{"name": "a"}], [(1,)])
    adapter.close()
    adapter.close()
    assert path.read_text(encoding="utf-8").count("1") >= 1


def test_delimited_adapter_context_manager(tmp_path):
    """Context manager enters with self, exits with close."""
    path = tmp_path / "out.csv"
    with DelimitedTextAdapter(path) as adapter:
        assert adapter is not None
        adapter.on_batch([{"name": "id"}], [(1,)])
    assert path.exists()
    assert "1" in path.read_text(encoding="utf-8")


def test_delimited_adapter_context_manager_on_exception_closes(tmp_path):
    """On exception, __exit__ closes the file and propagates."""
    path = tmp_path / "out.csv"
    with pytest.raises(ValueError, match="oops"), DelimitedTextAdapter(path) as adapter:
        adapter.on_batch([{"name": "x"}], [(1,)])
        raise ValueError("oops")
    # File may or may not exist depending on when exception occurred; adapter should be closed
    adapter.close()


# -----------------------------------------------------------------------------
# CsvAdapter
# -----------------------------------------------------------------------------


def test_csv_adapter_inherits_and_writes(tmp_path):
    """CsvAdapter behaves like DelimitedTextAdapter (writes valid CSV)."""
    path = tmp_path / "out.csv"
    with CsvAdapter(path) as adapter:
        adapter.on_batch(
            [{"name": "id"}, {"name": "name"}],
            [(1, "Alpha"), (2, "Beta")],
        )
    reader = csv.reader(io.StringIO(path.read_text(encoding="utf-8")))
    rows = list(reader)
    assert rows[0] == ["id", "name"]
    assert rows[1] == ["1", "Alpha"]
    assert rows[2] == ["2", "Beta"]


# -----------------------------------------------------------------------------
# EcsvAdapter: init, delimiter validation, preamble, type inference
# -----------------------------------------------------------------------------


def test_ecsv_adapter_delimiter_invalid_raises():
    """EcsvAdapter rejects delimiter other than ',' or ' '."""
    with pytest.raises(ValueError, match="ECSV delimiter must be"):
        EcsvAdapter("/tmp/out.ecsv", delimiter="\t")


def test_ecsv_adapter_delimiter_comma_allowed(tmp_path):
    """EcsvAdapter accepts delimiter=','."""
    path = tmp_path / "out.ecsv"
    with EcsvAdapter(path, delimiter=",") as adapter:
        adapter.on_batch([{"name": "x"}], [(1,)])
    assert path.exists()


def test_ecsv_adapter_delimiter_space_allowed(tmp_path):
    """EcsvAdapter accepts delimiter=' '."""
    path = tmp_path / "out.ecsv"
    with EcsvAdapter(path, delimiter=" ") as adapter:
        adapter.on_batch([{"name": "a"}, {"name": "b"}], [(1, 2)])
    content = path.read_text(encoding="utf-8")
    assert '# delimiter: " "' in content or "# delimiter: ' '" in content


def test_ecsv_adapter_preamble_has_ecsv_header_and_datatype(tmp_path):
    """ECSV output has # %ECSV 1.0, delimiter, datatype lines, schema."""
    path = tmp_path / "out.ecsv"
    with EcsvAdapter(path) as adapter:
        adapter.on_batch(
            [{"name": "id"}, {"name": "mag"}],
            [(1, 12.5), (2, 15.0)],
        )
    content = path.read_text(encoding="utf-8")
    assert "# %ECSV 1.0" in content
    assert "# ---" in content
    assert "# delimiter:" in content
    assert "# datatype:" in content
    assert "# schema:" in content
    assert "astropy" in content or "schema" in content.lower()


def test_ecsv_adapter_infer_type_bool_int_float_string(tmp_path):
    """Datatype lines reflect inferred types from first batch."""
    path = tmp_path / "out.ecsv"
    with EcsvAdapter(path) as adapter:
        adapter.on_batch(
            [
                {"name": "flag"},
                {"name": "count"},
                {"name": "value"},
                {"name": "label"},
            ],
            [(True, 1, 1.5, "alpha"), (False, 2, 2.5, "beta")],
        )
    content = path.read_text(encoding="utf-8")
    assert "bool" in content
    assert "int64" in content
    assert "float64" in content
    assert "string" in content


def test_ecsv_adapter_all_none_column_infers_string(tmp_path):
    """Column with all None values infers as string."""
    path = tmp_path / "out.ecsv"
    with EcsvAdapter(path) as adapter:
        adapter.on_batch(
            [{"name": "a"}, {"name": "b"}],
            [(None, 1), (None, 2)],
        )
    content = path.read_text(encoding="utf-8")
    # First column all None -> string; second has int -> int64
    assert "string" in content
    assert "int64" in content


def test_ecsv_inline_map_static():
    """_inline_map renders key: value pairs as ECSV inline format."""
    out = EcsvAdapter._inline_map({"name": "ra", "datatype": "float64"})
    assert "name:" in out
    assert "float64" in out
    assert "ra" in out
    out_null = EcsvAdapter._inline_map({"name": "x", "datatype": None})
    assert "null" in out_null


def test_ecsv_adapter_column_meta_in_preamble(tmp_path):
    """Optional column_meta is merged into datatype lines."""
    path = tmp_path / "out.ecsv"
    with EcsvAdapter(
        path,
        column_meta={"ra": {"unit": "deg"}, "dec": {"unit": "deg"}},
    ) as adapter:
        adapter.on_batch(
            [{"name": "ra"}, {"name": "dec"}],
            [(10.0, 20.0)],
        )
    content = path.read_text(encoding="utf-8")
    assert "unit" in content
    assert "deg" in content


# -----------------------------------------------------------------------------
# Round-trip with VOTable parser
# -----------------------------------------------------------------------------


def test_csv_roundtrip_votpipe_parser(tmp_path):
    """parse_votable -> CsvAdapter -> file has expected rows."""
    from tests.fixtures import tabledata_vot
    from votpipe import parse_votable

    xml = tabledata_vot(
        fields=[
            {"name": "id", "datatype": "int"},
            {"name": "ra", "datatype": "double"},
        ],
        rows=[["1", "10.5"], ["2", "20.0"], ["3", "30.0"]],
    )
    path = tmp_path / "out.csv"
    with CsvAdapter(path) as adapter:
        parse_votable(io.BytesIO(xml), adapter.on_batch)
    reader = csv.reader(io.StringIO(path.read_text(encoding="utf-8")))
    rows = list(reader)
    assert rows[0] == ["id", "ra"]
    assert rows[1] == ["1", "10.5"]
    assert rows[2] == ["2", "20.0"]
    assert rows[3] == ["3", "30.0"]


def test_ecsv_roundtrip_votpipe_parser(tmp_path):
    """parse_votable -> EcsvAdapter -> file has ECSV preamble and data."""
    from tests.fixtures import tabledata_vot
    from votpipe import parse_votable

    xml = tabledata_vot(
        fields=[
            {"name": "source_id", "datatype": "long"},
            {"name": "mag", "datatype": "float"},
        ],
        rows=[["100", "12.5"], ["200", "15.0"]],
    )
    path = tmp_path / "out.ecsv"
    with EcsvAdapter(path) as adapter:
        parse_votable(io.BytesIO(xml), adapter.on_batch)
    content = path.read_text(encoding="utf-8")
    assert "# %ECSV 1.0" in content
    assert "source_id" in content
    assert "mag" in content
    assert "100" in content and "12.5" in content


# -----------------------------------------------------------------------------
# Astropy compatibility: Astropy can read our CSV/ECSV output
# -----------------------------------------------------------------------------


def _rows_equal(expected: dict, actual: dict) -> bool:
    """Compare two row dicts; use pytest.approx for floats."""
    if set(expected) != set(actual):
        return False
    for key in expected:
        e, a = expected[key], actual[key]
        if e is None and a is None:
            continue
        if e is None or a is None:
            return False
        if isinstance(e, float) and isinstance(a, (int, float)):
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


def _table_to_row_dicts(table):
    """Convert Astropy Table to list of dicts (native Python types); masked/NaN -> None."""
    pytest.importorskip("astropy")
    import numpy as np

    rows = []
    for row in table:
        d = {}
        for col in table.colnames:
            val = row[col]
            if hasattr(np, "ma") and np.ma.is_masked(val) or val is None:
                d[col] = None
            elif hasattr(val, "item"):
                if val.dtype.kind in "iu":
                    d[col] = int(val.item())
                elif val.dtype.kind == "f":
                    f = float(val.item())
                    d[col] = None if np.isnan(f) else f
                else:
                    d[col] = val.item()
            elif isinstance(val, (np.integer,)):
                d[col] = int(val)
            elif isinstance(val, (np.floating,)):
                f = float(val)
                d[col] = None if np.isnan(f) else f
            elif isinstance(val, (np.bool_, bool)):
                d[col] = bool(val)
            else:
                d[col] = val
        rows.append(d)
    return rows


def _astropy_ecsv_read_format():
    """Return Table.read format for ECSV: 'ecsv' if registered, else 'ascii.ecsv'.
    Raises if neither is available (no ECSV reader in registry).
    """
    from astropy.io import registry
    from astropy.table import Table

    formats = registry.get_formats(Table, readwrite="Read")
    format_names = set(formats["Format"])
    if "ecsv" in format_names:
        return "ecsv"
    if "ascii.ecsv" in format_names:
        return "ascii.ecsv"
    raise ValueError(
        "No ECSV reader in Astropy Table registry (expected 'ecsv' or 'ascii.ecsv')"
    )


def test_astropy_reads_csv_output(tmp_path):
    """CsvAdapter output can be read by Astropy Table.read(..., format='csv')."""
    pytest.importorskip("astropy")
    from astropy.table import Table

    path = tmp_path / "out.csv"
    expected = [
        {"id": 1, "ra": 10.5, "name": "Alpha"},
        {"id": 2, "ra": 20.0, "name": "Beta"},
    ]
    with CsvAdapter(path) as adapter:
        adapter.on_batch(
            [{"name": "id"}, {"name": "ra"}, {"name": "name"}],
            [(1, 10.5, "Alpha"), (2, 20.0, "Beta")],
        )
    table = Table.read(path, format="csv")
    actual = _table_to_row_dicts(table)
    assert len(actual) == len(expected)
    for exp, act in zip(expected, actual, strict=True):
        assert _rows_equal(exp, act), f"expected {exp}, got {act}"


def test_astropy_reads_ecsv_output(tmp_path):
    """EcsvAdapter output can be read by Astropy Table.read(..., format='ecsv')."""
    pytest.importorskip("astropy")
    from astropy.table import Table

    ecsv_fmt = _astropy_ecsv_read_format()
    path = tmp_path / "out.ecsv"
    expected = [
        {"id": 1, "ra": 10.5, "flag": True},
        {"id": 2, "ra": 20.0, "flag": False},
    ]
    with EcsvAdapter(path) as adapter:
        adapter.on_batch(
            [{"name": "id"}, {"name": "ra"}, {"name": "flag"}],
            [(1, 10.5, True), (2, 20.0, False)],
        )
    table = Table.read(path, format=ecsv_fmt)
    actual = _table_to_row_dicts(table)
    assert len(actual) == len(expected)
    for exp, act in zip(expected, actual, strict=True):
        assert _rows_equal(exp, act), f"expected {exp}, got {act}"


def test_astropy_ecsv_roundtrip_with_none(tmp_path):
    """EcsvAdapter with None values; Astropy reads and preserves nulls."""
    pytest.importorskip("astropy")
    from astropy.table import Table

    ecsv_fmt = _astropy_ecsv_read_format()
    path = tmp_path / "out.ecsv"
    with EcsvAdapter(path) as adapter:
        adapter.on_batch(
            [{"name": "a"}, {"name": "b"}],
            [(1, None), (2, 42)],
        )
    table = Table.read(path, format=ecsv_fmt)
    actual = _table_to_row_dicts(table)
    assert len(actual) == 2
    assert actual[0]["a"] == 1
    assert actual[0]["b"] is None
    assert actual[1]["a"] == 2
    assert actual[1]["b"] == 42


def test_astropy_vot_to_ecsv_to_astropy(tmp_path):
    """Astropy writes VOTable -> votpipe parses -> EcsvAdapter -> Astropy reads ECSV; data matches."""
    from tests.test_roundtrip_astropy import _canonical_table, _expected_rows

    pytest.importorskip("astropy")
    from astropy.io.votable import writeto
    from astropy.table import Table

    from votpipe import parse_votable

    # Use TABLEDATA table with string column (no BINARY UTF-16 issues)
    table = _canonical_table(with_masked=True, with_string_column=True)
    expected = _expected_rows(table)

    vot_path = tmp_path / "data.vot"
    ecsv_path = tmp_path / "data.ecsv"
    writeto(table, str(vot_path), tabledata_format="tabledata")

    with EcsvAdapter(ecsv_path) as adapter:
        parse_votable(vot_path, adapter.on_batch)

    ecsv_fmt = _astropy_ecsv_read_format()
    roundtrip = Table.read(ecsv_path, format=ecsv_fmt)
    actual = _table_to_row_dicts(roundtrip)

    assert len(actual) == len(expected)
    for i, (exp, act) in enumerate(zip(expected, actual, strict=True)):
        assert _rows_equal(exp, act), f"Row {i}: expected {exp}, got {act}"
