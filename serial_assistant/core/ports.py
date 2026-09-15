"""串口设备名的排序工具。

按「前缀 + 数字」自然排序，让 COM2 排在 COM10 前面；
非本机风格的名字（如 /dev/ttyUSB0）按前缀分组、组内按数字升序。
"""
from __future__ import annotations

import re

_TRAILING_NUMBER = re.compile(r"^(.*?)(\d+)$")


def port_sort_key(name: str):
    """返回排序键：有数字结尾的按（前缀, 数字）排，其余按名字排到后面。"""
    text = str(name).strip()
    match = _TRAILING_NUMBER.match(text)
    if match:
        prefix = match.group(1).upper()
        return (0, prefix, int(match.group(2)), text)
    return (1, text.upper(), 0, text)


def sort_ports(names) -> list:
    """按自然顺序排序串口名列表。"""
    return sorted((str(n) for n in names), key=port_sort_key)
