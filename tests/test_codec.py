import pytest

from serial_assistant.core.codec import (
    bytes_to_hex,
    encode_payload,
    hex_to_bytes,
    parse_escapes,
)


def test_parse_escapes_plain_text():
    assert parse_escapes("Hello") == b"Hello"


def test_parse_escapes_common_sequences():
    assert parse_escapes(r"A\nB") == b"A\nB"
    assert parse_escapes(r"A\r\nB") == b"A\r\nB"
    assert parse_escapes(r"\t\\\0") == b"\t\\\x00"


def test_parse_escapes_hex_byte():
    assert parse_escapes(r"\x41\x42") == b"AB"
    assert parse_escapes(r"\xFF") == b"\xff"


def test_parse_escapes_chinese_utf8():
    assert parse_escapes("中文") == "中文".encode("utf-8")


def test_parse_escapes_invalid():
    with pytest.raises(ValueError):
        parse_escapes(r"\xZZ")
    with pytest.raises(ValueError):
        parse_escapes("abc\\")
    with pytest.raises(ValueError):
        parse_escapes(r"\q")


def test_hex_to_bytes_forms():
    assert hex_to_bytes("01 03 00 0A") == bytes([1, 3, 0, 10])
    assert hex_to_bytes("0103000A") == bytes([1, 3, 0, 10])
    assert hex_to_bytes("0x01,0x03;0x0A") == bytes([1, 3, 10])
    assert hex_to_bytes("") == b""


def test_hex_to_bytes_invalid():
    with pytest.raises(ValueError):
        hex_to_bytes("0A B")
    with pytest.raises(ValueError):
        hex_to_bytes("GG")


def test_bytes_to_hex_round_trip():
    data = bytes(range(16))
    assert bytes_to_hex(data) == "00 01 02 03 04 05 06 07 08 09 0A 0B 0C 0D 0E 0F"


def test_encode_payload_modes():
    assert encode_payload("41 42", True) == b"AB"
    assert encode_payload(r"A\n", False, True) == b"A\n"
    assert encode_payload(r"A\n", False, False) == "A\\n".encode("utf-8")
