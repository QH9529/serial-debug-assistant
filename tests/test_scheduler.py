from serial_assistant.core.scheduler import (
    MODE_PER_ITEM,
    MODE_SEQUENTIAL,
    LoopScheduler,
    MessageItem,
)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def make_items(*intervals, enabled=None):
    enabled = enabled or [True] * len(intervals)
    return [
        MessageItem(content=f"m{i}", interval_ms=iv, enabled=en)
        for i, (iv, en) in enumerate(zip(intervals, enabled))
    ]


def test_sequential_order():
    clock = FakeClock()
    sched = LoopScheduler(make_items(100, 200, 300), MODE_SEQUENTIAL, now_fn=clock)
    assert sched.poll() == [0]
    clock.advance(0.05)
    assert sched.poll() == []
    clock.advance(0.05)
    assert sched.poll() == [1]
    clock.advance(0.2)
    assert sched.poll() == [2]
    clock.advance(0.3)
    assert sched.poll() == [0]


def test_sequential_skips_disabled():
    clock = FakeClock()
    sched = LoopScheduler(make_items(100, 100, 100, enabled=[True, False, True]), MODE_SEQUENTIAL, now_fn=clock)
    assert sched.order == [0, 2]
    assert sched.poll() == [0]
    clock.advance(0.1)
    assert sched.poll() == [2]
    clock.advance(0.1)
    assert sched.poll() == [0]


def test_per_item_independent_cycles():
    clock = FakeClock()
    sched = LoopScheduler(make_items(100, 200, 300), MODE_PER_ITEM, now_fn=clock)
    assert sched.poll() == [0, 1, 2]
    clock.advance(0.05)
    assert sched.poll() == []
    clock.advance(0.05)  # t=0.1
    assert sched.poll() == [0]
    clock.advance(0.1)  # t=0.2
    assert sched.poll() == [0, 1]
    clock.advance(0.1)  # t=0.3
    assert sched.poll() == [0, 2]
    clock.advance(0.1)  # t=0.4
    assert sched.poll() == [0, 1]


def test_all_disabled_never_fires():
    clock = FakeClock()
    sched = LoopScheduler(make_items(100, 200, enabled=[False, False]), MODE_SEQUENTIAL, now_fn=clock)
    clock.advance(10)
    assert sched.poll() == []
    assert sched.order == []


def test_interval_lower_bound():
    assert MessageItem(interval_ms=0).interval_ms == 1
    assert MessageItem.from_dict({"interval_ms": -5}).interval_ms == 1


def test_unknown_mode_rejected():
    import pytest

    with pytest.raises(ValueError):
        LoopScheduler([], "unknown")
