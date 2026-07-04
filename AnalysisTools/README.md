# ADS1299 Data Analysis Tools

These scripts are copied from the EEG working folder and adjusted for this GUI package.

## Folders

- Raw GUI recordings: `D:\OpenBCI_GUI_ADS1299\UserData\Recordings`
- Filtered outputs: `D:\OpenBCI_GUI_ADS1299\AnalysisTools\filtered_data`
- Analysis-ready outputs: `D:\OpenBCI_GUI_ADS1299\AnalysisTools\analysis_ready`

Run commands from this folder in PowerShell:

```powershell
Set-Location D:\OpenBCI_GUI_ADS1299\AnalysisTools
```

## 1. Filter Latest OpenBCI Raw Recording

```powershell
python filter_openbci_raw.py
```

This finds the latest `OpenBCI-RAW-*.txt` under `UserData\Recordings`, applies the default 50 Hz notch and 0.5-40 Hz bandpass filters, then writes CSV output to `filtered_data`.

## 2. Prepare Paradigm Analysis Tables

```powershell
python prepare_eeg_paradigm_format.py
```

This converts the latest filtered CSV into analysis-ready continuous EEG, channel, event, and metadata files.

## 3. Analyze Stress/Anxiety Paradigm

```powershell
python analyze_stress_paradigm.py
```

Use this after preparing EEG data and exporting matching paradigm event files from the anxiety induction program.

## Notes

This folder includes `sitecustomize.py`, which adds `D:\Lib\site-packages` to Python's search path on this workstation. The scripts use Python packages such as `numpy`, `pandas`, `scipy`, and `matplotlib`.

If a package is still missing, install it with:

```powershell
python -m pip install numpy pandas scipy matplotlib
```

The older BrainFlow bridge script is kept separately in:

```text
D:\OpenBCI_GUI_ADS1299\BridgeTools
```
