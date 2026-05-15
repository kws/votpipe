"""Unit tests for votpipe._decode pure helpers."""

import struct

import pytest

from votpipe._decode import (
    build_struct_format,
    cast_tabledata_value,
    decode_binary2_row,
    decode_binary_row,
    decode_variable_binary_row,
    has_variable_length_fields,
)


class TestBuildStructFormat:
    def test_binary_two_int(self):
        fields = [{"name": "a", "datatype": "int"}, {"name": "b", "datatype": "int"}]
        fmt, null_bytes, row_size = build_struct_format(fields, binary2=False)
        assert null_bytes == 0
        assert fmt == ">ii"
        assert row_size == 8

    def test_binary2_two_int(self):
        fields = [{"name": "a", "datatype": "int"}, {"name": "b", "datatype": "int"}]
        fmt, null_bytes, row_size = build_struct_format(fields, binary2=True)
        assert null_bytes == 1  # 2 bits -> 1 byte
        assert fmt == ">ii"
        assert row_size == 1 + 8

    def test_binary2_five_fields(self):
        fields = [{"name": f"c{i}", "datatype": "int"} for i in range(5)]
        _, null_bytes, row_size = build_struct_format(fields, binary2=True)
        assert null_bytes == 1  # 5 bits -> 1 byte
        assert row_size == 1 + 5 * 4

    def test_double_and_float(self):
        fields = [
            {"name": "ra", "datatype": "double"},
            {"name": "mag", "datatype": "float"},
        ]
        fmt, null_bytes, row_size = build_struct_format(fields, binary2=False)
        assert fmt == ">df"
        assert row_size == 12

    def test_unsupported_datatype_raises(self):
        fields = [{"name": "x", "datatype": "complex"}]
        with pytest.raises(NotImplementedError, match="Unsupported BINARY datatype"):
            build_struct_format(fields, binary2=False)

    def test_char_fixed_arraysize(self):
        fields = [{"name": "id", "datatype": "char", "arraysize": "4"}]
        fmt, null_bytes, row_size = build_struct_format(fields, binary2=False)
        assert "4s" in fmt
        assert row_size == 4

    def test_char_variable_length_raises(self):
        fields = [{"name": "x", "datatype": "char", "arraysize": "*"}]
        with pytest.raises(NotImplementedError, match="Variable-length char"):
            build_struct_format(fields, binary2=False)

    def test_detect_variable_length_fields(self):
        assert has_variable_length_fields(
            [{"name": "x", "datatype": "char", "arraysize": "*"}]
        )
        assert not has_variable_length_fields([{"name": "x", "datatype": "char"}])


class TestDecodeBinaryRow:
    def test_two_int(self):
        fields = [{"name": "a", "datatype": "int"}, {"name": "b", "datatype": "int"}]
        fmt, _, _ = build_struct_format(fields, binary2=False)
        row_bytes = struct.pack(">ii", 42, 100)
        out = decode_binary_row(fmt, row_bytes, 0)
        assert out == (42, 100)

    def test_double_float(self):
        fields = [
            {"name": "ra", "datatype": "double"},
            {"name": "mag", "datatype": "float"},
        ]
        fmt, _, _ = build_struct_format(fields, binary2=False)
        row_bytes = struct.pack(">df", 180.5, 12.25)
        out = decode_binary_row(fmt, row_bytes, 0)
        assert out[0] == 180.5
        assert out[1] == pytest.approx(12.25)


class TestDecodeBinary2Row:
    def test_two_int_no_nulls(self):
        fields = [{"name": "a", "datatype": "int"}, {"name": "b", "datatype": "int"}]
        fmt, null_bytes, row_size = build_struct_format(fields, binary2=True)
        mask = bytes([0])  # no nulls
        data = struct.pack(">ii", 1, 2)
        row_bytes = mask + data
        out = decode_binary2_row(fmt, null_bytes, row_bytes, 0)
        assert out == (1, 2)

    def test_two_int_first_null(self):
        fields = [{"name": "a", "datatype": "int"}, {"name": "b", "datatype": "int"}]
        fmt, null_bytes, _ = build_struct_format(fields, binary2=True)
        # MSB (bit 7) = column 0 null, bit 6 = column 1 null
        mask = bytes([0x80])  # column 0 null
        data = struct.pack(">ii", 0, 99)
        row_bytes = mask + data
        out = decode_binary2_row(fmt, null_bytes, row_bytes, 0)
        assert out[0] is None
        assert out[1] == 99

    def test_null_mask_bytes_zero_raises(self):
        with pytest.raises(ValueError, match="BINARY2 requires null_mask_bytes"):
            decode_binary2_row(">i", 0, struct.pack(">i", 1), 0)


class TestDecodeVariableBinaryRow:
    def test_mixed_binary_row_with_variable_char(self):
        fields = [
            {"name": "id", "datatype": "int"},
            {"name": "flags", "datatype": "char", "arraysize": "*"},
            {"name": "mag", "datatype": "float"},
        ]
        row_bytes = struct.pack(">i", 7)
        row_bytes += struct.pack(">i", 5) + b"abc  "
        row_bytes += struct.pack(">f", 12.5)

        row, offset = decode_variable_binary_row(
            fields,
            row_bytes,
            0,
            binary2=False,
        )

        assert row == (7, "abc", 12.5)
        assert offset == len(row_bytes)

    def test_incomplete_variable_char_row_waits_for_more_bytes(self):
        fields = [{"name": "flags", "datatype": "char", "arraysize": "*"}]
        row, offset = decode_variable_binary_row(
            fields,
            struct.pack(">i", 5) + b"ab",
            0,
            binary2=False,
        )

        assert row is None
        assert offset == 0

    def test_binary2_null_variable_char(self):
        fields = [
            {"name": "id", "datatype": "int"},
            {"name": "flags", "datatype": "char", "arraysize": "*"},
        ]
        mask = bytes([0x40])
        row_bytes = mask + struct.pack(">i", 9) + struct.pack(">i", 0)

        row, offset = decode_variable_binary_row(
            fields,
            row_bytes,
            0,
            binary2=True,
        )

        assert row == (9, None)
        assert offset == len(row_bytes)


class TestCastTabledataValue:
    def test_int(self):
        assert cast_tabledata_value("42", "int") == 42
        assert cast_tabledata_value("  -1  ", "int") == -1

    def test_double_float(self):
        assert cast_tabledata_value("3.14", "double") == 3.14
        assert cast_tabledata_value("2.5", "float") == 2.5

    def test_boolean(self):
        assert cast_tabledata_value("1", "boolean") is True
        assert cast_tabledata_value("true", "boolean") is True
        assert cast_tabledata_value("T", "boolean") is True
        assert cast_tabledata_value("0", "boolean") is False
        assert cast_tabledata_value("false", "boolean") is False
        assert cast_tabledata_value("F", "boolean") is False

    def test_empty_or_none_is_none(self):
        assert cast_tabledata_value("", "int") is None
        assert cast_tabledata_value("   ", "int") is None
        assert cast_tabledata_value(None, "int") is None

    def test_char_passthrough(self):
        assert cast_tabledata_value("hello", "char") == "hello"

    def test_unsigned_byte(self):
        assert cast_tabledata_value("255", "unsignedByte") == 255
        assert cast_tabledata_value("300", "unsignedByte") == 44  # 300 & 0xFF

    def test_unsupported_datatype_raises(self):
        with pytest.raises(NotImplementedError, match="Unsupported TABLEDATA datatype"):
            cast_tabledata_value("x", "complex")
