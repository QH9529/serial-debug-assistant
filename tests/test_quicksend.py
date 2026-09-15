from serial_assistant.core.quicksend import (
    MAX_SLOTS,
    QuickSlot,
    dump_history,
    dump_slots,
    history_from_raw,
    load_slots,
    push_history,
)


def test_slot_round_trip():
    slots = [
        QuickSlot(label="读寄存器", content="01 03 00 00 00 0A", is_hex=True, checksum="crc16", hotkey="F1"),
        QuickSlot(label="", content=r"AT+GMR\r\n", is_hex=False, checksum="none", hotkey="Ctrl+1"),
    ]
    assert load_slots(dump_slots(slots)) == slots


def test_slot_tolerant_load():
    assert load_slots(None) == []
    assert load_slots("{not json") == []
    assert load_slots('{"a": 1}') == []
    loaded = load_slots('[{"content": "A", "checksum": "bogus", "is_hex": "yes"}]')
    assert loaded[0].content == "A"
    assert loaded[0].checksum == "none"
    assert loaded[0].is_hex is True


def test_slot_limit():
    raw = dump_slots([QuickSlot(content=str(i)) for i in range(MAX_SLOTS + 10)])
    assert len(load_slots(raw)) == MAX_SLOTS


def test_display_label():
    assert QuickSlot(label="短").display_label() == "短"
    assert QuickSlot(content="0123456789abcdef").display_label(8).endswith("…")
    assert QuickSlot().display_label() == "(空)"


def test_history_push_dedupe_and_limit():
    history = []
    for i in range(25):
        history = push_history(history, f"cmd{i}", False)
    assert len(history) == 20
    assert history[0]["text"] == "cmd24"

    history = push_history(history, "cmd24", False)
    assert history[0]["text"] == "cmd24"
    assert sum(1 for entry in history if entry["text"] == "cmd24") == 1

    assert push_history(history, "   ", False) == history


def test_history_raw_tolerant():
    assert history_from_raw(None) == []
    assert history_from_raw("[bad") == []
    entries = history_from_raw(dump_history([{"text": "A", "is_hex": True}]))
    assert entries == [{"text": "A", "is_hex": True}]
