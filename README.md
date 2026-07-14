# OpenBCI GUI ADS1299

这是基于 OpenBCI GUI v5.2.2 修改的 ADS1299 16 通道采集 GUI。当前版本增加了 `ADS1299 16ch (WiFi TCP)` 数据源，GUI 可以在电脑上监听 TCP 端口，接收 ADS1299 采集板通过 WiFi 发来的原始数据帧，并使用 OpenBCI GUI 的时域、频谱、脑电地形图、网络转发和录制功能。

## 目录说明

- `App/`: Windows 打包版 GUI，包含 `OpenBCI_GUI.exe` 和运行所需的 Java、库文件、资源文件。
- `Source/`: OpenBCI GUI v5.2.2 源码和 ADS1299 TCP 数据源修改。
- `ProcessingSketchbook/`: Processing 运行源码时需要的第三方库。
- `UserData/Settings/`: GUI 默认设置，包含 ADS1299 16 通道布局。
- `UserData/Sample_Data/`: OpenBCI GUI 示例数据。
- `BridgeTools/`: ADS129x 到 BrainFlow Streaming Board 的桥接脚本。
- `AnalysisTools/`: EEG 数据过滤和离线分析脚本。

没有上传 `UserData/Recordings/`、`UserData/Console_Data/`、`downloads/`、`build_check/`、`Processing-3.5.4/` 等目录，因为它们分别是个人录制数据、运行日志、下载缓存、编译输出和本机安装包。

## 运行条件

### 直接运行打包版

- Windows 10/11 64 位电脑。
- 支持 OpenGL 的显卡驱动。
- 建议至少 2 GB 内存、1 GB 可用磁盘空间。
- 如果连接真实 ADS1299 采集板，电脑和采集板需要在同一局域网内。
- Windows 防火墙需要允许 `OpenBCI_GUI.exe` 监听 TCP 端口，默认端口是 `1234`。

### 从源码运行

- Processing 3.5.4 或 3.5.3。
- 不建议使用 Processing 4。
- Java 8 环境通常随 Processing 3.5.x 一起提供。
- 运行源码时需要 `ProcessingSketchbook/libraries` 中的库。

### Python 工具

- Python 3.9 或更高版本。
- 常用依赖：

```powershell
python -m pip install numpy pandas scipy matplotlib
```

## 快速运行

1. 在 GitHub 页面点击 `Code` -> `Download ZIP`，解压项目。
2. 进入解压后的项目目录。
3. 双击运行：

```text
App\OpenBCI_GUI.exe
```

4. 在 GUI 的 `DATA SOURCE` 中选择：

```text
ADS1299 16ch (WiFi TCP)
```

5. 设置 `LISTEN PORT`，默认 `1234`。
6. 选择和采集板一致的采样率：`250Hz`、`500Hz`、`1000Hz` 或 `2000Hz`。
7. 点击 `START SESSION`，然后启动数据流。

GUI 会监听：

```text
0.0.0.0:<LISTEN PORT>
```

真实采集板需要主动连接到这台电脑的 IPv4 地址和 GUI 中设置的端口。

## ADS1299 采集板 WiFi 配置

进入采集板串口配置模式后，按行发送类似命令：

```text
AT+NAME=你的2.4G_WiFi名称
AT+PSWD=你的WiFi密码
AT+IP=电脑IPv4地址
AT+PORT=1234
AT+SETOVER
```

注意：

- `AT+PORT` 必须和 GUI 的 `LISTEN PORT` 一致。
- `AT+IP` 填电脑在当前局域网中的 IPv4 地址，不要填公网 IP。
- 采集板输出的采样率要和 GUI 里选择的采样率一致，否则 GUI 会提示采样率不匹配。
- 如果连接不上，优先检查 Windows 防火墙、端口是否被占用、电脑和采集板是否在同一网络。

## 从 Processing 运行源码

1. 安装 Processing 3.5.4 或 3.5.3。
2. 打开 Processing，进入 `File` -> `Preferences`。
3. 将 Sketchbook location 指向本项目的：

```text
ProcessingSketchbook
```

4. 用 Processing 打开：

```text
Source\OpenBCI_GUI\OpenBCI_GUI.pde
```

5. 点击运行按钮。
6. 按照上面的 ADS1299 快速运行步骤选择数据源、端口和采样率。

如果 Processing 提示缺少库，把 `ProcessingSketchbook\libraries` 下的库复制到你的默认 Processing sketchbook 的 `libraries` 目录，再重启 Processing。

## 本地模拟数据测试

如果没有真实 ADS1299 硬件，可以先用模拟发送器检查 GUI TCP 接收是否正常。

1. 先启动 GUI，并选择 `ADS1299 16ch (WiFi TCP)`，端口保持 `1234`。
2. 在另一个 PowerShell 窗口运行：

```powershell
Set-Location Source
python tools\ads129x_fake_sender.py --host 127.0.0.1 --port 1234 --rate 250 --duration 30
```

常用故障注入测试：

```powershell
python tools\ads129x_fake_sender.py --host 127.0.0.1 --port 1234 --rate 250 --sequence-gap-after 20
python tools\ads129x_fake_sender.py --host 127.0.0.1 --port 1234 --rate 250 --bad-checksum-every 10
```

## 数据保存位置

GUI 默认把数据和配置写到：

```text
%LOCALAPPDATA%\OpenBCI_GUI_ADS1299\UserData
```

如果旧版的 `D:\OpenBCI_GUI_ADS1299\UserData` 已经存在，程序会继续使用该目录，避免已有设置和录制数据迁移后丢失。

如果需要把录制和配置保存到其他磁盘，请设置用户环境变量 `OPENBCI_GUI_DATA_DIR`。例如保存到 O 盘：

```powershell
[Environment]::SetEnvironmentVariable(
    "OPENBCI_GUI_DATA_DIR",
    "O:\OpenBCI_GUI_ADS1299\UserData",
    "User"
)
```

设置后需要退出并重新启动 GUI。程序启动时会自动创建 `Recordings`、`Settings`、`Console_Data` 和 `Sample_Data` 子目录，不再依赖固定的 `D:` 盘符。

仓库不会保存个人录制数据。需要共享实验数据时，请单独整理脱敏后的数据文件，并避免把几十 GB 的原始录制直接提交进 Git。

## 离线分析工具

分析脚本位于：

```text
AnalysisTools
```

常用命令：

```powershell
Set-Location AnalysisTools
python filter_openbci_raw.py
python prepare_eeg_paradigm_format.py
python analyze_stress_paradigm.py
```

这些脚本默认读取 `UserData\Recordings` 下最新的 OpenBCI 原始录制文件，并输出过滤后或分析就绪的数据。详细说明见 `AnalysisTools\README.md`。

## 常见问题

- GUI 没有收到数据：检查防火墙是否允许入站 TCP，确认采集板连接的是电脑 IPv4 和同一个端口。
- 提示端口被占用：换一个 `LISTEN PORT`，同时修改采集板 `AT+PORT`。
- 提示采样率不匹配：停止 session，选择和采集板输出一致的采样率后重启。
- Processing 编译失败：确认使用 Processing 3.5.4 或 3.5.3，并确认库目录已配置。
- 录制文件没有出现在预期位置：检查 `DirectoryManager.pde` 中的数据目录配置。

## 来源和许可

本项目基于 OpenBCI GUI v5.2.2 修改。原项目使用 MIT License，许可证见 `Source\LICENSE`。
