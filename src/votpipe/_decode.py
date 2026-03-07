"""
Pure helpers for VOTable field and row decoding.
Used by the streaming parser for BINARY, BINARY2, and TABLEDATA value casting.
"""

import struct

# VOTable datatypes to Python struct format (big-endian). Scalar numeric only.
# char (fixed-length) uses "Ns" where N is arraysize; handled separately.
BINARY_TYPE_MAP = {
    "boolean": "?",
    "bit": "?",  # VOTable bit type; Astropy writes bool as bit
    "unsignedByte": "B",
    "short": "h",
    "int": "i",
    "long": "q",
    "float": "f",
    "double": "d",
}


def _field_struct_char(field: dict) -> str:
    """Struct format for a single field. Raises NotImplementedError for unsupported types."""
    datatype = (field.get("datatype") or "int").strip().lower()
    arraysize = (field.get("arraysize") or "1").strip()

    if datatype in ("char", "unicodechar"):
        if arraysize == "*" or "x" in arraysize:
            raise NotImplementedError(
                f"Variable-length char (arraysize={arraysize!r}) is not supported"
            )
        try:
            n = int(arraysize)
        except ValueError:
            raise NotImplementedError(
                f"Unsupported arraysize for char: {arraysize!r}"
            ) from None
        if n < 1:
            raise NotImplementedError(f"Invalid char arraysize: {n}")
        return f">{n}s"

    fmt = BINARY_TYPE_MAP.get(datatype)
    if fmt is None:
        raise NotImplementedError(f"Unsupported BINARY datatype: {datatype!r}")
    return ">" + fmt


def build_struct_format(fields: list[dict], binary2: bool) -> tuple[str, int, int]:
    """
    Build struct format and row layout for binary serialization.

    Args:
        fields: List of field dicts with "name", "datatype", optionally "arraysize".
        binary2: If True, include null mask (BINARY2); if False, no mask (BINARY).

    Returns:
        (struct_fmt, null_mask_bytes, row_size).
        For BINARY, null_mask_bytes is 0. row_size is total bytes per row.
    """
    null_mask_bytes = ((len(fields) + 7) // 8) if binary2 else 0
    struct_fmt = ">"
    for f in fields:
        struct_fmt += _field_struct_char(f).lstrip(">")
    data_size = struct.calcsize(struct_fmt)
    row_size = null_mask_bytes + data_size
    return (struct_fmt, null_mask_bytes, row_size)


def decode_binary2_row(
    struct_fmt: str,
    null_mask_bytes: int,
    row_bytes: bytes,
) -> tuple:
    """Unpack a single BINARY2 row into a positional tuple.

    Null-masked positions become None. Bytes values are decoded to str.
    """
    if null_mask_bytes == 0:
        raise ValueError("BINARY2 requires null_mask_bytes > 0")
    mask_bytes = row_bytes[:null_mask_bytes]
    data_bytes = row_bytes[null_mask_bytes:]
    raw_values = struct.unpack(struct_fmt, data_bytes)
    return tuple(
        None
        if (mask_bytes[i // 8] & (1 << (7 - i % 8))) != 0
        else (val.decode("utf-8").strip() if isinstance(val, bytes) else val)
        for i, val in enumerate(raw_values)
    )


def decode_binary_row(
    struct_fmt: str,
    row_bytes: bytes,
) -> tuple:
    """Unpack a single BINARY row (no null mask) into a positional tuple.

    Bytes values are decoded to str.
    """
    raw_values = struct.unpack(struct_fmt, row_bytes)
    return tuple(
        val.decode("utf-8").strip() if isinstance(val, bytes) else val
        for val in raw_values
    )


def cast_tabledata_value(raw_str: str, datatype: str) -> object:
    """
    Parse a TABLEDATA cell string to the correct Python type.
    VOTable TABLEDATA uses TCDATA string content; empty string or special nulls become None.
    """
    if raw_str is None or (isinstance(raw_str, str) and raw_str.strip() == ""):
        return None
    raw_str = raw_str.strip()
    datatype = (datatype or "int").strip().lower()

    if datatype in ("boolean", "bit"):
        if raw_str in ("1", "true", "T"):
            return True
        if raw_str in ("0", "false", "F"):
            return False
        raise ValueError(f"Invalid boolean/bit: {raw_str!r}")
    if datatype == "unsignedbyte":
        return int(raw_str) & 0xFF
    if datatype in ("short", "int", "long"):
        return int(raw_str)
    if datatype == "float":
        return float(raw_str)
    if datatype == "double":
        return float(raw_str)
    if datatype in ("char", "unicodechar"):
        return raw_str
    raise NotImplementedError(f"Unsupported TABLEDATA datatype: {datatype!r}")
