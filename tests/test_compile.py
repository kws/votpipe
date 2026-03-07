"""Direct tests of compile_row_transform (select, where, combined, errors)."""

import pytest

from votpipe._compile import compile_row_transform


def _fields(*names: str):
    """Minimal field list: name only."""
    return [{"name": n, "datatype": "double"} for n in names]


# -------------------------------------------------------------------------
# Select
# -------------------------------------------------------------------------


def test_select_identity_passthrough():
    """No select -> all columns, same order."""
    fields = _fields("a", "b", "c")
    out_fields, transform = compile_row_transform(fields)
    assert [f["name"] for f in out_fields] == ["a", "b", "c"]
    rows = [(1, 2, 3), (4, 5, 6)]
    assert transform(rows) == rows


def test_select_subset():
    """Select subset of columns."""
    fields = _fields("a", "b", "c")
    out_fields, transform = compile_row_transform(fields, select="a,c")
    assert [f["name"] for f in out_fields] == ["a", "c"]
    rows = [(1, 2, 3), (4, 5, 6)]
    assert transform(rows) == [(1, 3), (4, 6)]


def test_select_reorder():
    """Select reorders columns."""
    fields = _fields("x", "y", "z")
    out_fields, transform = compile_row_transform(fields, select="z,x,y")
    assert [f["name"] for f in out_fields] == ["z", "x", "y"]
    rows = [(10, 20, 30)]
    assert transform(rows) == [(30, 10, 20)]


def test_select_unknown_column_raises():
    """Unknown column in select raises."""
    fields = _fields("a", "b")
    with pytest.raises(ValueError, match="Unknown column in select: 'c'"):
        compile_row_transform(fields, select="a,c,b")


def test_select_invalid_clause_raises():
    """Malformed select (empty segment) raises."""
    fields = _fields("a", "b")
    with pytest.raises(ValueError, match="Invalid --select clause"):
        compile_row_transform(fields, select="a,,b")


# -------------------------------------------------------------------------
# Where
# -------------------------------------------------------------------------


def test_where_simple_comparison():
    """Single comparison filters rows."""
    fields = _fields("ra", "dec")
    _, transform = compile_row_transform(fields, where="ra > 10")
    rows = [(5, 0), (15, 1), (20, 2)]
    assert transform(rows) == [(15, 1), (20, 2)]


def test_where_chained_comparison():
    """Chained comparison (e.g. 0 < x <= 10)."""
    fields = _fields("parallax")
    _, transform = compile_row_transform(fields, where="0 < parallax <= 10")
    rows = [(0,), (5,), (10,), (15,)]
    assert transform(rows) == [(5,), (10,)]


def test_where_and_or_not():
    """Boolean and, or, not."""
    fields = _fields("a", "b")
    _, transform = compile_row_transform(fields, where="a > 1 and b < 10")
    rows = [(0, 5), (2, 5), (2, 15)]
    assert transform(rows) == [(2, 5)]

    _, transform2 = compile_row_transform(fields, where="a > 5 or b < 2")
    rows2 = [(0, 0), (0, 5), (10, 5)]
    assert transform2(rows2) == [(0, 0), (10, 5)]

    _, transform3 = compile_row_transform(fields, where="not (a > 5)")
    rows3 = [(3, 0), (10, 0)]
    assert transform3(rows3) == [(3, 0)]


def test_where_is_none_is_not_none():
    """is None / is not None in where."""
    fields = _fields("x")
    _, transform_none = compile_row_transform(fields, where="x is None")
    assert transform_none([(None,), (1,)]) == [(None,)]

    _, transform_not_none = compile_row_transform(fields, where="x is not None")
    assert transform_not_none([(None,), (1,), (2,)]) == [(1,), (2,)]


def test_where_null_safe_comparison():
    """Nullable column comparison gets null guard (no row with None passes)."""
    fields = _fields("parallax")
    _, transform = compile_row_transform(fields, where="parallax > 10")
    rows = [(5,), (None,), (15,)]
    assert transform(rows) == [(15,)]


def test_where_equals_none_rejected():
    """== None / != None raise; must use is None / is not None."""
    fields = _fields("x")
    with pytest.raises(ValueError, match="Use 'is None' or 'is not None'"):
        compile_row_transform(fields, where="x == None")
    with pytest.raises(ValueError, match="Use 'is None' or 'is not None'"):
        compile_row_transform(fields, where="x != None")


def test_where_string_and_bool_constants():
    """String and bool constants in expressions."""
    fields = _fields("name", "active")
    _, transform = compile_row_transform(
        fields, where='name == "gaia" and active == True'
    )
    rows = [("gaia", True), ("hip", True), ("gaia", False)]
    assert transform(rows) == [("gaia", True)]


def test_where_unknown_column_raises():
    """Unknown column in where raises."""
    fields = _fields("a", "b")
    with pytest.raises(ValueError, match="Unknown column in where clause: 'c'"):
        compile_row_transform(fields, where="c > 0")


def test_where_invalid_expression_raises():
    """Invalid where syntax raises (SyntaxError from ast.parse)."""
    fields = _fields("a")
    with pytest.raises(ValueError, match="Invalid where expression"):
        compile_row_transform(fields, where="a [")  # invalid syntax


def test_where_unsupported_expression_raises():
    """Unsupported AST (e.g. arithmetic, function call) raises."""
    fields = _fields("a", "b")
    with pytest.raises(
        ValueError, match="Unsupported value element|Unsupported expression"
    ):
        compile_row_transform(fields, where="a + b > 0")
    with pytest.raises(ValueError, match="Unsupported"):
        compile_row_transform(fields, where="len(a) > 0")


# -------------------------------------------------------------------------
# Combined select + where
# -------------------------------------------------------------------------


def test_select_and_where_combined():
    """Select subset and filter."""
    fields = _fields("id", "ra", "dec")
    out_fields, transform = compile_row_transform(
        fields,
        select="id,dec",
        where="ra >= 20",
    )
    assert [f["name"] for f in out_fields] == ["id", "dec"]
    rows = [(1, 10, 100), (2, 20, 200), (3, 30, 300)]
    assert transform(rows) == [(2, 200), (3, 300)]


# -------------------------------------------------------------------------
# Field / name errors
# -------------------------------------------------------------------------


def test_duplicate_field_name_raises():
    """Duplicate field name in fields raises."""
    fields = [
        {"name": "a", "datatype": "int"},
        {"name": "a", "datatype": "int"},
    ]
    with pytest.raises(ValueError, match="Duplicate field name: 'a'"):
        compile_row_transform(fields)


def test_field_without_name_raises():
    """Field missing name raises."""
    fields = [{"datatype": "int"}]  # no "name"
    with pytest.raises(ValueError, match="Field at position 0 has no name"):
        compile_row_transform(fields)


# -------------------------------------------------------------------------
# Edge cases
# -------------------------------------------------------------------------


def test_unary_plus_minus_on_column():
    """Unary + and - on column refs in where."""
    fields = _fields("x")
    _, transform_neg = compile_row_transform(fields, where="-x > 0")
    assert transform_neg([(1,), (-1,), (-2,)]) == [(-1,), (-2,)]

    _, transform_plus = compile_row_transform(fields, where="+x >= 0")
    assert transform_plus([(-1,), (0,), (1,)]) == [(0,), (1,)]


def test_empty_batch():
    """Transform of empty list returns empty list."""
    fields = _fields("a", "b")
    _, transform = compile_row_transform(fields, where="a > 0")
    assert transform([]) == []
