"""编码工具：转义符解析、HEX 与文本互转。"""
from __future__ import annotations

import re

_ESCAPES = {
    "n": b"\n",
    "r": b"\r",
    "t": b"\t",
    "0": b"\x00",
    "\\": b"\\",
}


def parse_escapes(text: str) -> bytes:
    """把含转义符的文本解析为字节序列。

    支持 \\n \\r \\t \\0 \\xhh \\\\；其余以反斜杠开头的序列抛 ValueError。
    普通字符按 UTF-8 编码。
    """
    out = bytearray()
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch != "\\":
            out += ch.encode("utf-8")
            i += 1
            continue
        if i + 1 >= n:
            raise ValueError(f"位置 {i}：孤立的反斜杠")
        c = text[i + 1]
        if c == "x":
            part = text[i + 2 : i + 4]
            if len(part) < 2 or any(h not in "0123456789abcdefABCDEF" for h in part):
                raise ValueError(f"位置 {i}：非法的 \\xhh 转义 {text[i:i + 4]!r}")
            out.append(int(part, 16))
            i += 4
        elif c in _ESCAPES:
            out += _ESCAPES[c]
            i += 2
        else:
            raise ValueError(f"位置 {i}：不支持的转义序列 \\{c}")
    return bytes(out)


def hex_to_bytes(text: str) -> bytes:
    """把 HEX 字符串解析为字节，允许空格、逗号、分号分隔与 0x 前缀。"""
    tokens = [t for t in re.split(r"[\s,;]+", text.strip()) if t]
    chunks = []
    for token in tokens:
        if token[:2].lower() == "0x":
            token = token[2:]
        if not token:
            continue
        if len(token) % 2:
            raise ValueError(f"HEX 片段长度必须为偶数：{token!r}")
        chunks.append(token)
    cleaned = "".join(chunks)
    if not cleaned:
        return b""
    try:
        return bytes.fromhex(cleaned)
    except ValueError as exc:
        raise ValueError(f"非法 HEX 字符：{exc}") from exc


def bytes_to_hex(data: bytes) -> str:
    return data.hex(" ").upper()


def encode_payload(text: str, is_hex: bool, use_escapes: bool = True) -> bytes:
    """按发送模式把输入文本转成待发字节。HEX 模式忽略转义开关。"""
    if is_hex:
        return hex_to_bytes(text)
    if use_escapes:
        return parse_escapes(text)
    return text.encode("utf-8")
