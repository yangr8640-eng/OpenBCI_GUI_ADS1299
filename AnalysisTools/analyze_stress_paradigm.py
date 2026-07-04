"""Analyze the EEG stress/anxiety paradigm output.

Inputs:
1. continuous EEG CSV from prepare_eeg_paradigm_format.py
2. events.csv exported by anxiety-induction-program/index.html
3. optional channels.csv and questionnaire_results.json/csv

The report is a research feedback score, not a clinical diagnosis.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import signal


DEFAULT_CHANNEL_POSITIONS = {
    "Ch01": "Fp1",
    "Ch02": "Fp2",
    "Ch03": "F3",
    "Ch04": "F4",
    "Ch05": "F7",
    "Ch06": "F8",
    "Ch07": "C3",
    "Ch08": "C4",
    "Ch09": "P3",
    "Ch10": "P4",
    "Ch11": "O1",
    "Ch12": "O2",
    "Ch13": "Fz",
    "Ch14": "Cz",
    "Ch15": "Pz",
    "Ch16": "Oz",
}

EVENT_START_CODES = {
    "baseline_open": {11},
    "baseline_closed": {13},
    "neutral": {30},
    "stress": {40},
    "recovery": {50},
}

EVENT_END_CODES = {
    "baseline_open": {12},
    "baseline_closed": {14},
    "neutral": {33},
    "stress": {45},
    "recovery": {51},
}

FEATURE_NAMES = [
    "frontal_alpha",
    "beta_alpha",
    "relative_beta",
    "frontal_theta",
    "theta_beta",
    "right_frontal_activation",
]


@dataclass
class Segment:
    condition: str
    start_s: float
    end_s: float
    start_sample: int
    end_sample: int


def find_latest(pattern: str, root: Path) -> Path:
    candidates = [path for path in root.glob(pattern) if path.is_file()]
    if not candidates:
        raise FileNotFoundError(f"No file matched {root / pattern}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def matching_path(continuous_path: Path, suffix: str) -> Path | None:
    name = continuous_path.name
    if name.endswith("_continuous_eeg.csv"):
        candidate = continuous_path.with_name(name.replace("_continuous_eeg.csv", suffix))
        if candidate.exists():
            return candidate
    return None


def read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def infer_sample_rate(
    continuous: pd.DataFrame,
    metadata: dict[str, Any],
    override: float | None,
) -> float:
    if override:
        return float(override)
    if "sample_rate_hz" in metadata:
        return float(metadata["sample_rate_hz"])
    if "time_s" in continuous.columns and len(continuous) > 2:
        time_s = pd.to_numeric(continuous["time_s"], errors="coerce")
        diffs = time_s.diff().dropna()
        diffs = diffs[(diffs > 0) & np.isfinite(diffs)]
        if not diffs.empty:
            return round(1.0 / float(diffs.median()), 6)
    return 250.0


def channel_columns(continuous: pd.DataFrame) -> list[str]:
    channels = [column for column in continuous.columns if column.startswith("Ch")]
    if not channels:
        raise ValueError("Continuous EEG CSV has no ChXX columns.")
    return channels


def load_channel_positions(path: Path | None, channels: list[str]) -> dict[str, str]:
    positions = {channel: DEFAULT_CHANNEL_POSITIONS.get(channel, "") for channel in channels}
    if path is None or not path.exists():
        return positions

    table = pd.read_csv(path)
    if "channel_name" not in table.columns:
        return positions

    for row in table.itertuples(index=False):
        name = str(getattr(row, "channel_name", ""))
        position = ""
        if "electrode_position" in table.columns:
            position = str(getattr(row, "electrode_position", "") or "").strip()
        if name in positions and position and position.lower() != "nan":
            positions[name] = position
    return positions


def clean_events(raw: pd.DataFrame, continuous: pd.DataFrame, sample_rate_hz: float) -> pd.DataFrame:
    if raw.empty:
        raise ValueError(
            "缺少有效 events：当前事件表为空，不能进行范式分段分析。请先从 index.html 导出 events.csv。"
        )

    events = raw.copy()
    for column in ["code", "duration_s", "onset_sample", "onset_time_s", "event_unix_s"]:
        if column not in events.columns:
            events[column] = np.nan
        events[column] = pd.to_numeric(events[column], errors="coerce")
    for column in ["condition", "notes"]:
        if column not in events.columns:
            events[column] = ""
        events[column] = events[column].fillna("").astype(str)

    has_time = events["onset_time_s"].notna()
    has_sample = events["onset_sample"].notna()
    events.loc[~has_time & has_sample, "onset_time_s"] = (
        events.loc[~has_time & has_sample, "onset_sample"] / sample_rate_hz
    )

    if "absolute_timestamp" in continuous.columns:
        eeg_start = pd.to_numeric(continuous["absolute_timestamp"], errors="coerce").dropna()
        if not eeg_start.empty:
            first_timestamp = float(eeg_start.iloc[0])
            missing_time = events["onset_time_s"].isna() & events["event_unix_s"].notna()
            events.loc[missing_time, "onset_time_s"] = (
                events.loc[missing_time, "event_unix_s"] - first_timestamp
            )

    missing_sample = events["onset_sample"].isna() & events["onset_time_s"].notna()
    events.loc[missing_sample, "onset_sample"] = np.rint(
        events.loc[missing_sample, "onset_time_s"] * sample_rate_hz
    )

    valid = events["onset_time_s"].notna() & np.isfinite(events["onset_time_s"])
    if not valid.any():
        raise ValueError(
            "events.csv 中没有可用 onset_time_s/onset_sample，也无法用 event_unix_s 与 EEG absolute_timestamp 对齐。"
        )
    return events.loc[valid].reset_index(drop=True)


def find_segment(
    events: pd.DataFrame,
    condition: str,
    sample_rate_hz: float,
    sample_count: int,
) -> Segment | None:
    condition_rows = events[events["condition"].str.lower() == condition.lower()].copy()
    if condition_rows.empty:
        return None

    start_codes = EVENT_START_CODES.get(condition, set())
    end_codes = EVENT_END_CODES.get(condition, set())
    start_rows = condition_rows[condition_rows["code"].isin(start_codes)]
    if start_rows.empty:
        start_rows = condition_rows[condition_rows["notes"].str.contains("start", case=False, na=False)]
    if start_rows.empty:
        start_rows = condition_rows.head(1)

    start_row = start_rows.iloc[0]
    start_s = float(start_row["onset_time_s"])

    duration = float(start_row["duration_s"]) if pd.notna(start_row["duration_s"]) else math.nan
    end_rows = condition_rows[condition_rows["code"].isin(end_codes)]
    if end_rows.empty:
        end_rows = condition_rows[condition_rows["notes"].str.contains("end", case=False, na=False)]
    if pd.notna(duration) and duration > 0:
        end_s = start_s + duration
    elif not end_rows.empty:
        end_s = float(end_rows.iloc[-1]["onset_time_s"])
    else:
        return None

    total_duration = sample_count / sample_rate_hz
    start_s = max(0.0, min(start_s, total_duration))
    end_s = max(0.0, min(end_s, total_duration))
    if end_s - start_s < 2.0:
        return None

    start_sample = max(0, min(sample_count - 1, int(round(start_s * sample_rate_hz))))
    end_sample = max(start_sample + 1, min(sample_count, int(round(end_s * sample_rate_hz))))
    return Segment(condition, start_s, end_s, start_sample, end_sample)


def build_segments(events: pd.DataFrame, sample_rate_hz: float, sample_count: int) -> dict[str, Segment]:
    segments: dict[str, Segment] = {}
    for condition in EVENT_START_CODES:
        segment = find_segment(events, condition, sample_rate_hz, sample_count)
        if segment is not None:
            segments[condition] = segment

    if "baseline_open" not in segments and "baseline_closed" not in segments:
        raise ValueError("缺少 baseline_open/baseline_closed 事件，无法建立个人基线。")
    if "stress" not in segments:
        raise ValueError("缺少 stress 事件，无法计算压力任务 EEG 指标。")
    return segments


def preprocess_eeg(
    continuous: pd.DataFrame,
    channels: list[str],
    sample_rate_hz: float,
    *,
    apply_filter: bool,
    reference: str,
) -> tuple[np.ndarray, dict[str, Any]]:
    data = continuous[channels].apply(pd.to_numeric, errors="coerce")
    missing_ratio = data.isna().mean().to_dict()
    data = data.interpolate(limit_direction="both").fillna(0.0).to_numpy(dtype=float)
    data = data - np.nanmedian(data, axis=0, keepdims=True)

    robust_std = np.nanmedian(np.abs(data - np.nanmedian(data, axis=0, keepdims=True)), axis=0) * 1.4826
    p2p_robust = np.nanpercentile(data, 99, axis=0) - np.nanpercentile(data, 1, axis=0)
    bad_mask = (robust_std < 0.05) | (p2p_robust > 5000) | ~np.isfinite(robust_std)
    bad_channels = [channels[index] for index, bad in enumerate(bad_mask) if bad]

    if apply_filter and len(data) > int(sample_rate_hz * 4):
        nyquist = sample_rate_hz / 2.0
        try:
            if 0 < 50 < nyquist:
                b_notch, a_notch = signal.iirnotch(w0=50.0, Q=30.0, fs=sample_rate_hz)
                data = signal.filtfilt(b_notch, a_notch, data, axis=0)
            highcut = min(40.0, nyquist * 0.9)
            if 0.5 < highcut:
                sos = signal.butter(
                    4,
                    [0.5, highcut],
                    btype="bandpass",
                    fs=sample_rate_hz,
                    output="sos",
                )
                data = signal.sosfiltfilt(sos, data, axis=0)
        except ValueError:
            pass

    good_mask = ~bad_mask
    if reference == "average" and good_mask.sum() >= 2:
        data = data - np.nanmean(data[:, good_mask], axis=1, keepdims=True)

    quality = {
        "missing_ratio_by_channel": missing_ratio,
        "robust_std_uv_by_channel": {
            channel: float(value) for channel, value in zip(channels, robust_std)
        },
        "robust_p2p_uv_by_channel": {
            channel: float(value) for channel, value in zip(channels, p2p_robust)
        },
        "bad_channels": bad_channels,
        "bad_channel_ratio": float(len(bad_channels) / len(channels)),
        "reference": reference,
        "filter_applied": apply_filter,
    }
    return data, quality


def channel_groups(channels: list[str], positions: dict[str, str]) -> dict[str, list[int]]:
    position_to_index = {
        positions.get(channel, channel).lower(): index for index, channel in enumerate(channels)
    }

    def pick(names: list[str], fallback: list[int]) -> list[int]:
        found = [position_to_index[name.lower()] for name in names if name.lower() in position_to_index]
        if found:
            return found
        return [index for index in fallback if index < len(channels)]

    left = pick(["Fp1", "F3", "F7"], [0, 2, 4])
    right = pick(["Fp2", "F4", "F8"], [1, 3, 5])
    frontal = sorted(set(left + right + pick(["Fz"], [12])))
    return {
        "frontal_left": left,
        "frontal_right": right,
        "frontal": frontal,
    }


def band_power(freqs: np.ndarray, psd: np.ndarray, low: float, high: float) -> np.ndarray:
    mask = (freqs >= low) & (freqs < high)
    if not mask.any():
        return np.zeros(psd.shape[1], dtype=float)
    return np.trapezoid(psd[mask], freqs[mask], axis=0)


def compute_window_features(
    window: np.ndarray,
    sample_rate_hz: float,
    groups: dict[str, list[int]],
) -> dict[str, float]:
    nperseg = min(len(window), int(sample_rate_hz * 2))
    freqs, psd = signal.welch(window, fs=sample_rate_hz, nperseg=nperseg, axis=0)
    theta = band_power(freqs, psd, 4.0, 8.0)
    alpha = band_power(freqs, psd, 8.0, 13.0)
    beta = band_power(freqs, psd, 13.0, 30.0)
    eps = 1e-12

    frontal = groups["frontal"]
    left = groups["frontal_left"]
    right = groups["frontal_right"]

    frontal_alpha = float(np.nanmean(alpha[frontal]))
    frontal_beta = float(np.nanmean(beta[frontal]))
    frontal_theta = float(np.nanmean(theta[frontal]))
    alpha_left = float(np.nanmean(alpha[left]))
    alpha_right = float(np.nanmean(alpha[right]))
    total_power = frontal_theta + frontal_alpha + frontal_beta + eps

    return {
        "frontal_alpha": frontal_alpha,
        "beta_alpha": frontal_beta / (frontal_alpha + eps),
        "relative_beta": frontal_beta / total_power,
        "frontal_theta": frontal_theta,
        "theta_beta": frontal_theta / (frontal_beta + eps),
        "right_frontal_activation": math.log(alpha_left + eps) - math.log(alpha_right + eps),
    }


def window_is_clean(window: np.ndarray) -> bool:
    if not np.isfinite(window).all():
        return False
    p2p = np.nanpercentile(window, 99, axis=0) - np.nanpercentile(window, 1, axis=0)
    return bool(np.nanmedian(p2p) < 1000 and np.nanmax(p2p) < 5000)


def features_for_segment(
    data: np.ndarray,
    segment: Segment,
    sample_rate_hz: float,
    groups: dict[str, list[int]],
) -> tuple[list[dict[str, float]], dict[str, Any]]:
    window_size = max(8, int(round(sample_rate_hz * 2.0)))
    step = max(1, int(round(sample_rate_hz * 1.0)))
    features: list[dict[str, float]] = []
    clean_features: list[dict[str, float]] = []
    total_windows = 0
    clean_windows = 0

    for start in range(segment.start_sample, segment.end_sample - window_size + 1, step):
        window = data[start : start + window_size]
        if len(window) < window_size:
            continue
        total_windows += 1
        row = compute_window_features(window, sample_rate_hz, groups)
        row["start_s"] = start / sample_rate_hz
        row["clean"] = float(window_is_clean(window))
        features.append(row)
        if row["clean"]:
            clean_windows += 1
            clean_features.append(row)

    selected = clean_features if clean_features else features
    quality = {
        "total_windows": total_windows,
        "clean_windows": clean_windows,
        "used_clean_windows": bool(clean_features),
        "duration_s": segment.end_s - segment.start_s,
    }
    return selected, quality


def median_features(rows: list[dict[str, float]]) -> dict[str, float] | None:
    if not rows:
        return None
    return {
        name: float(np.nanmedian([row[name] for row in rows if np.isfinite(row.get(name, np.nan))]))
        for name in FEATURE_NAMES
    }


def robust_stats(rows: list[dict[str, float]], feature_name: str) -> tuple[float, float]:
    values = np.array([row[feature_name] for row in rows if np.isfinite(row.get(feature_name, np.nan))])
    if values.size == 0:
        return 0.0, 1.0
    median = float(np.nanmedian(values))
    mad = float(np.nanmedian(np.abs(values - median))) * 1.4826
    if not np.isfinite(mad) or mad < 1e-12:
        std = float(np.nanstd(values))
        mad = std if std > 1e-12 else 1.0
    return median, mad


def robust_z(value: float, baseline_rows: list[dict[str, float]], feature_name: str) -> float:
    median, scale = robust_stats(baseline_rows, feature_name)
    return float((value - median) / scale)


def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def load_questionnaire(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"available": False}

    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        scores = data.get("scores", {})
        pre = (scores.get("pre") or {}).get("totalNorm")
        post = (scores.get("post") or {}).get("totalNorm")
        delta = scores.get("delta")
        subjective = scores.get("subjectiveStress")
        return {
            "available": True,
            "source": str(path),
            "pre_norm": to_optional_float(pre),
            "post_norm": to_optional_float(post),
            "delta_norm": to_optional_float(delta),
            "subjective_stress": to_optional_float(subjective),
        }

    table = pd.read_csv(path)
    result: dict[str, Any] = {"available": True, "source": str(path)}
    for phase in ("pre", "post"):
        rows = table[table.get("phase", pd.Series(dtype=str)).astype(str).str.lower() == phase]
        if rows.empty:
            result[f"{phase}_norm"] = None
        elif "total_norm" in rows.columns and pd.to_numeric(rows["total_norm"], errors="coerce").notna().any():
            result[f"{phase}_norm"] = float(pd.to_numeric(rows["total_norm"], errors="coerce").dropna().iloc[0])
        elif "score_0_100" in rows.columns:
            result[f"{phase}_norm"] = float(pd.to_numeric(rows["score_0_100"], errors="coerce").mean())
    if result.get("pre_norm") is not None and result.get("post_norm") is not None:
        result["delta_norm"] = float(result["post_norm"] - result["pre_norm"])
    if "subjective_stress" in table.columns:
        values = pd.to_numeric(table["subjective_stress"], errors="coerce").dropna()
        result["subjective_stress"] = float(values.iloc[-1]) if not values.empty else None
    return result


def to_optional_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def score_level(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "无法评估"
    if value <= 34:
        return "低"
    if value <= 64:
        return "中"
    return "高"


def compute_scores(
    phase_features: dict[str, dict[str, float] | None],
    window_features: dict[str, list[dict[str, float]]],
    questionnaire: dict[str, Any],
) -> dict[str, Any]:
    baseline_rows = window_features.get("baseline_open", []) + window_features.get("baseline_closed", [])
    stress = phase_features.get("stress")
    eeg_score = None
    z_features: dict[str, float] = {}
    eeg_signal = None

    if baseline_rows and stress:
        for name in FEATURE_NAMES:
            z_features[name] = robust_z(stress[name], baseline_rows, name)
        neg_alpha_baseline = [{**row, "negative_alpha": -row["frontal_alpha"]} for row in baseline_rows]
        z_neg_alpha = robust_z(-stress["frontal_alpha"], neg_alpha_baseline, "negative_alpha")
        z_features["negative_frontal_alpha"] = z_neg_alpha
        eeg_signal = (
            0.35 * z_features["beta_alpha"]
            + 0.25 * z_features["relative_beta"]
            + 0.20 * z_neg_alpha
            + 0.20 * z_features["right_frontal_activation"]
        )
        eeg_score = round(100.0 * sigmoid(eeg_signal), 2)

    subjective_score = None
    if questionnaire.get("available"):
        post = questionnaire.get("post_norm")
        delta = questionnaire.get("delta_norm")
        subjective_vas = questionnaire.get("subjective_stress")
        post_component = post if post is not None else subjective_vas
        if post_component is not None:
            delta_component = 50.0 + (delta or 0.0)
            subjective_score = round(clamp(0.6 * post_component + 0.4 * delta_component, 0.0, 100.0), 2)

    if eeg_score is not None and subjective_score is not None:
        stress_index = round(0.55 * eeg_score + 0.45 * subjective_score, 2)
    elif eeg_score is not None:
        stress_index = eeg_score
    elif subjective_score is not None:
        stress_index = subjective_score
    else:
        stress_index = None

    return {
        "eeg_score": eeg_score,
        "eeg_signal": None if eeg_signal is None else round(eeg_signal, 6),
        "subjective_score": subjective_score,
        "stress_index": stress_index,
        "level": score_level(stress_index),
        "z_features": z_features,
        "formula": {
            "eeg_score": "100 * sigmoid(0.35*z(beta_alpha) + 0.25*z(relative_beta) + 0.20*z(-alpha) + 0.20*z(right_frontal_activation))",
            "subjective_score": "clamp(0.6*post_questionnaire_norm + 0.4*(50 + post_pre_delta), 0, 100)",
            "stress_index": "0.55*eeg_score + 0.45*subjective_score when both are available",
        },
    }


def compute_confidence(
    segment_quality: dict[str, dict[str, Any]],
    preprocessing_quality: dict[str, Any],
    events: pd.DataFrame,
    questionnaire: dict[str, Any],
    scores: dict[str, Any],
) -> dict[str, Any]:
    total_windows = sum(int(item["total_windows"]) for item in segment_quality.values())
    clean_windows = sum(int(item["clean_windows"]) for item in segment_quality.values())
    usable_ratio = clean_windows / total_windows if total_windows else 0.0
    if clean_windows == 0 and total_windows:
        usable_ratio = 0.35

    required = ["baseline_open", "baseline_closed", "neutral", "stress", "recovery"]
    present = sum(1 for condition in required if condition in segment_quality)
    event_ratio = present / len(required)
    bad_channel_ratio = float(preprocessing_quality["bad_channel_ratio"])
    questionnaire_ratio = 1.0 if questionnaire.get("available") else 0.0

    confidence = 100.0 * (
        0.35 * usable_ratio
        + 0.25 * max(0.0, 1.0 - bad_channel_ratio)
        + 0.25 * event_ratio
        + 0.15 * questionnaire_ratio
    )
    if scores.get("eeg_score") is None:
        confidence = min(confidence, 45.0)
    if scores.get("subjective_score") is None:
        confidence = min(confidence, 85.0)

    warnings: list[str] = []
    if usable_ratio < 0.4:
        warnings.append("可用 EEG 窗口比例偏低，建议检查电极、运动伪迹和采集质量。")
    if bad_channel_ratio > 0.25:
        warnings.append("坏通道比例偏高，建议重采或调整导联。")
    if event_ratio < 1.0:
        warnings.append("部分实验阶段事件缺失，报告置信度降低。")
    if not questionnaire.get("available"):
        warnings.append("未提供问卷结果，综合压力指数只参考 EEG。")

    return {
        "confidence": round(clamp(confidence, 0.0, 100.0), 2),
        "usable_window_ratio": round(usable_ratio, 4),
        "total_windows": total_windows,
        "clean_windows": clean_windows,
        "bad_channel_ratio": round(bad_channel_ratio, 4),
        "event_count": int(len(events)),
        "required_segment_ratio": round(event_ratio, 4),
        "questionnaire_available": bool(questionnaire.get("available")),
        "warnings": warnings,
    }


def round_nested(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: round_nested(item) for key, item in value.items()}
    if isinstance(value, list):
        return [round_nested(item) for item in value]
    if isinstance(value, float):
        if math.isfinite(value):
            return round(value, 6)
        return None
    return value


def render_html_report(report: dict[str, Any]) -> str:
    scores = report["scores"]
    quality = report["data_quality"]
    features = report["eeg_features"]

    def esc(value: Any) -> str:
        return html.escape("" if value is None else str(value))

    rows = []
    for condition, values in features.items():
        if values is None:
            continue
        rows.append(
            "<tr>"
            f"<td>{esc(condition)}</td>"
            f"<td>{esc(values.get('frontal_alpha'))}</td>"
            f"<td>{esc(values.get('beta_alpha'))}</td>"
            f"<td>{esc(values.get('relative_beta'))}</td>"
            f"<td>{esc(values.get('frontal_theta'))}</td>"
            f"<td>{esc(values.get('right_frontal_activation'))}</td>"
            "</tr>"
        )

    warnings = "".join(f"<li>{esc(item)}</li>" for item in quality["warnings"]) or "<li>无明显质量警告。</li>"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EEG 压力范式报告</title>
  <style>
    body {{ margin: 0; background: #f5f7f8; color: #1d252c; font-family: "Microsoft YaHei", Arial, sans-serif; }}
    main {{ max-width: 1040px; margin: 0 auto; padding: 28px; }}
    section {{ background: #fff; border: 1px solid #d7dee3; border-radius: 8px; padding: 20px; margin-bottom: 16px; }}
    h1, h2 {{ margin: 0 0 10px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .metric {{ border: 1px solid #d7dee3; border-radius: 8px; padding: 14px; }}
    .metric b {{ display: block; font-size: 28px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #d7dee3; padding: 9px; text-align: left; }}
    th {{ background: #eef3f5; }}
    @media (max-width: 760px) {{ .grid {{ grid-template-columns: 1fr; }} main {{ padding: 14px; }} }}
  </style>
</head>
<body>
  <main>
    <section>
      <h1>EEG 压力/状态焦虑报告</h1>
      <p>生成时间：{esc(report["generated_at"])}</p>
      <p>本报告用于实验反馈，不作为医学诊断。</p>
    </section>
    <section>
      <h2>评分</h2>
      <div class="grid">
        <div class="metric"><b>{esc(scores.get("stress_index"))}</b><span>综合压力指数</span></div>
        <div class="metric"><b>{esc(scores.get("level"))}</b><span>等级</span></div>
        <div class="metric"><b>{esc(scores.get("eeg_score"))}</b><span>EEG 分</span></div>
        <div class="metric"><b>{esc(scores.get("subjective_score"))}</b><span>主观分</span></div>
      </div>
    </section>
    <section>
      <h2>数据质量</h2>
      <div class="grid">
        <div class="metric"><b>{esc(quality.get("confidence"))}</b><span>置信度</span></div>
        <div class="metric"><b>{esc(quality.get("usable_window_ratio"))}</b><span>可用窗口比例</span></div>
        <div class="metric"><b>{esc(quality.get("bad_channel_ratio"))}</b><span>坏通道比例</span></div>
        <div class="metric"><b>{esc(quality.get("event_count"))}</b><span>事件数</span></div>
      </div>
      <ul>{warnings}</ul>
    </section>
    <section>
      <h2>EEG 特征中位数</h2>
      <table>
        <thead><tr><th>阶段</th><th>frontal alpha</th><th>beta/alpha</th><th>relative beta</th><th>frontal theta</th><th>右额叶激活指数</th></tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


def analyze(args: argparse.Namespace) -> tuple[dict[str, Any], Path, Path]:
    continuous_path = args.continuous or find_latest("*_continuous_eeg.csv", Path("analysis_ready"))
    continuous = pd.read_csv(continuous_path)
    metadata_path = args.metadata or matching_path(continuous_path, "_metadata.json")
    metadata = read_json(metadata_path)
    sample_rate_hz = infer_sample_rate(continuous, metadata, args.sample_rate)
    channels = channel_columns(continuous)
    channel_path = args.channels or matching_path(continuous_path, "_channels.csv")
    positions = load_channel_positions(channel_path, channels)

    events_path = args.events or matching_path(continuous_path, "_events.csv")
    if events_path is None:
        raise FileNotFoundError("No events file was provided and no matching *_events.csv was found.")
    events_raw = pd.read_csv(events_path)
    events = clean_events(events_raw, continuous, sample_rate_hz)
    segments = build_segments(events, sample_rate_hz, len(continuous))

    data, preprocessing_quality = preprocess_eeg(
        continuous,
        channels,
        sample_rate_hz,
        apply_filter=not args.no_filter,
        reference=args.reference,
    )
    groups = channel_groups(channels, positions)

    window_features: dict[str, list[dict[str, float]]] = {}
    segment_quality: dict[str, dict[str, Any]] = {}
    phase_features: dict[str, dict[str, float] | None] = {}
    for condition, segment in segments.items():
        rows, quality = features_for_segment(data, segment, sample_rate_hz, groups)
        window_features[condition] = rows
        segment_quality[condition] = quality
        phase_features[condition] = median_features(rows)

    questionnaire = load_questionnaire(args.questionnaire)
    scores = compute_scores(phase_features, window_features, questionnaire)
    confidence = compute_confidence(segment_quality, preprocessing_quality, events, questionnaire, scores)
    scores["confidence"] = confidence["confidence"]

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "inputs": {
            "continuous": str(continuous_path.resolve()),
            "events": str(events_path.resolve()),
            "channels": str(channel_path.resolve()) if channel_path else None,
            "metadata": str(metadata_path.resolve()) if metadata_path else None,
            "questionnaire": str(args.questionnaire.resolve()) if args.questionnaire else None,
        },
        "sample_rate_hz": sample_rate_hz,
        "channel_positions": positions,
        "segments": {
            key: {
                "start_s": value.start_s,
                "end_s": value.end_s,
                "start_sample": value.start_sample,
                "end_sample": value.end_sample,
            }
            for key, value in segments.items()
        },
        "eeg_features": phase_features,
        "segment_quality": segment_quality,
        "preprocessing_quality": preprocessing_quality,
        "questionnaire": questionnaire,
        "scores": scores,
        "data_quality": confidence,
        "note": "Research feedback only; not a medical or clinical anxiety diagnosis.",
    }

    report = round_nested(report)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = continuous_path.stem.replace("_paradigm_ready_continuous_eeg", "")
    json_path = args.output_dir / f"{stem}_stress_report.json"
    html_path = args.output_dir / f"{stem}_stress_report.html"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_html_report(report), encoding="utf-8")
    return report, json_path, html_path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze an EEG stress/anxiety paradigm session.")
    parser.add_argument("--continuous", type=Path, default=None, help="*_continuous_eeg.csv")
    parser.add_argument("--events", type=Path, default=None, help="events.csv exported by index.html")
    parser.add_argument("--channels", type=Path, default=None, help="optional *_channels.csv")
    parser.add_argument("--metadata", type=Path, default=None, help="optional *_metadata.json")
    parser.add_argument("--questionnaire", type=Path, default=None, help="questionnaire_results.json or .csv")
    parser.add_argument("--output-dir", type=Path, default=Path("stress_analysis"))
    parser.add_argument("--sample-rate", type=float, default=None)
    parser.add_argument("--no-filter", action="store_true", help="skip analysis-time bandpass/notch filtering")
    parser.add_argument("--reference", choices=("average", "none"), default="average")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = build_arg_parser().parse_args(argv)
    try:
        report, json_path, html_path = analyze(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    scores = report["scores"]
    print(f"Stress index: {scores.get('stress_index')} ({scores.get('level')})")
    print(f"EEG score: {scores.get('eeg_score')}")
    print(f"Subjective score: {scores.get('subjective_score')}")
    print(f"Confidence: {scores.get('confidence')}")
    print(f"JSON report: {json_path}")
    print(f"HTML report: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
