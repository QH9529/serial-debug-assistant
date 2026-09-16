# 串口调试助手 Serial Debug Assistant

当前版本：**V1.0.0**（界面左上角显示；应用图标见 `serial_assistant/assets/app.ico`）

跨平台串口调试助手，核心特色是**多条数据循环发送**。基于 Python 3.12+ + PySide6 + pyserial。

## 功能（V1）

- **多会话标签页**：一个窗口内可同时打开多个串口，每个会话拥有**独立的参数、收发、计数、日志、快捷指令与发送历史**；会话可新建 / 关闭 / 拖动排序 / **自定义名称**（标签页显示「名称（COMx）」，保留串口名）
  - 同一个 COM 不能被两个会话同时打开（占用校验 + 提示）
  - 串口参数在打开时生效：改动后界面提示「需重开端口生效」
  - 全局共享的只有主题与窗口尺寸
- **广播下发**：发送目标可选「当前会话 / 全部会话 / 勾选会话…」，一条指令同时下发给多个模块（单次、快捷、循环发送都生效）
- **串口间转发**：把某个会话收到的数据自动转发到另一个会话的串口（做链路验证 / 协议中继）
- 串口管理：端口枚举与刷新（按数字自然升序）、波特率（含自定义）、数据位 / 停止位 / 校验位 / 流控、断线检测与自动重连开关、记住上次端口
- **RTS / DTR 手动控制**：运行时切换控制线电平，可直接复位 MCU / 切换模块模式
- 收发：文本 / HEX 双模式、转义符（`\n` `\r` `\t` `\0` `\xhh`）、换行符可选（不追加 / CR / LF / CRLF）、时间戳（毫秒）、RX / TX 字节统计、暂停滚动、清空、自动日志（目录可选，`serial_YYYYMMDD.txt`）
- 接收显示：**文本 / HEX / 对照三种模式**（对照模式一行内同时给出十六进制与文本）、**编码可选**（UTF-8 / GBK / UTF-16 / ASCII / Latin-1）、**自动换行**（按接收空闲时间断行）、**保存数据**（另存为文本）、**窗口置顶**
- 发送辅助：**快捷发送面板**（一键发送常用指令，可绑定自定义快捷键）、**发送历史**（点选重发）、**发送文件**（按块分块下发，状态栏显示进度）
- **多条循环发送**：
  - 表格管理多条指令：启用开关、内容（输入框）、间隔 (ms)、备注，每行末尾带**带框删除按钮**；模式与校验全局共用（同单次发送），表内不再重复配置
  - 两种调度：**顺序轮询**（一条发完、等待它自己的间隔，再发下一条，循环往复）与**单条周期**（每条按各自周期独立触发）
  - **SSCOM 式多字符串**：勾选「统一周期」后用同一个周期循环所有勾选项；「发送一次」把勾选项按顺序各发一遍（不启动循环）
  - 一键启停；循环过程中状态栏提示当前发送的条目
- 校验自动追加：CRC16-Modbus（低字节在前）、SUM8 累加和、LRC（**单次发送 / 快捷发送 / 循环发送共用同一份校验设置**）
- 接收时间戳精确到毫秒（`HH:MM:SS.mmm`）
- 方案保存 / 加载：JSON 文件（UTF-8），可读可手改

## 界面

- 默认深色主题（铜橙单一强调色），可在顶部「浅色主题」按钮一键切换，选择会记住
- 日志区等宽字体，按 RX / TX / SYS 分类着色，便于快速区分收发
- 生成预览图：`python tools/preview.py preview`（无显示器环境也可用，输出 `preview/ui-dark.png`、`preview/ui-light.png`）

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

## 打包（单文件免依赖 exe）

```bash
pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed ^
  --name SerialDebugAssistant ^
  --icon serial_assistant/assets/app.ico ^
  --add-data "serial_assistant/assets;serial_assistant/assets" ^
  run.py
```

产物：`dist/SerialDebugAssistant.exe`

- 约 46 MB，**单文件、免安装、免依赖**（Python 与 Qt 已全部内置），已嵌入应用图标
- 首次启动会把内容解压到临时目录，约 1–3 秒；之后启动稍快
- 单文件打包程序有时被杀软误报，必要时加白名单
- 仓库已自带 `SerialDebugAssistant.spec`，后续可直接 `pyinstaller SerialDebugAssistant.spec` 重建

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
