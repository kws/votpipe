"""
Round-trip tests: Astropy writes VOTable (TABLEDATA, BINARY, BINARY2), votpipe parses and we compare rows.
"""

import tempfile
from pathlib import Path

import pytest

from tests.fixtures import BatchCollector
from votpipe import parse_votable


def _canonical_table(with_masked: bool, with_string_column: bool = False):
    """Build canonical Astropy Table. If with_masked, one column has a masked value (for BINARY2/TABLEDATA).
    If with_string_column, add a 'name' column (only used for TABLEDATA; Astropy writes unicodeChar as
    UTF-16 in BINARY/BINARY2 which votpipe does not support).
    """
    pytest.importorskip("astropy")
    from astropy.table import MaskedColumn, Table

    id_col = [1, 2, 3, 4, 5, 6]
    ra_col = [10.0, 20.5, 30.25, 40.0, 50.0, 60.0]
    mag_col = [12.5, 15.0, 14.0, 16.5, 11.0, 13.0]
    flag_col = [True, False, True, False, True, False]

    if with_masked:
        mag_col = MaskedColumn(mag_col, mask=[False, True, False, False, True, False])
    data = {
        "id": id_col,
        "ra": ra_col,
        "mag": mag_col,
        "flag": flag_col,
    }
    if with_string_column:
        data["name"] = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"]
    return Table(data)


def _expected_rows(table):
    """Convert Astropy table to list of dicts with Python types; masked -> None."""
    import numpy as np

    rows = []
    for row in table:
        d = {}
        for col in table.colnames:
            val = row[col]
            if np.ma.is_masked(val):
                d[col] = None
            elif hasattr(val, "dtype") and val.dtype.kind in "UO":
                d[col] = str(val).strip() if val is not None else None
            elif hasattr(val, "dtype") and val.dtype.kind == "S":
                d[col] = (
                    val.decode("utf-8").strip()
                    if hasattr(val, "decode")
                    else str(val).strip()
                )
            elif hasattr(val, "item"):
                d[col] = val.item() if val.dtype.kind in "iu" else float(val)
            elif isinstance(val, np.integer):
                d[col] = int(val)
            elif isinstance(val, np.floating):
                d[col] = float(val)
            elif isinstance(val, bytes):
                d[col] = val.decode("utf-8").strip()
            elif isinstance(val, str):
                d[col] = val.strip() if val is not None else None
            else:
                d[col] = None if val is None else val
        rows.append(d)
    return rows


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
        if isinstance(e, float) and isinstance(a, int | float):
            if pytest.approx(e, rel=1e-09) != a:
                return False
            continue
        if isinstance(e, str) and isinstance(a, str):
            if e.strip() != a.strip():
                return False
            continue
        if type(e).__name__ in ("bool", "bool_") and type(a).__name__ in (
            "bool",
            "bool_",
        ):
            if bool(e) != bool(a):
                return False
            continue
        # Astropy table may yield float 0.0/1.0 for bit column; votpipe yields bool
        if isinstance(e, int | float) and isinstance(a, bool):
            if bool(e) != bool(a):
                return False
            continue
        if isinstance(e, bool) and isinstance(a, int | float):
            if bool(e) != bool(a):
                return False
            continue
        if e != a:
            return False
    return True


@pytest.mark.parametrize("format", ["tabledata", "binary", "binary2"])
def test_roundtrip_astropy_format(format):
    """Astropy writes VOTable in given format; votpipe parses it; rows match."""
    pytest.importorskip("astropy")
    from astropy.io.votable import writeto

    # BINARY has no null mask: use table without masked column.
    # Include string column only for TABLEDATA (Astropy writes unicodeChar as UTF-16 in BINARY/BINARY2).
    with_masked = format != "binary"
    with_string_column = format == "tabledata"
    table = _canonical_table(
        with_masked=with_masked, with_string_column=with_string_column
    )
    expected = _expected_rows(table)

    with tempfile.NamedTemporaryFile(suffix=".vot", delete=False) as f:
        path = Path(f.name)
    try:
        writeto(table, str(path), tabledata_format=format)
        collector = BatchCollector()
        parse_votable(path, collector.on_batch)
    finally:
        path.unlink(missing_ok=True)

    assert len(collector.rows) == len(expected), "Row count mismatch"
    for i, (exp_row, act_row) in enumerate(
        zip(expected, collector.as_dicts(), strict=True)
    ):
        assert _rows_equal(exp_row, act_row), (
            f"Row {i} mismatch: expected {exp_row}, got {act_row}"
        )
