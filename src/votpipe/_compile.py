"""
Compile select/where expressions into a row transform function.

Public API: compile_row_transform(fields, select=None, where=None)
returns (out_fields, transform_batch) where transform_batch(rows) -> rows.

Supported where syntax: column names, numeric/string/bool/None constants,
and/or/not, == != < <= > >=, is None / is not None, chained comparisons.
Comparisons against nullable columns are compiled null-safe.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from typing import Any

Field = dict[str, Any]
Row = tuple[Any, ...]


def compile_row_transform(
    fields: list[Field],
    *,
    select: str | None = None,
    where: str | None = None,
) -> tuple[list[Field], Callable[[list[Row]], list[Row]]]:
    """
    Compile select and where into output field list and a batch transform.

    Returns
    -------
    out_fields : list of field dicts (subset/reorder per select)
    transform_batch : callable(list[Row]) -> list[Row]
    """
    name_to_index = _build_name_to_index(fields)
    selected_indices, out_fields = _compile_select(fields, name_to_index, select)
    where_src = _compile_where(where, name_to_index) if where else None
    transform_batch = _build_batch_function(
        selected_indices=selected_indices,
        where_src=where_src,
        input_width=len(fields),
    )
    return out_fields, transform_batch


# -------------------------------------------------------------------------
# Name/index and select
# -------------------------------------------------------------------------


def _build_name_to_index(fields: list[Field]) -> dict[str, int]:
    name_to_index: dict[str, int] = {}
    for i, field in enumerate(fields):
        name = field.get("name", "")
        if not name:
            raise ValueError(f"Field at position {i} has no name")
        if name in name_to_index:
            raise ValueError(f"Duplicate field name: {name!r}")
        name_to_index[name] = i
    return name_to_index


def _compile_select(
    fields: list[Field],
    name_to_index: dict[str, int],
    select: str | None,
) -> tuple[tuple[int, ...], list[Field]]:
    if not select:
        indices = tuple(range(len(fields)))
        return indices, list(fields)

    names = [part.strip() for part in select.split(",")]
    if not names or any(not name for name in names):
        raise ValueError("Invalid --select clause")

    indices: list[int] = []
    out_fields: list[Field] = []

    for name in names:
        try:
            idx = name_to_index[name]
        except KeyError as e:
            raise ValueError(f"Unknown column in select: {name!r}") from e
        indices.append(idx)
        out_fields.append(fields[idx])

    return tuple(indices), out_fields


def _compile_where(where: str, name_to_index: dict[str, int]) -> str:
    try:
        tree = ast.parse(where, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"Invalid where expression: {where!r}") from e

    return _emit_expr(tree.body, name_to_index)


def _build_batch_function(
    *,
    selected_indices: tuple[int, ...],
    where_src: str | None,
    input_width: int,
) -> Callable[[list[Row]], list[Row]]:
    identity_projection = selected_indices == tuple(range(input_width))

    if identity_projection:
        projection_src = "row"
    else:
        projection_src = "(" + ", ".join(f"row[{i}]" for i in selected_indices) + ",)"

    if where_src is None and identity_projection:

        def transform_batch(rows: list[Row]) -> list[Row]:
            return rows

        return transform_batch

    lines = [
        "def transform_batch(rows):",
        "    out = []",
        "    append = out.append",
        "    for row in rows:",
    ]

    if where_src is not None:
        lines.append(f"        if {where_src}:")
        lines.append(f"            append({projection_src})")
    else:
        lines.append(f"        append({projection_src})")

    lines.append("    return out")

    namespace: dict[str, Any] = {}
    source = "\n".join(lines)
    exec(source, namespace)  # noqa: S102 - source is generated from validated AST only
    return namespace["transform_batch"]


# -------------------------------------------------------------------------
# Expression compiler (where clause AST -> source string)
# -------------------------------------------------------------------------


def _emit_expr(node: ast.AST, name_to_index: dict[str, int]) -> str:
    if isinstance(node, ast.BoolOp):
        op = _bool_op_str(node.op)
        values = [_emit_expr(v, name_to_index) for v in node.values]
        return "(" + f" {op} ".join(values) + ")"

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return f"(not {_emit_expr(node.operand, name_to_index)})"

    if isinstance(node, ast.Compare):
        return _emit_compare(node, name_to_index)

    if isinstance(node, ast.Name):
        return _emit_value(node, name_to_index)

    if isinstance(node, ast.Constant):
        return _emit_value(node, name_to_index)

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd | ast.USub):
        return _emit_value(node, name_to_index)

    raise ValueError(
        f"Unsupported expression element: {node.__class__.__name__}. "
        "Supported: names, constants, and/or/not, comparisons, is None."
    )


def _emit_compare(node: ast.Compare, name_to_index: dict[str, int]) -> str:
    operands = [node.left, *node.comparators]
    terms: list[str] = []

    for left_node, op_node, right_node in zip(
        operands[:-1], node.ops, operands[1:], strict=True
    ):
        left_src = _emit_value(left_node, name_to_index)
        right_src = _emit_value(right_node, name_to_index)

        if isinstance(op_node, ast.Is):
            _require_none_identity_compare(left_node, right_node)
            terms.append(f"({left_src} is {right_src})")
            continue

        if isinstance(op_node, ast.IsNot):
            _require_none_identity_compare(left_node, right_node)
            terms.append(f"({left_src} is not {right_src})")
            continue

        if _is_none_literal(left_node) or _is_none_literal(right_node):
            raise ValueError("Use 'is None' or 'is not None', not == None / != None")

        op_src = _compare_op_str(op_node)

        guards: list[str] = []
        if _is_nullable_value_node(left_node):
            guards.append(f"({left_src} is not None)")
        if _is_nullable_value_node(right_node):
            guards.append(f"({right_src} is not None)")

        cmp_src = f"({left_src} {op_src} {right_src})"
        if guards:
            terms.append("(" + " and ".join([*guards, cmp_src]) + ")")
        else:
            terms.append(cmp_src)

    return "(" + " and ".join(terms) + ")"


def _emit_value(node: ast.AST, name_to_index: dict[str, int]) -> str:
    if isinstance(node, ast.Name):
        try:
            idx = name_to_index[node.id]
        except KeyError as e:
            raise ValueError(f"Unknown column in where clause: {node.id!r}") from e
        return f"row[{idx}]"

    if isinstance(node, ast.Constant):
        if isinstance(node.value, int | float | str | bool) or node.value is None:
            return repr(node.value)
        raise ValueError(
            f"Unsupported constant type in where clause: {type(node.value).__name__}"
        )

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
        operand = _emit_value(node.operand, name_to_index)
        return f"(+{operand})"

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        operand = _emit_value(node.operand, name_to_index)
        return f"(-{operand})"

    raise ValueError(
        f"Unsupported value element in where clause: {node.__class__.__name__}"
    )


def _bool_op_str(op: ast.boolop) -> str:
    if isinstance(op, ast.And):
        return "and"
    if isinstance(op, ast.Or):
        return "or"
    raise ValueError(f"Unsupported boolean operator: {op.__class__.__name__}")


def _compare_op_str(op: ast.cmpop) -> str:
    mapping = {
        ast.Eq: "==",
        ast.NotEq: "!=",
        ast.Lt: "<",
        ast.LtE: "<=",
        ast.Gt: ">",
        ast.GtE: ">=",
    }
    for cls, text in mapping.items():
        if isinstance(op, cls):
            return text
    raise ValueError(
        f"Unsupported comparison operator: {op.__class__.__name__}. "
        "Supported: ==, !=, <, <=, >, >=, is None, is not None."
    )


def _is_none_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _require_none_identity_compare(left_node: ast.AST, right_node: ast.AST) -> None:
    if not (_is_none_literal(left_node) or _is_none_literal(right_node)):
        raise ValueError("'is' / 'is not' are only supported with None")


def _is_nullable_value_node(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd | ast.USub):
        return isinstance(node.operand, ast.Name)
    return False
