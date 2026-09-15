"""发送方案的 JSON 保存 / 加载。"""
from __future__ import annotations

import json
from pathlib import Path

from .scheduler import MODE_SEQUENTIAL, MODES, MessageItem

SCHEMA_VERSION = 1


class ProfileError(ValueError):
    """方案文件格式错误。"""


def save_profile(path, mode: str, items) -> None:
    """把调度模式与条目列表写入 JSON 文件。"""
    if mode not in MODES:
        raise ProfileError(f"未知调度模式：{mode!r}")
    payload = {
        "version": SCHEMA_VERSION,
        "mode": mode,
        "items": [it.to_dict() for it in items],
    }
    target = Path(path)
    parent = target.parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_profile(path):
    """读取 JSON 方案，返回 (mode, items)。"""
    target = Path(path)
    if not target.exists():
        raise ProfileError(f"文件不存在：{target}")
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProfileError(f"JSON 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise ProfileError("方案文件根节点必须是 JSON 对象")
    mode = data.get("mode", MODE_SEQUENTIAL)
    if mode not in MODES:
        raise ProfileError(f"未知调度模式：{mode!r}")
    raw_items = data.get("items", [])
    if not isinstance(raw_items, list):
        raise ProfileError("items 必须是数组")
    items = [MessageItem.from_dict(d) for d in raw_items]
    return mode, items
