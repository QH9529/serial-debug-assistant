"""循环发送调度器：纯逻辑、时间可注入，便于离线测试。"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .checksum import CHECKSUM_NAMES

MODE_SEQUENTIAL = "sequential"
MODE_PER_ITEM = "per_item"
MODES = (MODE_SEQUENTIAL, MODE_PER_ITEM)

MODE_LABELS = {
    MODE_SEQUENTIAL: "顺序轮询",
    MODE_PER_ITEM: "单条周期",
}


@dataclass
class MessageItem:
    """一条可循环发送的数据。"""

    content: str = ""
    is_hex: bool = False
    interval_ms: int = 1000
    note: str = ""
    enabled: bool = True
    checksum: str = "none"

    def __post_init__(self):
        self.interval_ms = max(int(self.interval_ms), 1)

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "is_hex": self.is_hex,
            "interval_ms": self.interval_ms,
            "note": self.note,
            "enabled": self.enabled,
            "checksum": self.checksum,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MessageItem":
        if not isinstance(data, dict):
            data = {}
        try:
            interval = int(data.get("interval_ms", 1000))
        except (TypeError, ValueError):
            interval = 1000
        checksum = str(data.get("checksum", "none"))
        if checksum not in CHECKSUM_NAMES:
            checksum = "none"
        return cls(
            content=str(data.get("content", "")),
            is_hex=bool(data.get("is_hex", False)),
            interval_ms=max(interval, 1),
            note=str(data.get("note", "")),
            enabled=bool(data.get("enabled", True)),
            checksum=checksum,
        )


class LoopScheduler:
    """驱动循环发送。

    sequential：按列表顺序轮询，发送一条后等待该条自己的间隔，再发下一条（到尾后回绕）。
    per_item：每条启用的条目按自己的周期独立触发。
    poll() 返回本次到期、需要发送的条目在原列表中的索引。
    """

    def __init__(self, items, mode: str, now_fn=time.monotonic):
        if mode not in MODES:
            raise ValueError(f"未知调度模式：{mode!r}")
        self._items = list(items)
        self._mode = mode
        self._now = now_fn
        self._order = [i for i, it in enumerate(self._items) if it.enabled]
        self._pos = 0
        start = self._now()
        self._next_time = start
        self._next_times = [start for _ in self._order]

    @property
    def order(self):
        """参与调度的条目索引。"""
        return list(self._order)

    def poll(self):
        """返回当前到期条目的索引列表（无则为空表）。"""
        due = []
        if not self._order:
            return due
        now = self._now()
        if self._mode == MODE_SEQUENTIAL:
            if now >= self._next_time:
                idx = self._order[self._pos]
                due.append(idx)
                self._pos = (self._pos + 1) % len(self._order)
                interval = max(self._items[idx].interval_ms, 1) / 1000.0
                self._next_time = now + interval
            return due
        for k, idx in enumerate(self._order):
            if now >= self._next_times[k]:
                due.append(idx)
                interval = max(self._items[idx].interval_ms, 1) / 1000.0
                self._next_times[k] = now + interval
        return due
