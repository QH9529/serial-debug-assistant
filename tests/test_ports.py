from serial_assistant.core.ports import port_sort_key, sort_ports


def test_com_ports_sorted_numerically():
    names = ["COM10", "COM2", "COM1", "COM21", "COM3"]
    assert sort_ports(names) == ["COM1", "COM2", "COM3", "COM10", "COM21"]


def test_unix_style_ports_sorted_by_number():
    names = ["/dev/ttyUSB10", "/dev/ttyUSB2", "/dev/ttyACM1"]
    assert sort_ports(names) == ["/dev/ttyACM1", "/dev/ttyUSB2", "/dev/ttyUSB10"]


def test_windows_raw_device_prefix():
    names = ["\\\\.\\COM11", "\\\\.\\COM2"]
    assert sort_ports(names) == ["\\\\.\\COM2", "\\\\.\\COM11"]


def test_names_without_number_go_last():
    names = ["VIRTUAL", "COM4"]
    assert sort_ports(names) == ["COM4", "VIRTUAL"]


def test_port_sort_key_case_insensitive():
    assert port_sort_key("COM9") < port_sort_key("COM10")
    assert port_sort_key("com9")[:3] == port_sort_key("COM9")[:3]
