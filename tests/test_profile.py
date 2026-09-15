import pytest

from serial_assistant.core.profile import ProfileError, load_profile, save_profile
from serial_assistant.core.scheduler import MODE_PER_ITEM, MODE_SEQUENTIAL, MessageItem


def sample_items():
    return [
        MessageItem(
            content="01 03 00 00 00 0A",
            is_hex=True,
            interval_ms=500,
            note="读寄存器",
            enabled=True,
            checksum="crc16",
        ),
        MessageItem(
            content=r"AT+RST\r\n",
            is_hex=False,
            interval_ms=1000,
            note="复位",
            enabled=False,
            checksum="none",
        ),
        MessageItem(
            content=r"PING\n",
            is_hex=False,
            interval_ms=250,
            note="心跳 中文备注",
            enabled=True,
            checksum="sum8",
        ),
    ]


def test_round_trip_per_item(tmp_path):
    path = tmp_path / "scheme.json"
    items = sample_items()
    save_profile(path, MODE_PER_ITEM, items)
    mode, loaded = load_profile(path)
    assert mode == MODE_PER_ITEM
    assert loaded == items


def test_round_trip_sequential_keeps_chinese(tmp_path):
    path = tmp_path / "scheme.json"
    items = sample_items()
    save_profile(path, MODE_SEQUENTIAL, items)
    mode, loaded = load_profile(path)
    assert mode == MODE_SEQUENTIAL
    assert loaded == items
    assert "中文备注" in path.read_text(encoding="utf-8")


def test_load_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile(path)


def test_load_missing_file(tmp_path):
    with pytest.raises(ProfileError):
        load_profile(tmp_path / "nope.json")


def test_load_bad_mode(tmp_path):
    path = tmp_path / "bad_mode.json"
    path.write_text('{"mode": "unknown", "items": []}', encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile(path)


def test_load_tolerates_bad_item_fields(tmp_path):
    path = tmp_path / "tolerant.json"
    path.write_text(
        '{"mode": "sequential", "items": [{"content": "A", "interval_ms": "x", '
        '"checksum": "bogus", "enabled": "yes"}]}',
        encoding="utf-8",
    )
    mode, items = load_profile(path)
    assert mode == MODE_SEQUENTIAL
    assert items[0].interval_ms == 1000
    assert items[0].checksum == "none"
    assert items[0].enabled is True
