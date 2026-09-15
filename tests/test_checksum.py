import pytest

from serial_assistant.core.checksum import (
    append_checksum,
    crc16_modbus,
    crc16_modbus_bytes,
    lrc,
    sum8,
)


def test_crc16_modbus_standard_check_value():
    # CRC-16/MODBUS 的标准校验值
    assert crc16_modbus(b"123456789") == 0x4B37


def test_crc16_modbus_byte_order_low_first():
    data = b"123456789"
    crc = crc16_modbus(data)
    assert crc16_modbus_bytes(data) == bytes([crc & 0xFF, crc >> 8])


def test_crc16_modbus_modbus_frame():
    # Modbus RTU 常见示例帧：01 03 00 00 00 0A -> CRC C5 CD（低字节在前）
    frame = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x0A])
    crc = crc16_modbus(frame)
    assert crc & 0xFF == 0xC5
    assert crc >> 8 == 0xCD


def test_sum8():
    assert sum8(b"\x01\x02\x03") == 6
    assert sum8(b"\xff\x01") == 0x00


def test_lrc_two_complement():
    assert lrc(b"\x01\x02\x03") == 0xFA
    assert lrc(b"\x00") == 0x00


def test_append_checksum():
    data = b"\x01\x03"
    assert append_checksum(data, "none") == data
    assert append_checksum(data, "sum8") == data + bytes([4])
    assert append_checksum(data, "lrc") == data + bytes([0xFC])
    assert len(append_checksum(data, "crc16")) == len(data) + 2
    with pytest.raises(ValueError):
        append_checksum(data, "md5")
