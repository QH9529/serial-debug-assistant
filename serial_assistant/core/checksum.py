"""校验和计算：CRC16-Modbus / SUM8 / LRC。"""
from __future__ import annotations

CHECKSUM_NAMES = ("none", "crc16", "sum8", "lrc")


def crc16_modbus(data: bytes) -> int:
    """CRC16/MODBUS：多项式 0xA001（0x8005 反射），初值 0xFFFF。

    标准校验值：crc16_modbus(b"123456789") == 0x4B37
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def crc16_modbus_bytes(data: bytes) -> bytes:
    """CRC16-Modbus 附加字节，低字节在前（Modbus RTU 惯例）。"""
    crc = crc16_modbus(data)
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def sum8(data: bytes) -> int:
    """8 位累加和。"""
    return sum(data) & 0xFF


def lrc(data: bytes) -> int:
    """LRC：各字节之和取反加一（Modbus ASCII 惯例）。"""
    return (-sum(data)) & 0xFF


def append_checksum(data: bytes, kind: str) -> bytes:
    """按类型在数据尾部追加校验字节；kind == 'none' 时原样返回。"""
    if kind == "none":
        return bytes(data)
    if kind == "crc16":
        return bytes(data) + crc16_modbus_bytes(data)
    if kind == "sum8":
        return bytes(data) + bytes([sum8(data)])
    if kind == "lrc":
        return bytes(data) + bytes([lrc(data)])
    raise ValueError(f"未知校验类型：{kind!r}")
