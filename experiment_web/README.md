# MIST 网页与 OpenBCI GUI 联动

## 正式实验启动顺序

1. 运行 `App\OpenBCI_GUI.exe`。
2. 在 GUI 中选择 `ADS1299 16ch (WiFi TCP)`，确认监听端口和采样率后点击 `START SESSION`。
3. 启动 ADS1299，使其连接到 GUI；GUI 控制台应显示硬件 TCP 客户端已连接。
4. 运行 `experiment_web\run_experiment_windows.bat`，浏览器打开后填写被试信息并按 Enter。
5. 网页会检查 GUI、Session、ADS1299 数据源和硬件连接。全部通过后才进入实验。

每个阶段在被试按空格开始时自动启动 GUI stream。阶段结束、跳过或中止时，网页会等待 GUI 停止 stream 并关闭文件，然后才进入下一页。

## 数据位置和命名

- 行为 CSV：`%USERPROFILE%\Desktop\MIST_data`
- EEG：默认位于 `%LOCALAPPDATA%\OpenBCI_GUI_ADS1299\UserData\Recordings\OpenBCISession_<实验会话>`；如果旧目录 `D:\OpenBCI_GUI_ADS1299\UserData` 已存在，GUI 会继续使用旧目录

EEG 文件名最后一段固定为阶段名，例如：

```text
MIST_SUB01_ses-01_20260714_120000_eyes_open.txt
MIST_SUB01_ses-01_20260714_120000_eyes_closed.txt
MIST_SUB01_ses-01_20260714_120000_practice.txt
MIST_SUB01_ses-01_20260714_120000_control.txt
MIST_SUB01_ses-01_20260714_120000_stress.txt
MIST_SUB01_ses-01_20260714_120000_recovery.txt
```

可用 `OPENBCI_GUI_DATA_DIR` 环境变量覆盖 GUI 的 `UserData` 保存位置。

## 控制接口

GUI 只在本机 `127.0.0.1:1236` 监听实验控制命令。网页后端会动态重连，支持：

- `STATUS`：查询 GUI Session、ADS1299 硬件、stream 和文件状态；
- `RECORD:<session>|<file-name>`：打开一个阶段文件并开始 stream；
- `STOP`：停止 stream，关闭文件后再确认；
- `PING`：控制服务存活检测。

## 验证

```powershell
experiment_web\venv\Scripts\python.exe -m unittest discover -s experiment_web\tests -v
node --check experiment_web\static\experiment.js
```
