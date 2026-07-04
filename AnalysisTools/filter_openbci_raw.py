"""Filter OpenBCI GUI RAW text exports.

Default processing is suitable for a first EEG inspection in a 50 Hz mains
environment: 50 Hz notch, then 0.5-40 Hz zero-phase Butterworth bandpass.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import signal


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_RECORDINGS_DIR = PROJECT_ROOT / "UserData" / "Recordings"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "filtered_data"


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


def find_latest_raw_file(recordings_dir: Path, min_bytes: int) -> Path:
    candidates = [
        path
        for path in recordings_dir.rglob("OpenBCI-RAW-*.txt")
        if path.is_file() and path.stat().st_size >= min_bytes
    ]
    if not candidates:
        raise FileNotFoundError(
            f"No OpenBCI-RAW-*.txt file >= {min_bytes} bytes found under {recordings_dir}"
        )
    return max(candidates, key=lambda path: path.stat().st_mtime)


def read_openbci_raw(path: Path) -> tuple[pd.DataFrame, pd.DataFrame, list[str], float]:
    header = parse_openbci_header(path)
    sample_rate = float(header.get("sample_rate", 250.0))

    frame = pd.read_csv(path, comment="%", skipinitialspace=True)
    exg_columns = [column for column in frame.columns if column.startswith("EXG Channel")]
    if not exg_columns:
        raise ValueError("No EXG Channel columns were found in the input file.")

    exg = frame[exg_columns].apply(pd.to_numeric, errors="coerce")
    valid_rows = ~exg.isna().all(axis=1)
    frame = frame.loc[valid_rows].reset_index(drop=True)
    exg = exg.loc[valid_rows].reset_index(drop=True)

    if len(exg) < int(sample_rate * 2):
        raise ValueError(
            f"Only {len(exg)} samples were found. Use a longer recording for filtering."
        )

    exg = exg.interpolate(limit_direction="both").fillna(0.0)
    return frame, exg, exg_columns, sample_rate


def apply_filters(
    exg: pd.DataFrame,
    sample_rate: float,
    lowcut: float | None,
    highcut: float | None,
    notch: float | None,
    notch_q: float,
    order: int,
) -> np.ndarray:
    nyquist = sample_rate / 2.0
    data = exg.to_numpy(dtype=float)

    if notch is not None:
        if not 0 < notch < nyquist:
            raise ValueError(f"Notch frequency must be between 0 and Nyquist ({nyquist:g} Hz).")
        b_notch, a_notch = signal.iirnotch(w0=notch, Q=notch_q, fs=sample_rate)
        data = signal.filtfilt(b_notch, a_notch, data, axis=0)

    if lowcut is not None and highcut is not None:
        if not 0 < lowcut < highcut < nyquist:
            raise ValueError(
                f"Bandpass must satisfy 0 < lowcut < highcut < Nyquist ({nyquist:g} Hz)."
            )
        sos = signal.butter(order, [lowcut, highcut], btype="bandpass", fs=sample_rate, output="sos")
        data = signal.sosfiltfilt(sos, data, axis=0)
    elif lowcut is not None:
        if not 0 < lowcut < nyquist:
            raise ValueError(f"High-pass cutoff must be between 0 and Nyquist ({nyquist:g} Hz).")
        sos = signal.butter(order, lowcut, btype="highpass", fs=sample_rate, output="sos")
        data = signal.sosfiltfilt(sos, data, axis=0)
    elif highcut is not None:
        if not 0 < highcut < nyquist:
            raise ValueError(f"Low-pass cutoff must be between 0 and Nyquist ({nyquist:g} Hz).")
        sos = signal.butter(order, highcut, btype="lowpass", fs=sample_rate, output="sos")
        data = signal.sosfiltfilt(sos, data, axis=0)

    return data


def write_filtered_csv(
    original: pd.DataFrame,
    exg_columns: list[str],
    filtered: np.ndarray,
    output_path: Path,
) -> None:
    output = pd.DataFrame()
    if "Sample Index" in original.columns:
        output["Sample Index"] = original["Sample Index"].values

    for index, column in enumerate(exg_columns):
        output[f"{column} filtered_uV"] = filtered[:, index]

    for column in ["Timestamp", "Timestamp (Formatted)"]:
        if column in original.columns:
            output[column] = original[column].values

    output.to_csv(output_path, index=False)


def write_preview_plot(
    raw: pd.DataFrame,
    filtered: np.ndarray,
    exg_columns: list[str],
    sample_rate: float,
    output_path: Path,
    seconds: float,
    channel_count: int,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    points = min(len(raw), max(1, int(seconds * sample_rate)))
    channels = list(range(min(channel_count, len(exg_columns))))
    t = np.arange(points) / sample_rate

    figure, axes = plt.subplots(len(channels), 1, figsize=(12, 2.2 * len(channels)), sharex=True)
    if len(channels) == 1:
        axes = [axes]

    raw_values = raw.to_numpy(dtype=float)
    for axis, channel in zip(axes, channels):
        raw_segment = raw_values[:points, channel]
        raw_segment = raw_segment - np.nanmedian(raw_segment)
        axis.plot(t, raw_segment, color="#9aa0a6", linewidth=0.7, label="raw, median removed")
        axis.plot(t, filtered[:points, channel], color="#1f77b4", linewidth=0.9, label="filtered")
        axis.set_ylabel(f"Ch {channel}\nuV")
        axis.grid(True, alpha=0.25)

    axes[0].legend(loc="upper right")
    axes[-1].set_xlabel("Time (s)")
    figure.tight_layout()
    figure.savefig(output_path, dpi=160)
    plt.close(figure)


def make_output_stem(input_path: Path, lowcut: float | None, highcut: float | None, notch: float | None) -> str:
    parts = [input_path.stem, "filtered"]
    if lowcut is not None and highcut is not None:
        parts.append(f"{lowcut:g}-{highcut:g}Hz")
    elif lowcut is not None:
        parts.append(f"highpass{lowcut:g}Hz")
    elif highcut is not None:
        parts.append(f"lowpass{highcut:g}Hz")
    if notch is not None:
        parts.append(f"notch{notch:g}Hz")
    return "_".join(parts).replace(".", "p")


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter an OpenBCI GUI RAW text recording.")
    parser.add_argument("--input", type=Path, default=None, help="OpenBCI-RAW-*.txt file to process")
    parser.add_argument("--recordings-dir", type=Path, default=DEFAULT_RECORDINGS_DIR)
    parser.add_argument("--min-bytes", type=int, default=10_000, help="minimum file size for auto-pick")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--lowcut", type=float, default=0.5, help="high-pass edge in Hz; use 0 to disable")
    parser.add_argument("--highcut", type=float, default=40.0, help="low-pass edge in Hz; use 0 to disable")
    parser.add_argument("--notch", type=float, default=50.0, help="notch frequency in Hz; use 0 to disable")
    parser.add_argument("--notch-q", type=float, default=30.0)
    parser.add_argument("--order", type=int, default=4)
    parser.add_argument("--preview-seconds", type=float, default=10.0)
    parser.add_argument("--preview-channels", type=int, default=16)
    parser.add_argument("--no-plot", action="store_true")
    args = parser.parse_args()

    recordings_dir = args.recordings_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    input_path = (
        args.input.expanduser().resolve()
        if args.input
        else find_latest_raw_file(recordings_dir, args.min_bytes)
    )
    lowcut = args.lowcut if args.lowcut > 0 else None
    highcut = args.highcut if args.highcut > 0 else None
    notch = args.notch if args.notch > 0 else None

    original, exg, exg_columns, sample_rate = read_openbci_raw(input_path)
    filtered = apply_filters(exg, sample_rate, lowcut, highcut, notch, args.notch_q, args.order)

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = make_output_stem(input_path, lowcut, highcut, notch)
    csv_path = output_dir / f"{stem}.csv"
    write_filtered_csv(original, exg_columns, filtered, csv_path)

    print(f"Input: {input_path}")
    print(f"Samples: {len(exg)}")
    print(f"Channels: {len(exg_columns)}")
    print(f"Sample rate: {sample_rate:g} Hz")
    print(f"Filtered CSV: {csv_path}")

    if not args.no_plot:
        png_path = output_dir / f"{stem}_preview.png"
        write_preview_plot(
            exg,
            filtered,
            exg_columns,
            sample_rate,
            png_path,
            args.preview_seconds,
            args.preview_channels,
        )
        print(f"Preview plot: {png_path}")


if __name__ == "__main__":
    main()
