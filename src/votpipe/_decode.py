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


def has_variable_length_fields(fields: list[dict]) -> bool:
    """Return True when a BINARY/BINARY2 row cannot use a fixed struct layout."""
    return any(_is_variable_length_field(field) for field in fields)


def _is_variable_length_field(field: dict) -> bool:
    arraysize = (field.get("arraysize") or "1").strip()
    return "*" in arraysize


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


def apply_null_mask(raw_values: tuple, mask_bytes: bytes) -> tuple:
    """Apply a BINARY2 null-flag bitmask to unpacked struct values.

    For each field, if the corresponding bit in *mask_bytes* is set the value
    becomes ``None``.  Otherwise ``bytes`` values (fixed-length char fields)
    are decoded to UTF-8 strings with trailing whitespace stripped.
    """
    return tuple(
        None
        if (mask_bytes[i // 8] & (1 << (7 - (i % 8)))) != 0
        else (val.decode("utf-8").rstrip() if isinstance(val, bytes) else val)
        for i, val in enumerate(raw_values)
    )


def decode_binary_row(struct_fmt, buf, offset):
    return struct.unpack_from(struct_fmt, buf, offset)


def decode_binary2_row(
    struct_fmt: str,
    null_mask_bytes: int,
    buf,
    offset: int,
) -> tuple:
    """Unpack a single BINARY2 row from a buffer at a given offset."""
    if null_mask_bytes == 0:
        raise ValueError("BINARY2 requires null_mask_bytes > 0")

    mask_bytes = buf[offset : offset + null_mask_bytes]
    raw_values = struct.unpack_from(struct_fmt, buf, offset + null_mask_bytes)
    return apply_null_mask(raw_values, mask_bytes)


def decode_variable_binary_row(
    fields: list[dict],
    buf,
    offset: int,
    *,
    binary2: bool,
) -> tuple[tuple | None, int]:
    """Decode one possibly variable-length BINARY/BINARY2 row.

    Variable-length fields are prefixed by a big-endian 32-bit element count in
    VOTable BINARY streams. If the current buffer does not yet contain a whole
    row, returns ``(None, offset)`` so the streaming parser can wait for more
    bytes.
    """
    null_mask_bytes = ((len(fields) + 7) // 8) if binary2 else 0
    if len(buf) - offset < null_mask_bytes:
        return None, offset

    pos = offset
    mask_bytes = b""
    if binary2:
        mask_bytes = bytes(buf[pos : pos + null_mask_bytes])
        pos += null_mask_bytes

    values: list[object] = []
    for index, field in enumerate(fields):
        decoded = _decode_field_value(field, buf, pos)
        if decoded is None:
            return None, offset
        value, pos = decoded
        if binary2 and (mask_bytes[index // 8] & (1 << (7 - (index % 8)))) != 0:
            value = None
        values.append(value)

    return tuple(values), pos


def _decode_field_value(field: dict, buf, offset: int) -> tuple[object, int] | None:
    datatype = (field.get("datatype") or "int").strip().lower()
    arraysize = (field.get("arraysize") or "1").strip()

    if datatype in ("char", "unicodechar"):
        return _decode_char_value(datatype, arraysize, buf, offset)
    if "*" in arraysize:
        raise NotImplementedError(
            f"Variable-length arrays are only supported for char fields: {datatype!r}"
        )

    fmt = BINARY_TYPE_MAP.get(datatype)
    if fmt is None:
        raise NotImplementedError(f"Unsupported BINARY datatype: {datatype!r}")
    size = struct.calcsize(">" + fmt)
    if len(buf) - offset < size:
        return None
    return struct.unpack_from(">" + fmt, buf, offset)[0], offset + size


def _decode_char_value(
    datatype: str,
    arraysize: str,
    buf,
    offset: int,
) -> tuple[str | None, int] | None:
    if "x" in arraysize:
        raise NotImplementedError(f"Unsupported arraysize for char: {arraysize!r}")

    if "*" in arraysize:
        if len(buf) - offset < 4:
            return None
        count = struct.unpack_from(">i", buf, offset)[0]
        if count < 0:
            raise ValueError(f"Invalid variable-length char count: {count}")
        data_offset = offset + 4
        byte_count = count if datatype == "char" else count * 2
        if len(buf) - data_offset < byte_count:
            return None
        raw = bytes(buf[data_offset : data_offset + byte_count])
        return _decode_char_bytes(raw, datatype), data_offset + byte_count

    try:
        count = int(arraysize)
    except ValueError:
        raise NotImplementedError(
            f"Unsupported arraysize for char: {arraysize!r}"
        ) from None
    if count < 1:
        raise NotImplementedError(f"Invalid char arraysize: {count}")
    byte_count = count if datatype == "char" else count * 2
    if len(buf) - offset < byte_count:
        return None
    raw = bytes(buf[offset : offset + byte_count])
    return _decode_char_bytes(raw, datatype), offset + byte_count


def _decode_char_bytes(raw: bytes, datatype: str) -> str:
    encoding = "utf-16-be" if datatype == "unicodechar" else "utf-8"
    return raw.decode(encoding).rstrip()


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
