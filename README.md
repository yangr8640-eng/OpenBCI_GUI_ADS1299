# OpenBCI GUI ADS1299 + MIST EEG 实验集成

本分支基于 OpenBCI GUI v5.2.2 ADS1299 修改版，集成了 MIST（Montreal Imaging Stress Task）脑电实验的自动录制控制。GUI 与实验通过 TCP 通信，实验在每个阶段开始时自动触发 GUI 开始录制，阶段结束时自动停止并保存，文件按 `[被试编号]-[阶段名称]-RAW.txt` 格式命名。

## 架构概览

```
MIST 实验 (Python/PsychoPy)           OpenBCI GUI (Processing/Java)
┌────────────────────────┐           ┌──────────────────────────────┐
│ mist.py                │  TCP      │ ExperimentControlServer.pde  │
│  ┌──────────────────┐  │  :1236   │ (后台守护线程)                 │
│  │ GUIController    │──┼─────────▶│                              │
│  │ .start_stage()   │  │ RECORD:  │ → stopRunning()              │
│  │ .stop()          │  │ SUB01-   │ → setRecordingName()         │
│  └──────────────────┘  │ eyes_open│ → startRunning()             │
│                        │ -RAW     │                              │
│                        │ STOP     │ → stopRunning()              │
└────────────────────────┘           └──────────────────────────────┘
```

- **GUI 在录制时**：实验窗口仍响应用户操作，被试答题不受影响
- **GUI 未运行时**：实验仍可正常运行，GUIController 连接失败后静默跳过（优雅降级）

## 目录结构

```
OpenBCI_GUI_ADS1299/
├── Source/OpenBCI_GUI/          # Processing GUI 源代码 (.pde)
│   ├── OpenBCI_GUI.pde          # 主程序（含实验控制入口）
│   ├── ExperimentControlServer.pde  # [新增] TCP 命令服务器
│   ├── DataLogger.pde           # [修改] 支持自定义录制文件名
│   ├── DataWriterODF.pde        # [修改] 三参数构造函数
│   ├── DataWriterAuxODF.pde     # [修改] 同上
│   ├── DirectoryManager.pde     # [修改] 跨平台数据路径
│   └── ...                      # 其余 GUI 源文件
├── experiment/                  # [新增] MIST 实验 Python 代码
│   ├── mist.py                  # 实验主程序 (PsychoPy)
│   ├── gui_controller.py        # GUI TCP 客户端
│   ├── requirements.txt         # Python 依赖
│   ├── run_experiment_windows.bat  # Windows 启动脚本
│   └── __init__.py
├── ProcessingSketchbook/        # Processing 第三方库
├── BridgeTools/                 # BrainFlow 桥接工具
├── AnalysisTools/               # 离线数据分析脚本
├── UserData/                    # 运行数据（不提交到 Git）
└── README.md
```

## 实验流程与阶段

| 顺序 | 阶段 | 时长 | 录制文件名 | 说明 |
|------|------|------|-----------|------|
| 0 | 被试信息输入 | — | 不录制 | 输入编号，按 Enter 进入实验 |
| 1 | 睁眼静息 | 3 分钟 | `SUB01-eyes_open-RAW.txt` | 注视屏幕中央十字 |
| 2 | 闭眼静息 | 3 分钟 | `SUB01-eyes_closed-RAW.txt` | 闭眼放松 |
| 3 | 练习阶段 | 3 分钟 | `SUB01-practice-RAW.txt` | 熟悉算术填空任务 |
| 4 | 对照阶段 | 3 分钟 | `SUB01-control-RAW.txt` | 普通难度算术 |
| 5 | 压力阶段 | 3 分钟 | `SUB01-stress-RAW.txt` | 限时 + 社会评价反馈 |
| 6 | 恢复阶段 | 3 分钟 | `SUB01-recovery-RAW.txt` | 静息恢复 |

每个阶段结束后进行 VAS（视觉模拟量表）主观评分，VAS 期间不录制脑电数据。按 `S` 键可跳过当前阶段/VAS（用于预实验调试）。

## 录制文件命名

所有文件保存在 GUI 的 `UserData/Recordings/` 下，格式如下：

```
UserData/Recordings/
├── OpenBCISession_SUB01-eyes_open-RAW/
│   └── SUB01-eyes_open-RAW.txt
├── OpenBCISession_SUB01-eyes_closed-RAW/
│   └── SUB01-eyes_closed-RAW.txt
├── OpenBCISession_SUB01-practice-RAW/
│   └── SUB01-practice-RAW.txt
├── OpenBCISession_SUB01-control-RAW/
│   └── SUB01-control-RAW.txt
├── OpenBCISession_SUB01-stress-RAW/
│   └── SUB01-stress-RAW.txt
└── OpenBCISession_SUB01-recovery-RAW/
    └── SUB01-recovery-RAW.txt
```

文件格式为 OpenBCI Data Format (ODF)，即带 `%` 前缀元数据头的 CSV 文本文件。

## 运行环境

### GUI 端

| 方式 | 需要 | 适用场景 |
|------|------|----------|
| 从源码运行 | Processing 3.5.4（不支持 Processing 4）+ 第三方库 | 开发/调试 |
| 导出独立应用 | 无需 Processing，双击 `.exe` 即可 | 被试机/正式实验 |

### 实验端

- Python 3.10 或更高版本
- 依赖见 `experiment/requirements.txt`

## 快速开始（完整流程）

### 第一步：启动 GUI

**方式 A — Processing 源码运行：**

1. 安装 [Processing 3.5.4](https://processing.org/download)
2. 打开 Processing，`File → Preferences`，将 Sketchbook location 指向本项目的 `ProcessingSketchbook/`
3. 用 Processing 打开 `Source/OpenBCI_GUI/OpenBCI_GUI.pde`
4. 点击 ▶ 运行

**方式 B — 导出为独立应用：**

在 Processing 中点击 `File → Export Application`，勾选当前平台，导出后在生成目录中双击运行。

### 第二步：配置 GUI

1. 在 `DATA SOURCE` 中选择 `ADS1299 16ch (WiFi TCP)`
2. 设置监听端口（默认 `1234`）
3. 选择与采集板一致的采样率
4. 点击 `START SESSION`
5. 确认 ADS1299 采集板已连接并传输正常
6. **此时 GUI 控制服务器已在后台启动（端口 1236）**

### 第三步：安装实验依赖

```bash
# macOS / Linux
python3 -m venv venv
source venv/bin/activate
pip install -r experiment/requirements.txt

# Windows
python -m venv venv
venv\Scripts\activate
pip install -r experiment/requirements.txt
```

### 第四步：运行实验

```bash
# macOS / Linux
venv/bin/python -m experiment.mist

# Windows（也可直接双击 run_experiment_windows.bat）
venv\Scripts\python -m experiment.mist
```

### 第五步：输入被试信息

1. 在实验窗口输入被试编号（如 `SUB01`）
2. 按 `Enter` 确认
3. 如果 GUI 连接正常，终端会输出 `GUI integration active`
4. 后续每个阶段自动开始/停止录制

## GUI 控制协议

用于调试或自定义控制。GUI 在端口 `1236` 上监听 TCP 命令（换行符分隔）：

| 命令 | 作用 | 返回 |
|------|------|------|
| `RECORD:<文件名>` | 停止当前录制，设置文件名，开始新录制 | `OK RECORD:<文件名>` |
| `STOP` | 停止当前录制 | `OK STOPPED` |
| `PING` | 连接测试 | `PONG` |

### 手动测试

```bash
# 测试连接
echo "PING" | nc 127.0.0.1 1236
# 应返回: PONG

# 触发录制
echo "RECORD:SUB01-eyes_open-RAW" | nc 127.0.0.1 1236
# 应返回: OK RECORD:SUB01-eyes_open-RAW

# 停止录制
echo "STOP" | nc 127.0.0.1 1236
# 应返回: OK STOPPED
```

## 无硬件测试

### 模拟 ADS1299 数据源

```bash
cd Source
python tools/ads129x_fake_sender.py --host 127.0.0.1 --port 1234 --rate 250 --duration 30
```

### 不启动 GUI 运行实验

实验在 GUI 不可用时会自动降级，正常执行所有阶段，仅跳过录制控制。终端会显示：

```
[GUIController] Cannot connect to GUI at 127.0.0.1:1236: Connection refused
WARNING: Could not connect to OpenBCI GUI — experiment will run without automatic recording
```

## ADS1299 采集板 WiFi 配置

进入采集板串口配置模式后，按行发送：

```
AT+NAME=你的2.4G_WiFi名称
AT+PSWD=你的WiFi密码
AT+IP=电脑IPv4地址
AT+PORT=1234
AT+SETOVER
```

- `AT+PORT` 必须与 GUI 的 `LISTEN PORT` 一致
- `AT+IP` 填电脑在局域网中的 IPv4 地址
- 采集板采样率需与 GUI 设置一致

## 离线分析

分析脚本位于 `AnalysisTools/`：

```bash
cd AnalysisTools
python filter_openbci_raw.py
python prepare_eeg_paradigm_format.py
python analyze_stress_paradigm.py
```

## 常见问题

**GUI 端：**
- **Processing 编译失败**：确认使用 Processing 3.5.4（非 4.x），确认库目录已正确配置
- **端口被占用**：更换 `LISTEN PORT`，同步修改采集板配置
- **采样率不匹配**：停止 Session，切换采样率后重新开始
- **录制文件路径不对**：检查 `DirectoryManager.pde` 中的数据目录配置
- **控制服务器启动失败**：检查端口 1236 是否被占用

**实验端：**
- **GUI 连接失败**：确认 GUI 已启动并进入 SESSION 状态，确认 `GUI_CONTROL_PORT` 配置正确
- **PsychoPy 窗口黑屏/闪退**：检查显卡驱动，尝试更新 PsychoPy
- **pylsl 导入失败**：不影响核心功能，仅 LSL 标记不可用
- **被试输入框不显示中文**：Windows 需确保系统语言支持已安装

**网络：**
- **采集板无数据**：检查防火墙是否允许入站 TCP 连接，确认采集板 IP 地址指向正确
- **控制端口不通**：确认防火墙未阻止端口 1236

## 来源与许可

- OpenBCI GUI v5.2.2：MIT License，详见 `Source/LICENSE`
- MIST 实验代码：基于 PsychoPy 开发
- 本分支修改部分：MIT License
