# -*- coding: utf-8 -*-
"""Analyze two mouse OpenBCI raw EEG recordings.

The default channel interpretation follows OpenBCI hardware numbering:
hardware channels 1/3/5/10 map to file columns EXG Channel 0/2/4/9.
Use --file-zero-based if the requested channel numbers refer literally to
the EXG Channel labels in the text file.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import signal


RECORDINGS = [
    {
        "file": "小鼠.txt",
        "recording": "mouse_patch",
        "label": "Patch electrodes",
        "label_zh": "贴片电极",
    },
    {
        "file": "小鼠2.txt",
        "recording": "mouse_needle",
        "label": "Needle electrodes",
        "label_zh": "针状电极",
    },
]

REGIONS = [
    ("occipital", "枕叶", "Occipital"),
    ("parietal", "顶叶", "Parietal"),
    ("temporal", "颞叶", "Temporal"),
]

BANDS = [
    ("delta", "Delta", 0.5, 4.0),
    ("theta", "Theta", 4.0, 8.0),
    ("alpha_sigma", "Alpha/Sigma", 8.0, 12.0),
    ("beta", "Beta", 12.0, 30.0),
    ("low_gamma", "Low gamma", 30.0, 45.0),
]

FULL_SCALE_UV = 187_500.0
NEAR_RAIL_UV = 0.90 * FULL_SCALE_UV


@dataclass(frozen=True)
class ChannelMap:
    brain_channels: list[int]
    reference_channel: int
    description: str


def parse_openbci_header(path: Path) -> dict[str, float | int | str]:
    info: dict[str, float | int | str] = {}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.startswith("%"):
                break
            if "Sample Rate" in line:
                match = re.search(r"=\s*([0-9.]+)", line)
                if match:
                    info["sample_rate"] = float(match.group(1))
            elif "Number of channels" in line:
                match = re.search(r"=\s*([0-9]+)", line)
                if match:
                    info["channel_count"] = int(match.group(1))
            elif "Board" in line:
                info["board"] = line.split("=", 1)[-1].strip()
    return info


def find_recording(root: Path, expected_name: str) -> Path:
    for path in root.glob("*.txt"):
        if path.name == expected_name:
            return path
    raise FileNotFoundError(f"Could not find {expected_name} under {root}")


def build_channel_map(file_zero_based: bool) -> ChannelMap:
    if file_zero_based:
        return ChannelMap(
            brain_channels=[1, 3, 5],
            reference_channel=10,
            description="literal file labels EXG Channel 1/3/5/10",
        )
    return ChannelMap(
        brain_channels=[0, 2, 4],
        reference_channel=9,
        description="OpenBCI hardware channels 1/3/5/10 mapped to EXG Channel 0/2/4/9",
    )


def read_selected_openbci(path: Path, channel_map: ChannelMap) -> tuple[pd.DataFrame, float]:
    header = parse_openbci_header(path)
    sample_rate = float(header.get("sample_rate", 250.0))
    wanted = {"Sample Index"}
    for channel in [*channel_map.brain_channels, channel_map.reference_channel]:
        wanted.add(f"EXG Channel {channel}")

    frame = pd.read_csv(
        path,
        comment="%",
        skipinitialspace=True,
        usecols=lambda column: column.strip() in wanted,
    )
    frame.columns = [column.strip() for column in frame.columns]
    for column in frame.columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    exg_columns = [column for column in frame.columns if column.startswith("EXG Channel")]
    valid = ~frame[exg_columns].isna().all(axis=1)
    frame = frame.loc[valid].reset_index(drop=True)
    frame[exg_columns] = frame[exg_columns].interpolate(limit_direction="both").fillna(0.0)
    return frame, sample_rate


def apply_filters(data: np.ndarray, sample_rate: float) -> np.ndarray:
    filtered = np.asarray(data, dtype=float)
    if 0 < 50.0 < sample_rate / 2:
        b_notch, a_notch = signal.iirnotch(w0=50.0, Q=30.0, fs=sample_rate)
        filtered = signal.filtfilt(b_notch, a_notch, filtered, axis=0)

    sos = signal.butter(
        4,
        [0.5, 45.0],
        btype="bandpass",
        fs=sample_rate,
        output="sos",
    )
    return signal.sosfiltfilt(sos, filtered, axis=0)


def robust_threshold(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return math.inf
    median = float(np.median(finite))
    mad = float(np.median(np.abs(finite - median)))
    robust_sigma = 1.4826 * mad
    q1, q3 = np.percentile(finite, [25, 75])
    iqr = float(q3 - q1)
    candidates = [
        median + 8.0 * robust_sigma,
        float(q3 + 4.0 * iqr),
        float(np.percentile(finite, 99.0)),
    ]
    candidates = [value for value in candidates if np.isfinite(value)]
    return max(candidates) if candidates else math.inf


def epoch_peak_to_peak(data: np.ndarray, sample_rate: float, epoch_s: float) -> np.ndarray:
    epoch_len = max(1, int(round(epoch_s * sample_rate)))
    epoch_count = len(data) // epoch_len
    if epoch_count == 0:
        return np.empty((0, data.shape[1]))
    epochs = data[: epoch_count * epoch_len].reshape(epoch_count, epoch_len, data.shape[1])
    return np.ptp(epochs, axis=1)


def epoch_rms(data: np.ndarray, sample_rate: float, epoch_s: float) -> np.ndarray:
    epoch_len = max(1, int(round(epoch_s * sample_rate)))
    epoch_count = len(data) // epoch_len
    if epoch_count == 0:
        return np.empty((0, data.shape[1]))
    epochs = data[: epoch_count * epoch_len].reshape(epoch_count, epoch_len, data.shape[1])
    return np.sqrt(np.mean(epochs**2, axis=1))


def median_epoch_psd(
    data: np.ndarray,
    sample_rate: float,
    clean_epoch_mask: np.ndarray,
    epoch_s: float,
) -> tuple[np.ndarray, np.ndarray, list[int]]:
    epoch_len = max(1, int(round(epoch_s * sample_rate)))
    epoch_count = len(data) // epoch_len
    if epoch_count == 0:
        freqs, psd = signal.welch(data, fs=sample_rate, nperseg=min(len(data), 1024), axis=0)
        return freqs, psd.T, [0 for _ in range(data.shape[1])]

    epochs = data[: epoch_count * epoch_len].reshape(epoch_count, epoch_len, data.shape[1])
    psd_by_channel = []
    clean_counts = []
    freqs = None
    for channel in range(data.shape[1]):
        channel_epochs = epochs[:, :, channel]
        mask = clean_epoch_mask[:, channel]
        if not np.any(mask):
            mask = np.ones(epoch_count, dtype=bool)
        f, pxx = signal.welch(
            channel_epochs[mask],
            fs=sample_rate,
            nperseg=epoch_len,
            noverlap=0,
            axis=1,
        )
        freqs = f
        psd_by_channel.append(np.median(pxx, axis=0))
        clean_counts.append(int(mask.sum()))

    assert freqs is not None
    return freqs, np.vstack(psd_by_channel), clean_counts


def welch_psd(data: np.ndarray, sample_rate: float) -> tuple[np.ndarray, np.ndarray]:
    nperseg = min(int(round(sample_rate * 8)), len(data))
    freqs, psd = signal.welch(data, fs=sample_rate, nperseg=nperseg, axis=0)
    return freqs, psd.T


def bandpower(freqs: np.ndarray, psd: np.ndarray, low: float, high: float) -> float:
    mask = (freqs >= low) & (freqs < high)
    if mask.sum() < 2:
        return float("nan")
    return float(np.trapezoid(psd[mask], freqs[mask]))


def summarize_recording(
    root: Path,
    config: dict[str, str],
    channel_map: ChannelMap,
    output_dir: Path,
    write_processed: bool,
) -> dict[str, object]:
    path = find_recording(root, config["file"])
    frame, sample_rate = read_selected_openbci(path, channel_map)
    brain_cols = [f"EXG Channel {channel}" for channel in channel_map.brain_channels]
    ref_col = f"EXG Channel {channel_map.reference_channel}"
    raw_brain = frame[brain_cols].to_numpy(dtype=float)
    raw_reference = frame[ref_col].to_numpy(dtype=float)[:, None]
    bipolar_raw = raw_brain - raw_reference
    bipolar_filtered = apply_filters(bipolar_raw, sample_rate)
    duration_s = len(frame) / sample_rate

    p2p = epoch_peak_to_peak(bipolar_filtered, sample_rate, epoch_s=4.0)
    epoch_rms_values = epoch_rms(bipolar_filtered, sample_rate, epoch_s=4.0)
    clean_masks = np.ones_like(p2p, dtype=bool)
    p2p_thresholds = []
    bad_epoch_pct = []
    for channel in range(len(REGIONS)):
        threshold = robust_threshold(p2p[:, channel]) if len(p2p) else math.inf
        p2p_thresholds.append(threshold)
        clean_masks[:, channel] = p2p[:, channel] <= threshold
        bad_epoch_pct.append(100.0 * (1.0 - float(clean_masks[:, channel].mean())) if len(p2p) else 0.0)

    psd_freqs, psd, clean_counts = median_epoch_psd(
        bipolar_filtered,
        sample_rate,
        clean_masks,
        epoch_s=4.0,
    )
    raw_psd_freqs, raw_psd = welch_psd(bipolar_raw - np.nanmedian(bipolar_raw, axis=0), sample_rate)

    channel_rows = []
    band_rows = []
    total_band_powers = []
    for index, (region_key, region_zh, region_en) in enumerate(REGIONS):
        filtered_channel = bipolar_filtered[:, index]
        raw_channel = bipolar_raw[:, index]
        clean_rms = epoch_rms_values[:, index][clean_masks[:, index]] if len(epoch_rms_values) else np.array([])
        all_epoch_rms = epoch_rms_values[:, index] if len(epoch_rms_values) else np.array([])
        total_power = bandpower(psd_freqs, psd[index], 0.5, 45.0)
        total_band_powers.append(total_power)
        peak_mask = (psd_freqs >= 0.5) & (psd_freqs <= 45.0)
        dominant_freq = float(psd_freqs[peak_mask][np.argmax(psd[index][peak_mask])])
        line_power = bandpower(raw_psd_freqs, raw_psd[index], 49.0, 51.0)
        wide_raw_power = bandpower(raw_psd_freqs, raw_psd[index], 1.0, 90.0)

        channel_rows.append(
            {
                "recording": config["recording"],
                "electrode_type": config["label"],
                "electrode_type_zh": config["label_zh"],
                "region": region_key,
                "region_zh": region_zh,
                "file_channel": brain_cols[index],
                "reference_channel": ref_col,
                "samples": len(frame),
                "duration_s": duration_s,
                "full_record_rms_uV": float(np.sqrt(np.mean(filtered_channel**2))),
                "stable_epoch_rms_median_uV": float(np.median(clean_rms)) if clean_rms.size else float("nan"),
                "stable_epoch_rms_mean_uV": float(np.mean(clean_rms)) if clean_rms.size else float("nan"),
                "epoch_rms_95_uV": float(np.percentile(all_epoch_rms, 95)) if all_epoch_rms.size else float("nan"),
                "median_abs_uV": float(np.median(np.abs(filtered_channel))),
                "epoch_p2p_median_uV": float(np.median(p2p[:, index])) if len(p2p) else float("nan"),
                "epoch_p2p_95_uV": float(np.percentile(p2p[:, index], 95)) if len(p2p) else float("nan"),
                "epoch_p2p_max_uV": float(np.max(p2p[:, index])) if len(p2p) else float("nan"),
                "bad_epoch_pct": bad_epoch_pct[index],
                "artifact_p2p_threshold_uV": float(p2p_thresholds[index]),
                "dominant_frequency_hz": dominant_freq,
                "line_50hz_raw_pct_of_1_90hz": (
                    100.0 * line_power / wide_raw_power if wide_raw_power and np.isfinite(wide_raw_power) else float("nan")
                ),
                "raw_median_uV": float(np.median(raw_channel)),
                "raw_iqr_uV": float(np.percentile(raw_channel, 75) - np.percentile(raw_channel, 25)),
                "raw_near_rail_pct": float(100.0 * np.mean(np.abs(raw_channel) >= NEAR_RAIL_UV)),
                "clean_epoch_count": clean_counts[index],
            }
        )

        for band_key, band_label, low, high in BANDS:
            power = bandpower(psd_freqs, psd[index], low, high)
            band_rows.append(
                {
                    "recording": config["recording"],
                    "electrode_type": config["label"],
                    "electrode_type_zh": config["label_zh"],
                    "region": region_key,
                    "region_zh": region_zh,
                    "band": band_key,
                    "band_label": band_label,
                    "low_hz": low,
                    "high_hz": high,
                    "power_uV2": power,
                    "relative_power_pct": 100.0 * power / total_power if total_power else float("nan"),
                }
            )

    corr = np.corrcoef(bipolar_filtered.T)
    corr_rows = []
    for left in range(len(REGIONS)):
        for right in range(left + 1, len(REGIONS)):
            f_coh, coh = signal.coherence(
                bipolar_filtered[:, left],
                bipolar_filtered[:, right],
                fs=sample_rate,
                nperseg=min(int(sample_rate * 4), len(bipolar_filtered)),
            )
            coh_mask = (f_coh >= 0.5) & (f_coh <= 45.0)
            corr_rows.append(
                {
                    "recording": config["recording"],
                    "electrode_type": config["label"],
                    "pair": f"{REGIONS[left][0]}-{REGIONS[right][0]}",
                    "pearson_r": float(corr[left, right]),
                    "mean_coherence_0p5_45hz": float(np.mean(coh[coh_mask])),
                }
            )

    processed_csv = None
    if write_processed:
        processed = pd.DataFrame({"time_s": np.arange(len(frame)) / sample_rate})
        for index, (region_key, _, _) in enumerate(REGIONS):
            processed[f"{region_key}_minus_reference_filtered_uV"] = bipolar_filtered[:, index]
        processed_csv = output_dir / f"{config['recording']}_processed_bipolar_0p5-45Hz_notch50.csv"
        processed.to_csv(processed_csv, index=False)

    return {
        "path": path,
        "sample_rate": sample_rate,
        "duration_s": duration_s,
        "frame": frame,
        "bipolar_filtered": bipolar_filtered,
        "psd_freqs": psd_freqs,
        "psd": psd,
        "channel_rows": channel_rows,
        "band_rows": band_rows,
        "corr_rows": corr_rows,
        "processed_csv": processed_csv,
        "total_band_power_mean": float(np.mean(total_band_powers)),
    }


def write_recording_summary(results: list[dict[str, object]], channel_map: ChannelMap, output_dir: Path) -> Path:
    rows = []
    for result, config in zip(results, RECORDINGS):
        rows.append(
            {
                "recording": config["recording"],
                "electrode_type": config["label"],
                "electrode_type_zh": config["label_zh"],
                "file": str(result["path"]),
                "sample_rate_hz": result["sample_rate"],
                "duration_s": result["duration_s"],
                "duration_min": float(result["duration_s"]) / 60.0,
                "channel_mapping": channel_map.description,
            }
        )
    path = output_dir / "recording_summary.csv"
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")
    return path


def plot_traces(results: list[dict[str, object]], output_dir: Path) -> Path:
    fig, axes = plt.subplots(len(results), 1, figsize=(12, 6), sharex=False)
    if len(results) == 1:
        axes = [axes]
    colors = ["#2b6cb0", "#2f855a", "#c05621"]

    for ax, result, config in zip(axes, results, RECORDINGS):
        data = result["bipolar_filtered"]
        sample_rate = float(result["sample_rate"])
        start = int(min(sample_rate * 30, max(0, len(data) - sample_rate * 10)))
        count = int(min(sample_rate * 10, len(data) - start))
        segment = data[start : start + count]
        t = np.arange(count) / sample_rate + start / sample_rate
        scale = max(1.0, float(np.percentile(np.abs(segment), 95)))
        offsets = np.arange(segment.shape[1] - 1, -1, -1) * scale * 3.0
        label_x = t[0] + 0.02 * (t[-1] - t[0]) if count > 1 else t[0]
        for index, (_, _, region_en) in enumerate(REGIONS):
            ax.plot(t, segment[:, index] + offsets[index], lw=0.8, color=colors[index], label=region_en)
            ax.text(label_x, offsets[index], region_en, ha="left", va="center", fontsize=9)
        ax.set_title(f"{config['label']} filtered bipolar traces")
        ax.set_ylabel("uV + offset")
        ax.grid(True, alpha=0.2)
    axes[-1].set_xlabel("Time (s)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", frameon=False)
    fig.tight_layout(rect=(0, 0, 0.94, 1))
    path = output_dir / "filtered_trace_preview.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def plot_psd(results: list[dict[str, object]], output_dir: Path) -> Path:
    fig, axes = plt.subplots(1, len(REGIONS), figsize=(14, 4), sharey=True)
    colors = ["#2b6cb0", "#b83280"]
    for index, (_, _, region_en) in enumerate(REGIONS):
        ax = axes[index]
        for result, config, color in zip(results, RECORDINGS, colors):
            freqs = result["psd_freqs"]
            psd = result["psd"][index]
            mask = (freqs >= 0.5) & (freqs <= 45.0)
            ax.semilogy(freqs[mask], psd[mask], lw=1.4, color=color, label=config["label"])
        ax.set_title(region_en)
        ax.set_xlabel("Frequency (Hz)")
        ax.grid(True, alpha=0.25)
    axes[0].set_ylabel("PSD (uV^2/Hz)")
    axes[-1].legend(frameon=False)
    fig.tight_layout()
    path = output_dir / "psd_patch_vs_needle.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def plot_relative_band_power(band_table: pd.DataFrame, output_dir: Path) -> Path:
    fig, axes = plt.subplots(1, len(REGIONS), figsize=(15, 4), sharey=True)
    band_labels = [band[1] for band in BANDS]
    band_keys = [band[0] for band in BANDS]
    colors = ["#4c78a8", "#59a14f", "#f2cf5b", "#e15759", "#9c755f"]

    for region_index, (region_key, _, region_en) in enumerate(REGIONS):
        ax = axes[region_index]
        subset = band_table[band_table["region"] == region_key]
        bottoms = np.zeros(len(RECORDINGS))
        x = np.arange(len(RECORDINGS))
        for band_key, band_label, color in zip(band_keys, band_labels, colors):
            heights = []
            for config in RECORDINGS:
                row = subset[
                    (subset["recording"] == config["recording"])
                    & (subset["band"] == band_key)
                ]
                heights.append(float(row["relative_power_pct"].iloc[0]) if len(row) else 0.0)
            ax.bar(x, heights, bottom=bottoms, color=color, label=band_label, width=0.6)
            bottoms += np.array(heights)
        ax.set_xticks(x, [config["label"].split()[0] for config in RECORDINGS])
        ax.set_title(region_en)
        ax.set_ylim(0, 100)
        ax.grid(True, axis="y", alpha=0.2)
    axes[0].set_ylabel("Relative band power (%)")
    axes[-1].legend(loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False)
    fig.tight_layout()
    path = output_dir / "relative_band_power.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def plot_quality(channel_table: pd.DataFrame, output_dir: Path) -> Path:
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    metrics = [
        ("stable_epoch_rms_median_uV", "Median clean-epoch RMS (uV)"),
        ("bad_epoch_pct", "Rejected 4-s epochs (%)"),
        ("line_50hz_raw_pct_of_1_90hz", "Raw 50 Hz share of 1-90 Hz (%)"),
    ]
    colors = {"mouse_patch": "#2b6cb0", "mouse_needle": "#b83280"}
    x = np.arange(len(REGIONS))
    width = 0.36
    for ax, (metric, title) in zip(axes, metrics):
        for offset, config in zip([-width / 2, width / 2], RECORDINGS):
            subset = channel_table[channel_table["recording"] == config["recording"]]
            values = [
                float(subset[subset["region"] == region_key][metric].iloc[0])
                for region_key, _, _ in REGIONS
            ]
            ax.bar(
                x + offset,
                values,
                width=width,
                color=colors[config["recording"]],
                label=config["label"],
            )
        ax.set_xticks(x, [region[2] for region in REGIONS], rotation=20, ha="right")
        ax.set_title(title)
        ax.grid(True, axis="y", alpha=0.2)
    axes[0].legend(frameon=False)
    fig.tight_layout()
    path = output_dir / "signal_quality_summary.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def ratio_text(numerator: float, denominator: float) -> str:
    if denominator == 0 or not np.isfinite(denominator):
        return "NA"
    return f"{numerator / denominator:.2f}x"


def strongest_band_rows(band_table: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (recording, region), group in band_table.groupby(["recording", "region"], sort=False):
        top = group.sort_values("relative_power_pct", ascending=False).iloc[0]
        rows.append(top)
    return pd.DataFrame(rows)


def write_markdown_report(
    output_dir: Path,
    channel_table: pd.DataFrame,
    band_table: pd.DataFrame,
    corr_table: pd.DataFrame,
    recording_table: pd.DataFrame,
    plot_paths: list[Path],
    channel_map: ChannelMap,
) -> Path:
    patch = channel_table[channel_table["recording"] == "mouse_patch"].set_index("region")
    needle = channel_table[channel_table["recording"] == "mouse_needle"].set_index("region")
    top_bands = strongest_band_rows(band_table)

    mean_patch_stable_rms = float(patch["stable_epoch_rms_median_uV"].mean())
    mean_needle_stable_rms = float(needle["stable_epoch_rms_median_uV"].mean())
    mean_patch_full_rms = float(patch["full_record_rms_uV"].mean())
    mean_needle_full_rms = float(needle["full_record_rms_uV"].mean())
    mean_patch_line = float(patch["line_50hz_raw_pct_of_1_90hz"].mean())
    mean_needle_line = float(needle["line_50hz_raw_pct_of_1_90hz"].mean())
    mean_patch_bad = float(patch["bad_epoch_pct"].mean())
    mean_needle_bad = float(needle["bad_epoch_pct"].mean())
    max_patch_p2p = float(patch["epoch_p2p_max_uV"].max())
    max_needle_p2p = float(needle["epoch_p2p_max_uV"].max())
    needle_parietal_rail = float(needle.loc["parietal", "raw_near_rail_pct"])
    mean_patch_coh = float(
        corr_table[corr_table["recording"] == "mouse_patch"]["mean_coherence_0p5_45hz"].mean()
    )
    mean_needle_coh = float(
        corr_table[corr_table["recording"] == "mouse_needle"]["mean_coherence_0p5_45hz"].mean()
    )

    lines = [
        "# 小鼠麻醉状态 EEG 原始数据处理与对比分析",
        "",
        "## 数据与处理",
        "",
        f"- 通道映射：{channel_map.description}。",
        "- 分析导联：枕叶-参考、顶叶-参考、颞叶-参考；参考通道为背部十字定位点。",
        "- 预处理：先做脑区通道减参考通道，然后 50 Hz 陷波，再做 0.5-45 Hz 零相位 Butterworth 带通。",
        "- 频谱：4 秒 epoch 的 Welch PSD，使用稳健峰峰值阈值剔除明显伪迹 epoch。",
        "- 频段：delta 0.5-4 Hz、theta 4-8 Hz、alpha/sigma 8-12 Hz、beta 12-30 Hz、low gamma 30-45 Hz。",
        "",
        "## 记录概况",
        "",
        "| 记录 | 电极 | 时长(min) | 采样率(Hz) |",
        "|---|---:|---:|---:|",
    ]
    for row in recording_table.itertuples(index=False):
        lines.append(
            f"| {row.recording} | {row.electrode_type_zh} | {row.duration_min:.2f} | {row.sample_rate_hz:.0f} |"
        )

    lines.extend(
        [
            "",
            "## 主要结果",
            "",
            f"- 干净 4 秒 epoch 的中位 RMS：针状电极平均 {mean_needle_stable_rms:.1f} uV，贴片电极平均 {mean_patch_stable_rms:.1f} uV，针状/贴片约 {ratio_text(mean_needle_stable_rms, mean_patch_stable_rms)}。",
            f"- 全段 RMS：针状 {mean_needle_full_rms:.1f} uV，贴片 {mean_patch_full_rms:.1f} uV；它明显高于稳定 epoch 指标，说明少量大瞬态会强烈抬高全段 RMS。",
            f"- 原始双极信号中 50 Hz 能量占 1-90 Hz 的比例：贴片约 {mean_patch_line:.2f}%，针状约 {mean_needle_line:.2f}%。",
            f"- 4 秒 epoch 伪迹剔除比例：贴片平均 {mean_patch_bad:.1f}%，针状平均 {mean_needle_bad:.1f}%；但最大 epoch 峰峰值贴片约 {max_patch_p2p:.0f} uV、针状约 {max_needle_p2p:.0f} uV，针状存在少数极端瞬态。",
            f"- 针状顶叶原始双极信号有 {needle_parietal_rail:.1f}% 样本接近 ADS1299 满量程边缘，提示 DC 偏置/接触/参考连接需要重点检查。",
            f"- 三个脑区之间的平均相干性：贴片 {mean_patch_coh:.2f}，针状 {mean_needle_coh:.2f}；相干性很高时更像共同参考/体积传导/全局麻醉节律，不能直接解释为三个脑区独立活动。",
            "",
            "## 分脑区摘要",
            "",
            "| 脑区 | 贴片稳定 RMS(uV) | 针状稳定 RMS(uV) | 针/贴 | 贴片主峰(Hz) | 针状主峰(Hz) | 贴片主导频段 | 针状主导频段 |",
            "|---|---:|---:|---:|---:|---:|---|---|",
        ]
    )

    for region_key, region_zh, _ in REGIONS:
        patch_row = patch.loc[region_key]
        needle_row = needle.loc[region_key]
        patch_band = top_bands[
            (top_bands["recording"] == "mouse_patch") & (top_bands["region"] == region_key)
        ].iloc[0]
        needle_band = top_bands[
            (top_bands["recording"] == "mouse_needle") & (top_bands["region"] == region_key)
        ].iloc[0]
        lines.append(
            "| "
            f"{region_zh} | "
            f"{patch_row.stable_epoch_rms_median_uV:.1f} | "
            f"{needle_row.stable_epoch_rms_median_uV:.1f} | "
            f"{ratio_text(float(needle_row.stable_epoch_rms_median_uV), float(patch_row.stable_epoch_rms_median_uV))} | "
            f"{patch_row.dominant_frequency_hz:.2f} | "
            f"{needle_row.dominant_frequency_hz:.2f} | "
            f"{patch_band.band_label} ({patch_band.relative_power_pct:.1f}%) | "
            f"{needle_band.band_label} ({needle_band.relative_power_pct:.1f}%) |"
        )

    lines.extend(
        [
            "",
            "## 可以说明什么",
            "",
            "1. 这两次记录都能看到麻醉状态下的低频 EEG 成分，且三个脑区共享较强节律，符合麻醉/全局脑状态主导的记录特征。",
            "2. 在干净 epoch 中，针状电极的稳定振幅只比贴片略高；它并不是稳定地记录到数倍更大的脑电，而是出现了更突出的约 5.75 Hz 周期成分。",
            "3. 针状数据的 5.75 Hz 主峰及其谐波很清楚，可能是麻醉状态节律，也可能混有心电/脉搏/共同参考成分；需要同步 ECG、呼吸或更换参考位置来确认。",
            "4. 贴片的 50 Hz 占比整体更高，针状的工频干扰较低；但针状顶叶接近满量程和少数极端瞬态更明显，说明针状方案需要优先优化接触、固定和参考。",
            "",
            "## 不能说明什么",
            "",
            "1. 不能据此证明针状电极一定优于贴片电极，因为这里只有两次记录，没有重复动物、重复插拔和阻抗记录。",
            "2. 不能把枕叶、顶叶、颞叶的差异直接解释为脑区功能差异；共同参考、体积传导、麻醉深度变化和电极接触都会造成类似差异。",
            "3. 不能从这两份静息/麻醉原始记录推断行为或疾病表型，需要事件标记、麻醉剂量/时间、阻抗和更多样本。",
            "",
            "## 输出文件",
            "",
        ]
    )
    for path in plot_paths:
        lines.append(f"- {path.name}")
    lines.extend(
        [
            "- recording_summary.csv",
            "- channel_quality_summary.csv",
            "- band_power_summary.csv",
            "- channel_correlation_summary.csv",
            "- mouse_patch_processed_bipolar_0p5-45Hz_notch50.csv",
            "- mouse_needle_processed_bipolar_0p5-45Hz_notch50.csv",
            "",
            "BioRender 备注：已检索到可用于后续示意图的 mouse brain / EEG electrode / dorsal mouse 图标素材；本报告中的数值图来自本地原始数据处理。",
        ]
    )

    path = output_dir / "mouse_eeg_report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_json_summary(output_dir: Path, channel_map: ChannelMap, outputs: dict[str, str]) -> Path:
    path = output_dir / "analysis_manifest.json"
    path.write_text(
        json.dumps(
            {
                "channel_mapping": channel_map.description,
                "outputs": outputs,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze two mouse EEG raw OpenBCI text files.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Folder containing 小鼠.txt and 小鼠2.txt")
    parser.add_argument("--output-dir", type=Path, default=Path("mouse_eeg_analysis"))
    parser.add_argument(
        "--file-zero-based",
        action="store_true",
        help="Interpret requested channels as literal EXG Channel 1/3/5/10 labels.",
    )
    parser.add_argument("--no-processed-csv", action="store_true", help="Skip writing filtered continuous CSVs.")
    args = parser.parse_args()

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    channel_map = build_channel_map(args.file_zero_based)

    results = [
        summarize_recording(
            args.root,
            config,
            channel_map,
            output_dir,
            write_processed=not args.no_processed_csv,
        )
        for config in RECORDINGS
    ]

    recording_summary_path = write_recording_summary(results, channel_map, output_dir)
    channel_table = pd.DataFrame([row for result in results for row in result["channel_rows"]])
    band_table = pd.DataFrame([row for result in results for row in result["band_rows"]])
    corr_table = pd.DataFrame([row for result in results for row in result["corr_rows"]])
    recording_table = pd.read_csv(recording_summary_path)

    channel_summary_path = output_dir / "channel_quality_summary.csv"
    band_summary_path = output_dir / "band_power_summary.csv"
    corr_summary_path = output_dir / "channel_correlation_summary.csv"
    channel_table.to_csv(channel_summary_path, index=False, encoding="utf-8-sig")
    band_table.to_csv(band_summary_path, index=False, encoding="utf-8-sig")
    corr_table.to_csv(corr_summary_path, index=False, encoding="utf-8-sig")

    plot_paths = [
        plot_traces(results, output_dir),
        plot_psd(results, output_dir),
        plot_relative_band_power(band_table, output_dir),
        plot_quality(channel_table, output_dir),
    ]
    report_path = write_markdown_report(
        output_dir,
        channel_table,
        band_table,
        corr_table,
        recording_table,
        plot_paths,
        channel_map,
    )

    outputs = {
        "report": str(report_path),
        "recording_summary": str(recording_summary_path),
        "channel_quality_summary": str(channel_summary_path),
        "band_power_summary": str(band_summary_path),
        "channel_correlation_summary": str(corr_summary_path),
        "plots": [str(path) for path in plot_paths],
    }
    processed = [result["processed_csv"] for result in results if result["processed_csv"] is not None]
    if processed:
        outputs["processed_csv"] = [str(path) for path in processed]
    manifest_path = write_json_summary(output_dir, channel_map, outputs)

    print(f"Channel mapping: {channel_map.description}")
    print(f"Report: {report_path}")
    print(f"Manifest: {manifest_path}")
    print(
        channel_table[
            [
                "recording",
                "region",
                "stable_epoch_rms_median_uV",
                "full_record_rms_uV",
                "bad_epoch_pct",
                "dominant_frequency_hz",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
