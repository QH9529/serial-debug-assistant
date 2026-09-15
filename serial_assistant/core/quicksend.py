"""快捷发送条目（一键发送 + 自定义快捷键）的模型与序列化。"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from .checksum import CHECKSUM_NAMES

MAX_SLOTS = 24
MAX_HISTORY = 20


@dataclass
class QuickSlot:
    """一条快捷发送配置。"""

    label: str = ""
    content: str = ""
    is_hex: bool = False
    checksum: str = "none"
    hotkey: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data) -> "QuickSlot":
        if not isinstance(data, dict):
            data = {}
        checksum = str(data.get("checksum", "none"))
        if checksum not in CHECKSUM_NAMES:
            checksum = "none"
        return cls(
            label=str(data.get("label", "")),
            content=str(data.get("content", "")),
            is_hex=bool(data.get("is_hex", False)),
            checksum=checksum,
            hotkey=str(data.get("hotkey", "")),
        )

    def display_label(self, limit: int = 12) -> str:
        """按钮上显示的文字：优先用备注名，其次截断内容。"""
        text = self.label.strip() or self.content.strip().replace("\n", " ").replace("\r", " ")
        if not text:
            return "(空)"
        return text if len(text) <= limit else text[: limit - 1] + "…"


def dump_slots(slots) -> str:
    """把快捷条列表序列化为设置里保存的 JSON 字符串。"""
    return json.dumps([s.to_dict() for s in slots], ensure_ascii=False)


def load_slots(raw) -> list:
    """从设置字符串还原快捷条；容错：非法数据返回空列表。"""
    if not raw:
        return []
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, (list, tuple)):
        return [QuickSlot.from_dict(x) for x in raw][:MAX_SLOTS]
    try:
        data = json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [QuickSlot.from_dict(x) for x in data][:MAX_SLOTS]


def push_history(history, text: str, is_hex: bool, limit: int = MAX_HISTORY) -> list:
    """把一次发送压入历史：去重、最新在前、长度受限。"""
    text = str(text)
    if not text.strip():
        return list(history)
    entry = {"text": text, "is_hex": bool(is_hex)}
    rest = [h for h in history if not (h.get("text") == text and bool(h.get("is_hex")) == bool(is_hex))]
    return ([entry] + rest)[:limit]


def history_from_raw(raw) -> list:
    """容错解析历史记录（设置里存 JSON 字符串）。"""
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        data = list(raw)
    else:
        try:
            data = json.loads(str(raw))
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data[:MAX_HISTORY]:
        if isinstance(item, dict) and item.get("text"):
            out.append({"text": str(item["text"]), "is_hex": bool(item.get("is_hex", False))})
    return out


def dump_history(history) -> str:
    return json.dumps(list(history), ensure_ascii=False)
