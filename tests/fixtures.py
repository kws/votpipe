"""
Minimal valid VOTable XML fixtures for tests.
Each factory returns bytes (UTF-8) of a complete VOTable document.
"""


class BatchCollector:
    """Collects fields and rows from parse_votable(..., on_batch=...)."""

    def __init__(self):
        self.fields = None
        self.rows = []
        self.calls = 0

    def on_batch(self, fields, rows):
        self.calls += 1
        if self.fields is None:
            self.fields = fields
        else:
            assert self.fields == fields
        self.rows.extend(rows)

    def get_field(self, name):
        return next(f for f in self.fields if f["name"] == name)

    def as_dicts(self) -> list[dict]:
        """Return rows as list of dicts (one per row, keyed by field name)."""
        field_names = [f["name"] for f in self.fields]
        return [dict(zip(field_names, row, strict=True)) for row in self.rows]


def _votable_wrapper(content: str) -> bytes:
    """Wrap TABLE content in minimal VOTABLE/RESOURCE/TABLE/DATA."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<VOTABLE version="1.4" xmlns="http://www.ivoa.net/xml/VOTable/v1.4">
  <RESOURCE>
    <TABLE>
{content}
    </TABLE>
  </RESOURCE>
</VOTABLE>
""".encode()


def tabledata_vot(
    fields: list[dict] | None = None,
    rows: list[list[str]] | None = None,
) -> bytes:
    """
    Build a VOTable with TABLEDATA serialization.

    fields: list of {"name": str, "datatype": str, "arraysize": str|None}
    rows: list of row cell value strings (same order as fields)
    """
    if fields is None:
        fields = [
            {"name": "id", "datatype": "int"},
            {"name": "ra", "datatype": "double"},
        ]
    if rows is None:
        rows = [["1", "10.5"], ["2", "20.0"]]

    field_lines = []
    for f in fields:
        attrs = f'name="{f["name"]}" datatype="{f["datatype"]}"'
        if f.get("arraysize"):
            attrs += f' arraysize="{f["arraysize"]}"'
        field_lines.append(f"      <FIELD {attrs}/>")

    row_lines = []
    for row in rows:
        tds = "".join(f"<TD>{v}</TD>" for v in row)
        row_lines.append(f"        <TR>{tds}</TR>")

    data_content = (
        """
      <DATA>
        <TABLEDATA>
"""
        + "\n".join(row_lines)
        + """
        </TABLEDATA>
      </DATA>
"""
    )
    table_content = "\n".join(field_lines) + data_content
    return _votable_wrapper(table_content)


def binary_vot(
    fields: list[dict],
    row_bytes_list: list[bytes],
) -> bytes:
    """
    Build a VOTable with BINARY serialization (no null mask).
    row_bytes_list: list of raw binary row bytes (one per row), big-endian.
    """
    import base64

    raw = b"".join(row_bytes_list)
    b64 = base64.b64encode(raw).decode("ascii")

    field_lines = []
    for f in fields:
        attrs = f'name="{f["name"]}" datatype="{f["datatype"]}"'
        if f.get("arraysize"):
            attrs += f' arraysize="{f["arraysize"]}"'
        field_lines.append(f"      <FIELD {attrs}/>")

    content = (
        "\n".join(field_lines)
        + f"""
      <DATA>
        <BINARY>
          <STREAM>{b64}</STREAM>
        </BINARY>
      </DATA>
"""
    )
    return _votable_wrapper(content)


def binary2_vot(
    fields: list[dict],
    row_bytes_list: list[bytes],
) -> bytes:
    """
    Build a VOTable with BINARY2 serialization (with null mask).
    row_bytes_list: list of raw binary row bytes (null mask + data per row), big-endian.
    """
    import base64

    raw = b"".join(row_bytes_list)
    b64 = base64.b64encode(raw).decode("ascii")

    field_lines = []
    for f in fields:
        attrs = f'name="{f["name"]}" datatype="{f["datatype"]}"'
        if f.get("arraysize"):
            attrs += f' arraysize="{f["arraysize"]}"'
        field_lines.append(f"      <FIELD {attrs}/>")

    content = (
        "\n".join(field_lines)
        + f"""
      <DATA>
        <BINARY2>
          <STREAM>{b64}</STREAM>
        </BINARY2>
      </DATA>
"""
    )
    return _votable_wrapper(content)
