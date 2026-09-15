# 串口调试助手 Serial Debug Assistant

跨平台串口调试助手，核心特色是**多条数据循环发送**。基于 Python 3.12+ + PySide6 + pyserial。

## 功能（V1）

- 串口管理：端口枚举与刷新、波特率（含自定义）、数据位 / 停止位 / 校验位 / 流控、断线检测与自动重连开关、记住上次端口
- 收发：文本 / HEX 双模式、转义符（`\n` `\r` `\t` `\0` `\xhh`）、追加 `\r\n`、时间戳开关、RX / TX 字节统计、暂停滚动、清空、接收日志自动保存到 `logs/`
- **多条循环发送**：
  - 表格管理多条指令：启用开关、内容、文本 / HEX 模式、间隔 (ms)、校验、备注，支持添加 / 删除 / 上移 / 下移 / 清空
  - 两种调度：**顺序轮询**（一条发完、等待它自己的间隔，再发下一条，循环往复）与**单条周期**（每条按各自周期独立触发）
  - 一键启停；循环过程中状态栏提示当前发送的条目
- 校验自动追加：CRC16-Modbus（低字节在前）、SUM8 累加和、LRC
- 方案保存 / 加载：JSON 文件（UTF-8），可读可手改

## 运行

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m serial_assistant
```

也可以直接 `python run.py`。

无显示器环境自检：

```bash
python -m serial_assistant --selftest
```

## 测试

```bash
pip install -r requirements-dev.txt
python -m pytest
```

覆盖内容：转义解析、HEX / 文本转换、CRC16-Modbus 标准校验值、SUM8、LRC、两种循环调度逻辑、方案 JSON 往返、offscreen GUI 冒烟。

## 打包

```bash
pip install pyinstaller
pyinstaller --noconfirm --windowed --name SerialDebugAssistant run.py
```

## 发送内容书写规则

- 文本模式：默认解析转义符 `\n`（换行）、`\r`、`\t`、`\0`、`\xhh`（单字节）；取消勾选「使用转义符」后按原样发送（UTF-8 编码）
- HEX 模式：如 `01 03 00 00 00 0A`，空格 / 逗号 / 分号 / `0x` 前缀均可
- 校验：按条目选择，自动追加到该条数据的末尾

## 项目结构

```
serial_assistant/
├── __main__.py          # 入口（python -m serial_assistant）
├── core/                # 纯逻辑，无 Qt 依赖，可独立单测
│   ├── codec.py         # 转义解析 / HEX 与文本转换
│   ├── checksum.py      # CRC16-Modbus / SUM8 / LRC
│   ├── scheduler.py     # 循环发送调度（顺序轮询 / 单条周期）
│   └── profile.py       # 方案 JSON 存取
├── serial_worker.py     # 串口 IO 工作线程（QThread + 信号）
└── ui/
    ├── send_table.py    # 循环发送表格
    └── main_window.py   # 主窗口
tests/                   # pytest 单元测试 + GUI 冒烟
```

## 架构说明

串口读写与循环发送调度全部在独立工作线程（`SerialWorker`）中完成，通过 Qt 信号与 UI 通信，界面不会因串口阻塞而卡顿；`core/` 为纯 Python 逻辑，便于测试与复用。

## License

MIT
