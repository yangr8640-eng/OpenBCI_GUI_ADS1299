"""
Modified MIST EEG experiment implemented with PsychoPy.

Current design
--------------
1. Subject information input inside the PsychoPy window.
2. Eyes-open resting baseline, 3 min.
3. Eyes-closed resting baseline, 3 min.
4. Practice arithmetic-fill stage, 3 min.
5. Control arithmetic-fill stage, 3 min.
6. Stress arithmetic-fill stage, 3 min.
7. Recovery stage, 3 min.
8. VAS rating after each block.
9. LSL markers for EEG synchronization.
10. Trial-level CSV logging.

Task
----
Participants type the numerical answer to each arithmetic expression and press
Enter. Example: "12 + 7 = ?" -> type "19" -> Enter.

Convenience
-----------
Press S on most screens to skip the current screen/block/VAS during pilot runs.
Skip events are written to markers and CSV so pilot data can be identified.

Before running
--------------
    pip install psychopy pylsl

If pylsl is unavailable, the experiment still runs and prints markers locally.
"""

from __future__ import annotations

import csv
import math
import os
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from psychopy import core, event, visual

try:
    from pylsl import StreamInfo, StreamOutlet
except Exception:
    StreamInfo = None
    StreamOutlet = None

# ---- GUI Integration ----
# When enabled, the experiment sends TCP commands to the OpenBCI GUI to
# automatically start/stop data recording at each stage boundary with
# file names like "SUB01-eyes_open-RAW.txt".
GUI_CONTROL_ENABLED = True
GUI_CONTROL_HOST = "127.0.0.1"
GUI_CONTROL_PORT = 1236

if GUI_CONTROL_ENABLED:
    try:
        from gui_controller import GUIController
    except ImportError:
        try:
            from mist.gui_controller import GUIController
        except ImportError:
            GUIController = None
            GUI_CONTROL_ENABLED = False
            print("GUI control disabled: gui_controller.py not found")


# ================================ Settings ================================ #


FULLSCREEN = True
WINDOW_SIZE = (1280, 720)

BACKGROUND = "#f4f7fb"
TEXT = "#172033"
MUTED = "#5f6b7a"
BLUE = "#1f6feb"
RED = "#c73535"
GREEN = "#248a3d"
DARK = "#101827"
CARD = "#ffffff"

SKIP_KEY = "s"

import platform as _platform
_SYSTEM = _platform.system()  # "Darwin" = macOS, "Windows" = Windows

# ---- Platform-adaptive text sizing ----
# macOS system font (PingFang SC) renders ~22% taller than Windows fonts at the
# same nominal height, causing line overlap on multi-line text.
_MAC_HEIGHT_SCALE = 0.82

def _h(h: float) -> float:
    """Return a platform-appropriate text height."""
    return round(h * _MAC_HEIGHT_SCALE, 3) if _SYSTEM == "Darwin" else h


@dataclass
class ExperimentConfig:
    data_dir: Path = Path.home() / "Desktop" / "MIST_data"

    # All formal stages are now 3 minutes.
    eyes_open_sec: float = 180.0
    eyes_closed_sec: float = 180.0
    practice_sec: float = 180.0
    control_sec: float = 180.0
    stress_sec: float = 180.0
    recovery_sec: float = 180.0

    fixation_sec: float = 0.35
    feedback_sec: float = 0.85
    iti_min: float = 0.25
    iti_max: float = 0.55

    practice_deadline: float = 8.0
    control_deadline: float = 10.0
    stress_deadline_start: float = 3.2
    stress_deadline_min: float = 1.1
    stress_deadline_max: float = 4.5

    # Stress pressure settings. The actual target is derived after the control
    # block: target = control accuracy + 15%, clamped to this range.
    stress_target_boost: int = 15
    stress_target_min: int = 75
    stress_target_max: int = 95
    peer_boost: int = 8
    target_success_rate: float = 0.55

    # Hide numerical per-trial countdown; participants see only a shrinking bar.
    show_deadline_seconds: bool = False

    def stage_duration(self, stage: str) -> float:
        return {
            "eyes_open": self.eyes_open_sec,
            "eyes_closed": self.eyes_closed_sec,
            "practice": self.practice_sec,
            "control": self.control_sec,
            "stress": self.stress_sec,
            "recovery": self.recovery_sec,
        }[stage]


# ================================ Utilities ================================ #


class MarkerOutlet:
    """Small LSL wrapper. Falls back to console logging if pylsl is unavailable."""

    def __init__(self, subject_id: str):
        self.subject_id = subject_id
        self.outlet = None
        if StreamInfo is not None and StreamOutlet is not None:
            try:
                info = StreamInfo(
                    name="MIST_EEG_Markers",
                    type="Markers",
                    channel_count=1,
                    nominal_srate=0,
                    channel_format="string",
                    source_id=f"MIST_{subject_id}",
                )
                self.outlet = StreamOutlet(info)
                print("LSL marker stream created: MIST_EEG_Markers")
            except Exception as exc:
                print(f"LSL unavailable, using console markers only: {exc}")

    def push(self, marker: str) -> None:
        timestamp = core.getTime()
        text = f"{self.subject_id}|{marker}"
        if self.outlet is not None:
            self.outlet.push_sample([text])
        print(f"[MARKER {timestamp:.3f}] {text}")


def now_string() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def open_window() -> visual.Window:
    return visual.Window(
        size=WINDOW_SIZE,
        fullscr=FULLSCREEN,
        color=BACKGROUND,
        units="height",
        allowGUI=False,
    )


def normalize_key(key: Any) -> str:
    if isinstance(key, tuple):
        return str(key[0])
    return str(key)


def check_abort(keys: list[Any] | None = None) -> None:
    if keys is None:
        keys = event.getKeys()
    if "escape" in [normalize_key(key) for key in keys]:
        raise KeyboardInterrupt


def has_skip(keys: list[Any]) -> bool:
    return SKIP_KEY in [normalize_key(key) for key in keys]


def flip_and_mark(win: visual.Window, markers: MarkerOutlet, marker: str) -> float:
    timestamp = win.flip()
    markers.push(marker)
    return timestamp


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(math.ceil(seconds)))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def clamp(value: int, low: int, high: int) -> int:
    return min(max(value, low), high)


def write_csv_row(path: Path, fieldnames: list[str], row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow({name: row.get(name, "") for name in fieldnames})


# ============================== Input Screens ============================== #


def draw_input_screen(win: visual.Window, title: str, prompt: str, value: str, hint: str) -> None:
    visual.Rect(win, width=1.36, height=0.66, fillColor=CARD, lineColor="#d9e2ef", pos=(0, 0)).draw()
    visual.TextStim(win, text=title, pos=(0, 0.22), height=_h(0.042), color=TEXT, bold=True).draw()
    visual.TextStim(win, text=prompt, pos=(0, 0.1), height=_h(0.03), color=TEXT, wrapWidth=1.1).draw()
    visual.Rect(win, width=0.88, height=0.09, fillColor="#f8fafc", lineColor="#b9c5d4", pos=(0, -0.035)).draw()
    visual.TextStim(win, text=value or "_", pos=(0, -0.045), height=_h(0.038), color=BLUE, wrapWidth=0.82).draw()
    visual.TextStim(win, text=hint, pos=(0, -0.22), height=_h(0.023), color=MUTED, wrapWidth=1.1).draw()
    win.flip()


def key_to_text(key: str) -> str:
    if len(key) == 1:
        return key
    digit_keys = {f"num_{i}": str(i) for i in range(10)}
    return digit_keys.get(key, "")


def get_text_input(
    win: visual.Window,
    prompt: str,
    default: str = "",
    allowed: str = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-",
) -> str:
    value = default
    event.clearEvents()
    while True:
        draw_input_screen(
            win,
            title="被试信息输入",
            prompt=prompt,
            value=value,
            hint="输入后按 Enter 确认；Backspace 删除；ESC 退出",
        )
        keys = event.waitKeys()
        check_abort(keys)
        for key in keys:
            if key in ("return", "num_enter"):
                return value.strip()
            if key == "backspace":
                value = value[:-1]
            elif key == "space":
                value += " "
            else:
                char = key_to_text(key)
                if char and char in allowed:
                    value += char


def get_choice_input(win: visual.Window, prompt: str, choices: list[str]) -> str:
    event.clearEvents()
    while True:
        body = [prompt, ""]
        for i, choice in enumerate(choices, start=1):
            body.append(f"{i}. {choice}")
        body.append("")
        body.append("按数字键选择；ESC 退出")
        draw_page(win, "被试信息输入", "\n".join(body), footer="")
        keys = event.waitKeys()
        check_abort(keys)
        for key in keys:
            if key.startswith("num_"):
                key = key[-1]
            if key.isdigit():
                index = int(key) - 1
                if 0 <= index < len(choices):
                    return choices[index]


def get_subject_info(win: visual.Window) -> dict[str, str]:
    """Collect subject information inside the PsychoPy window, avoiding Qt GUI."""
    subject_id = get_text_input(win, "Subject ID / 被试编号", default="TEST")
    session = get_text_input(win, "Session / 实验次数", default="01", allowed="0123456789")
    age = get_text_input(win, "Age / 年龄", default="", allowed="0123456789")
    sex = get_choice_input(win, "Sex / 性别", ["female", "male", "other", "prefer_not_to_say"])
    handedness = get_choice_input(win, "Handedness / 利手", ["right", "left", "ambidextrous"])
    operator = get_text_input(win, "Operator / 主试编号", default="")

    return {
        "subject_id": subject_id or "TEST",
        "session": session or "01",
        "age": age,
        "sex": sex,
        "handedness": handedness,
        "operator": operator,
    }


# ============================= Visual Building ============================ #


def draw_skip_hint(win: visual.Window) -> None:
    visual.Rect(win, width=0.26, height=0.055, fillColor="#fff4e6", lineColor="#f0b66a", pos=(0.62, -0.405)).draw()
    visual.TextStim(win, text="S 跳过", pos=(0.62, -0.413), height=_h(0.022), color="#9a5b00", bold=True).draw()


def draw_page(
    win: visual.Window,
    title: str,
    body: str,
    footer: str = "按空格键继续；按 S 跳过",
    accent: str = BLUE,
) -> None:
    visual.Rect(win, width=1.42, height=0.82, fillColor=CARD, lineColor="#d9e2ef", pos=(0, 0)).draw()
    visual.Rect(win, width=1.42, height=0.07, fillColor=accent, lineColor=accent, pos=(0, 0.375)).draw()
    visual.TextStim(win, text=title, pos=(0, 0.22), height=_h(0.046), color=TEXT, bold=True, wrapWidth=1.18).draw()
    visual.TextStim(
        win,
        text=body,
        pos=(0, 0.025),
        height=_h(0.028),
        color=TEXT,
        wrapWidth=1.18,
        alignText="center",
        ).draw()
    visual.TextStim(win, text=footer, pos=(0, -0.32), height=_h(0.024), color=MUTED, wrapWidth=1.18).draw()
    draw_skip_hint(win)
    win.flip()


def wait_for_space_or_skip() -> bool:
    """Return True when the screen was skipped."""
    event.clearEvents()
    while True:
        keys = event.waitKeys(keyList=["space", "escape", SKIP_KEY])
        check_abort(keys)
        if has_skip(keys):
            return True
        if "space" in keys:
            return False


def draw_header(win: visual.Window, stage_name: str, remaining: float, progress: float) -> None:
    progress = min(max(progress, 0.0), 1.0)
    visual.Rect(win, width=1.55, height=0.11, fillColor=CARD, lineColor="#d9e2ef", pos=(0, 0.405)).draw()
    visual.TextStim(
        win,
        text=stage_name,
        pos=(-0.62, 0.412),
        height=_h(0.027),
        color=TEXT,
        bold=True,
        alignText="left",
        ).draw()
    visual.TextStim(win, text=fmt_time(remaining), pos=(0.63, 0.412), height=_h(0.027), color=MUTED).draw()
    visual.Rect(win, width=1.24, height=0.012, fillColor="#e4ebf5", lineColor="#e4ebf5", pos=(0, 0.365)).draw()
    visual.Rect(
        win,
        width=1.24 * progress,
        height=0.012,
        fillColor=BLUE,
        lineColor=BLUE,
        pos=(-0.62 + 0.62 * progress, 0.365),
    ).draw()
    draw_skip_hint(win)


def draw_rest_screen(
    win: visual.Window,
    title: str,
    instruction: str,
    remaining: float,
    progress: float,
    show_fixation: bool = False,
) -> None:
    draw_header(win, title, remaining, progress)
    if show_fixation:
        visual.TextStim(win, text="+", pos=(0, 0.045), height=_h(0.105), color=DARK, bold=True).draw()
        visual.TextStim(win, text=instruction, pos=(0, -0.105), height=_h(0.034), color=TEXT, wrapWidth=1.2).draw()
        visual.TextStim(win, text=fmt_time(remaining), pos=(0, -0.215), height=_h(0.052), color=BLUE, bold=True).draw()
    else:
        visual.TextStim(win, text=instruction, pos=(0, 0.06), height=_h(0.047), color=TEXT, wrapWidth=1.2).draw()
        visual.TextStim(win, text=fmt_time(remaining), pos=(0, -0.09), height=_h(0.08), color=BLUE, bold=True).draw()
    visual.TextStim(win, text="请尽量减少眨眼和身体移动", pos=(0, -0.25), height=_h(0.026), color=MUTED).draw()


def draw_math_screen(
    win: visual.Window,
    stage_label: str,
    expression: str,
    typed_answer: str,
    remaining: float,
    progress: float,
    deadline_left: float,
    deadline_total: float,
    condition: str,
    current_perf: float | None,
    peer_average: int,
    target: int,
    show_deadline_seconds: bool,
) -> None:
    draw_header(win, stage_label, remaining, progress)

    if condition == "stress":
        x_positions = [-0.42, 0.0, 0.42]
        labels = [
            ("当前表现", f"{current_perf or 0:.0f}%", BLUE),
            ("同伴平均", f"{peer_average}%", RED),
            ("目标表现", f"{target}%", RED),
        ]
        for x, (label, value, color) in zip(x_positions, labels):
            visual.Rect(win, width=0.34, height=0.12, fillColor=CARD, lineColor="#d9e2ef", pos=(x, 0.245)).draw()
            visual.TextStim(win, text=label, pos=(x, 0.272), height=_h(0.02), color=MUTED).draw()
            visual.TextStim(win, text=value, pos=(x, 0.222), height=_h(0.035), color=color, bold=True).draw()
    else:
        visual.TextStim(
            win,
            text="请计算结果并按 Enter 提交。本阶段反馈为中性，不显示同伴比较。",
            pos=(0, 0.24),
            height=_h(0.025),
            color=MUTED,
            ).draw()

    visual.Rect(win, width=1.05, height=0.28, fillColor=CARD, lineColor="#d9e2ef", pos=(0, 0.02)).draw()
    visual.TextStim(win, text=f"{expression} = ?", pos=(0, 0.085), height=_h(0.07), color=DARK, bold=True).draw()
    visual.Rect(win, width=0.56, height=0.07, fillColor="#f8fafc", lineColor="#b9c5d4", pos=(0, -0.035)).draw()
    visual.TextStim(win, text=typed_answer or "_", pos=(0, -0.045), height=_h(0.042), color=BLUE, bold=True).draw()
    visual.TextStim(win, text="输入数字后按 Enter；Backspace 删除", pos=(0, -0.13), height=_h(0.026), color=TEXT).draw()

    bar_width = 0.7
    deadline_progress = max(0, min(deadline_left / max(deadline_total, 0.001), 1))
    visual.Rect(win, width=bar_width, height=0.018, fillColor="#e4ebf5", lineColor="#e4ebf5", pos=(0, -0.24)).draw()
    color = RED if condition == "stress" and deadline_left < 1.0 else BLUE
    visual.Rect(
        win,
        width=bar_width * deadline_progress,
        height=0.018,
        fillColor=color,
        lineColor=color,
        pos=(-bar_width / 2 + bar_width * deadline_progress / 2, -0.24),
    ).draw()
    deadline_text = f"作答剩余 {deadline_left:.1f} s" if show_deadline_seconds else "请在进度条结束前作答"
    visual.TextStim(win, text=deadline_text, pos=(0, -0.285), height=_h(0.024), color=MUTED).draw()


def draw_feedback(win: visual.Window, text: str, color: str, detail: str = "") -> None:
    visual.Rect(win, width=1.1, height=0.36, fillColor=CARD, lineColor="#d9e2ef", pos=(0, 0.02)).draw()
    visual.TextStim(win, text=text, pos=(0, 0.08), height=_h(0.052), color=color, bold=True, wrapWidth=1.0).draw()
    if detail:
        visual.TextStim(win, text=detail, pos=(0, -0.04), height=_h(0.028), color=MUTED, wrapWidth=1.0).draw()
    draw_skip_hint(win)


# ================================ Task Logic ============================== #


def generate_problem(condition: str) -> dict[str, Any]:
    """Create one arithmetic fill-in problem."""
    if condition == "practice":
        a = random.randint(2, 12)
        b = random.randint(2, 12)
        op = random.choice(["+", "-"])
    elif condition == "control":
        a = random.randint(6, 24)
        b = random.randint(2, 18)
        op = random.choice(["+", "-", "*"])
    else:
        a = random.randint(12, 48)
        b = random.randint(3, 19)
        op = random.choice(["+", "-", "*"])

    true_value = a + b if op == "+" else a - b if op == "-" else a * b
    return {
        "expression": f"{a} {op} {b}",
        "a": a,
        "b": b,
        "operator": op,
        "true_value": true_value,
        "correct_answer": str(true_value),
    }


def update_stress_deadline(deadline: float, recent_correct: list[bool], config: ExperimentConfig) -> float:
    if len(recent_correct) < 5:
        return deadline
    recent_rate = sum(recent_correct[-8:]) / len(recent_correct[-8:])
    if recent_rate > config.target_success_rate:
        deadline -= 0.18
    else:
        deadline += 0.12
    return min(max(deadline, config.stress_deadline_min), config.stress_deadline_max)


def estimate_stress_deadline(control_rts: list[float], config: ExperimentConfig) -> float:
    """Use control performance to initialize a participant-specific stress deadline."""
    if len(control_rts) < 3:
        return config.stress_deadline_start
    median_rt = sorted(control_rts)[len(control_rts) // 2]
    deadline = median_rt * 0.85
    return min(max(deadline, config.stress_deadline_min), config.stress_deadline_max)


def derive_stress_targets(control_accuracy: float, config: ExperimentConfig) -> tuple[int, int]:
    """Return displayed peer average and target accuracy based on control performance."""
    control_percent = round(control_accuracy * 100)
    target = clamp(control_percent + config.stress_target_boost, config.stress_target_min, config.stress_target_max)
    peer_average = clamp(control_percent + config.peer_boost, 70, max(70, target - 2))
    return peer_average, target


def run_rest_block(
    win: visual.Window,
    markers: MarkerOutlet,
    config: ExperimentConfig,
    log_path: Path,
    fieldnames: list[str],
    stage: str,
    title: str,
    instruction: str,
) -> dict[str, Any]:
    win.mouseVisible = False
    duration = config.stage_duration(stage)
    draw_page(win, title, f"{instruction}\n\n本阶段时长：{fmt_time(duration)}", accent=BLUE)
    if wait_for_space_or_skip():
        markers.push(f"BLOCK_SKIP/{stage}/before_start")
        write_csv_row(log_path, fieldnames, {"row_type": "block", "stage": stage, "condition": stage, "event": "skip_before_start"})
        return {"skipped": True}

    markers.push(f"BLOCK_START/{stage}")
    clock = core.Clock()
    skipped = False
    while clock.getTime() < duration:
        remaining = duration - clock.getTime()
        draw_rest_screen(
            win,
            title,
            instruction,
            remaining,
            clock.getTime() / duration,
            show_fixation=stage == "eyes_open",
        )
        win.flip()
        keys = event.getKeys(keyList=["escape", SKIP_KEY])
        check_abort(keys)
        if has_skip(keys):
            skipped = True
            markers.push(f"BLOCK_SKIP/{stage}/during_block")
            break

    markers.push(f"BLOCK_END/{stage}")
    write_csv_row(
        log_path,
        fieldnames,
        {
            "row_type": "block",
            "stage": stage,
            "condition": stage,
            "event": "block_end_skipped" if skipped else "block_end",
            "time_global": core.getTime(),
            "duration": clock.getTime(),
            "skipped": skipped,
        },
    )
    return {"skipped": skipped}


def run_vas(
    win: visual.Window,
    markers: MarkerOutlet,
    log_path: Path,
    fieldnames: list[str],
    after_stage: str,
) -> dict[str, Any]:
    previous_mouse_visibility = win.mouseVisible
    win.mouseVisible = True
    markers.push(f"VAS_START/after_{after_stage}")
    mouse = event.Mouse(win=win)
    rating_clock = core.Clock()
    rating = None
    skipped = False
    bar_left = -0.48
    bar_right = 0.48
    bar_y = -0.055

    event.clearEvents()
    while True:
        visual.Rect(win, width=1.32, height=0.62, fillColor=CARD, lineColor="#d9e2ef", pos=(0, 0)).draw()
        visual.TextStim(
            win,
            text="请评价你此刻的主观焦虑 / 压力水平",
            pos=(0, 0.18),
            height=_h(0.04),
            color=TEXT,
            bold=True,
            ).draw()
        visual.TextStim(win, text="0", pos=(bar_left, 0.035), height=_h(0.028), color=TEXT, bold=True).draw()
        visual.TextStim(win, text="100", pos=(bar_right, 0.035), height=_h(0.028), color=TEXT, bold=True).draw()
        visual.TextStim(win, text="完全没有", pos=(bar_left, -0.135), height=_h(0.026), color=TEXT).draw()
        visual.TextStim(win, text="非常强烈", pos=(bar_right, -0.135), height=_h(0.026), color=TEXT).draw()
        visual.Line(win, start=(bar_left, bar_y), end=(bar_right, bar_y), lineColor="#9aa8ba", lineWidth=8).draw()

        for tick in range(0, 101, 10):
            x = bar_left + (bar_right - bar_left) * tick / 100
            tick_height = 0.04 if tick in (0, 50, 100) else 0.026
            visual.Line(
                win,
                start=(x, bar_y - tick_height / 2),
                end=(x, bar_y + tick_height / 2),
                lineColor="#6b7788",
                lineWidth=2,
            ).draw()

        if rating is not None:
            marker_x = bar_left + (bar_right - bar_left) * rating / 100
            visual.Circle(win, radius=0.023, pos=(marker_x, bar_y), fillColor=BLUE, lineColor=BLUE).draw()
            visual.TextStim(win, text=f"{rating:.0f}", pos=(0, -0.005), height=_h(0.038), color=BLUE, bold=True).draw()
        else:
            visual.TextStim(win, text="请点击横线选择评分", pos=(0, -0.005), height=_h(0.03), color=MUTED).draw()

        visual.TextStim(
            win,
            text="用鼠标点击横线选择 0-100；按空格确认；按 S 跳过",
            pos=(0, -0.22),
            height=_h(0.025),
            color=MUTED,
            ).draw()
        draw_skip_hint(win)
        win.flip()

        if mouse.getPressed()[0]:
            x, y = mouse.getPos()
            if bar_left <= x <= bar_right and abs(y - bar_y) <= 0.09:
                rating = round((x - bar_left) / (bar_right - bar_left) * 100)
                rating = min(max(rating, 0), 100)
                core.wait(0.15)

        keys = event.getKeys(keyList=["space", "escape", SKIP_KEY])
        check_abort(keys)
        if has_skip(keys):
            skipped = True
            markers.push(f"VAS_SKIP/after_{after_stage}")
            break
        if "space" in keys and rating is not None:
            break

    if not skipped:
        markers.push(f"VAS_END/after_{after_stage}/rating_{rating}")
    win.mouseVisible = previous_mouse_visibility
    write_csv_row(
        log_path,
        fieldnames,
        {
            "row_type": "vas",
            "stage": after_stage,
            "condition": after_stage,
            "event": "vas_skipped" if skipped else "vas",
            "time_global": core.getTime(),
            "vas_rating": "" if skipped else rating,
            "rt": rating_clock.getTime(),
            "skipped": skipped,
        },
    )
    return {"skipped": skipped, "rating": rating}


def run_math_block(
    win: visual.Window,
    markers: MarkerOutlet,
    config: ExperimentConfig,
    log_path: Path,
    fieldnames: list[str],
    condition: str,
    title: str,
    initial_deadline: float | None = None,
    peer_average: int = 78,
    stress_target: int = 85,
) -> dict[str, Any]:
    win.mouseVisible = False
    duration = config.stage_duration(condition)
    if condition == "practice":
        deadline = config.practice_deadline
        intro = "练习阶段：请尽快且准确地计算结果。\n输入数字后按 Enter 提交。"
    elif condition == "control":
        deadline = config.control_deadline
        intro = "Control Math：请计算每道题的结果。\n本阶段反馈为中性，不显示同伴比较。"
    else:
        deadline = initial_deadline or config.stress_deadline_start
        intro = (
            "Stress Math：请尽快且准确地作答。\n"
            "屏幕会显示当前表现、同伴平均表现和目标表现。\n"
            "错误或超时会出现负性反馈。"
        )

    draw_page(win, title, f"{intro}\n\n本阶段时长：{fmt_time(duration)}", accent=RED if condition == "stress" else BLUE)
    if wait_for_space_or_skip():
        markers.push(f"BLOCK_SKIP/{condition}/before_start")
        write_csv_row(
            log_path,
            fieldnames,
            {"row_type": "block", "stage": condition, "condition": condition, "event": "skip_before_start", "skipped": True},
        )
        return {"skipped": True, "n_trials": 0, "accuracy": 0.0, "correct_rts": [], "final_deadline": deadline}

    markers.push(f"BLOCK_START/{condition}")
    block_clock = core.Clock()
    trial_index = 0
    correct_history: list[bool] = []
    valid_correct_rts: list[float] = []
    skipped = False

    while block_clock.getTime() < duration:
        trial_index += 1
        problem = generate_problem(condition)

        draw_header(win, title, duration - block_clock.getTime(), block_clock.getTime() / duration)
        visual.TextStim(win, text="+", pos=(0, 0), height=_h(0.07), color=MUTED).draw()
        win.flip()
        core.wait(config.fixation_sec)

        event.clearEvents()
        trial_clock = core.Clock()
        response = ""
        response_time = ""
        rt: float | str = ""
        timeout = False
        trial_skipped = False
        current_perf = 100 * sum(correct_history) / len(correct_history) if correct_history else 0.0

        draw_math_screen(
            win,
            title,
            problem["expression"],
            response,
            duration - block_clock.getTime(),
            block_clock.getTime() / duration,
            deadline,
            deadline,
            condition,
            current_perf,
            peer_average,
            stress_target,
            config.show_deadline_seconds,
        )
        problem_onset = flip_and_mark(
            win,
            markers,
            f"PROBLEM_ONSET/{condition}/trial_{trial_index}/{problem['expression']}=?",
        )
        trial_clock.reset()

        while trial_clock.getTime() < deadline:
            deadline_left = deadline - trial_clock.getTime()
            draw_math_screen(
                win,
                title,
                problem["expression"],
                response,
                duration - block_clock.getTime(),
                block_clock.getTime() / duration,
                deadline_left,
                deadline,
                condition,
                current_perf,
                peer_average,
                stress_target,
                config.show_deadline_seconds,
            )
            win.flip()
            keys = event.getKeys(
                keyList=[
                    "0",
                    "1",
                    "2",
                    "3",
                    "4",
                    "5",
                    "6",
                    "7",
                    "8",
                    "9",
                    "num_0",
                    "num_1",
                    "num_2",
                    "num_3",
                    "num_4",
                    "num_5",
                    "num_6",
                    "num_7",
                    "num_8",
                    "num_9",
                    "minus",
                    "backspace",
                    "return",
                    "num_enter",
                    "escape",
                    SKIP_KEY,
                ],
                timeStamped=trial_clock,
            )
            check_abort(keys)
            if not keys:
                continue

            for key, key_time in keys:
                if key == SKIP_KEY:
                    trial_skipped = True
                    skipped = True
                    markers.push(f"TRIAL_SKIP/{condition}/trial_{trial_index}")
                    break
                if key == "backspace":
                    response = response[:-1]
                elif key == "minus" and not response:
                    response = "-"
                elif key in ("return", "num_enter"):
                    if response not in ("", "-"):
                        rt = float(key_time)
                        response_time = core.getTime()
                        markers.push(f"RESPONSE/{condition}/trial_{trial_index}/{response}/rt_{rt:.3f}")
                        break
                else:
                    char = key_to_text(key)
                    if char.isdigit():
                        response += char
            if trial_skipped or isinstance(rt, float):
                break

        if trial_skipped:
            break

        if not response or not isinstance(rt, float):
            timeout = True
            markers.push(f"TIMEOUT/{condition}/trial_{trial_index}")

        is_correct = bool(response == problem["correct_answer"]) and not timeout
        correct_history.append(is_correct)
        if is_correct and isinstance(rt, float):
            valid_correct_rts.append(rt)

        deadline_used = deadline
        if condition == "stress":
            if timeout:
                feedback_text = "太慢了"
                feedback_detail = "你的反应速度低于目标表现"
                feedback_color = RED
                feedback_type = "negative_timeout"
            elif not is_correct:
                feedback_text = "错误"
                feedback_detail = "你的准确率低于目标表现"
                feedback_color = RED
                feedback_type = "negative_error"
            else:
                feedback_text = "正确"
                feedback_detail = "请继续保持速度"
                feedback_color = GREEN
                feedback_type = "positive"
            deadline = update_stress_deadline(deadline, correct_history, config)
        elif condition == "control":
            feedback_text = "已记录"
            feedback_detail = "请继续下一题"
            feedback_color = BLUE
            feedback_type = "neutral"
        else:
            feedback_text = "正确" if is_correct else "错误或超时"
            feedback_detail = "练习反馈"
            feedback_color = GREEN if is_correct else RED
            feedback_type = "practice_correct" if is_correct else "practice_incorrect"

        draw_feedback(win, feedback_text, feedback_color, feedback_detail)
        feedback_onset = flip_and_mark(win, markers, f"FEEDBACK_ONSET/{condition}/trial_{trial_index}/{feedback_type}")
        core.wait(config.feedback_sec)

        write_csv_row(
            log_path,
            fieldnames,
            {
                "row_type": "trial",
                "stage": condition,
                "condition": condition,
                "trial_index": trial_index,
                "problem": f"{problem['expression']} = ?",
                "a": problem["a"],
                "b": problem["b"],
                "operator": problem["operator"],
                "true_value": problem["true_value"],
                "shown_value": "",
                "equation_is_true": "",
                "correct_key": problem["correct_answer"],
                "response": response,
                "rt": rt,
                "correct": is_correct,
                "timeout": timeout,
                "deadline": deadline_used,
                "feedback_type": feedback_type,
                "problem_onset": problem_onset,
                "response_time": response_time,
                "feedback_onset": feedback_onset,
                "time_global": core.getTime(),
                "current_performance": current_perf,
                "peer_average": peer_average if condition == "stress" else "",
                "target_performance": stress_target if condition == "stress" else "",
                "skipped": False,
            },
        )

        core.wait(random.uniform(config.iti_min, config.iti_max))
        keys = event.getKeys(keyList=["escape", SKIP_KEY])
        check_abort(keys)
        if has_skip(keys):
            skipped = True
            markers.push(f"BLOCK_SKIP/{condition}/during_iti")
            break

    markers.push(f"BLOCK_END/{condition}")
    accuracy = sum(correct_history) / len(correct_history) if correct_history else 0.0
    write_csv_row(
        log_path,
        fieldnames,
        {
            "row_type": "block",
            "stage": condition,
            "condition": condition,
            "event": "block_end_skipped" if skipped else "block_end",
            "duration": block_clock.getTime(),
            "current_performance": accuracy * 100,
            "skipped": skipped,
        },
    )
    return {
        "skipped": skipped,
        "n_trials": len(correct_history),
        "accuracy": accuracy,
        "correct_rts": valid_correct_rts,
        "final_deadline": deadline,
    }


# ================================== Main ================================== #


FIELDNAMES = [
    "row_type",
    "stage",
    "condition",
    "event",
    "trial_index",
    "problem",
    "a",
    "b",
    "operator",
    "true_value",
    "shown_value",
    "equation_is_true",
    "correct_key",
    "response",
    "rt",
    "correct",
    "timeout",
    "deadline",
    "feedback_type",
    "problem_onset",
    "response_time",
    "feedback_onset",
    "time_global",
    "duration",
    "vas_rating",
    "current_performance",
    "peer_average",
    "target_performance",
    "condition_order",
    "practice_accuracy",
    "control_accuracy",
    "stress_initial_deadline",
    "skipped",
]


def log_experiment_event(
    log_path: Path,
    event_name: str,
    condition: str = "experiment",
    extra: dict[str, Any] | None = None,
) -> None:
    row = {
        "row_type": "experiment",
        "event": event_name,
        "time_global": core.getTime(),
        "condition": condition,
    }
    if extra:
        row.update(extra)
    write_csv_row(log_path, FIELDNAMES, row)


def main() -> None:
    random.seed()
    config = ExperimentConfig()
    win = open_window()
    subject = get_subject_info(win)
    subject_id = subject["subject_id"]
    condition_order = ["control", "stress"]

    # ---- Initialize GUI Controller ----
    gui: Any = None
    if GUI_CONTROL_ENABLED and GUIController is not None:
        gui = GUIController(GUI_CONTROL_HOST, GUI_CONTROL_PORT)
        if gui.connect():
            print(f"GUI integration active — recordings will be auto-managed for subject {subject_id}")
        else:
            print("WARNING: Could not connect to OpenBCI GUI. Recording will NOT be automatic.")
            print("  Make sure the GUI is running and a session has been started.")
            gui = None

    def gui_start_stage(stage_name: str) -> None:
        """Start recording for a stage, silently ignore if GUI is not available."""
        if gui is not None:
            try:
                gui.start_stage(subject_id, stage_name)
            except Exception as exc:
                print(f"GUI start_stage({stage_name}) failed: {exc}")

    def gui_stop() -> None:
        """Stop recording, silently ignore if GUI is not available."""
        if gui is not None:
            try:
                gui.stop()
            except Exception as exc:
                print(f"GUI stop failed: {exc}")

    config.data_dir.mkdir(parents=True, exist_ok=True)
    log_path = config.data_dir / f"MIST_{subject_id}_ses-{subject['session']}_{now_string()}.csv"
    markers = MarkerOutlet(subject_id)

    try:
        markers.push("EXPERIMENT_START")
        log_experiment_event(
            log_path,
            "experiment_start",
            extra={
                "condition_order": "->".join(condition_order),
            },
        )

        draw_page(
            win,
            "Modified MIST EEG 实验",
            (
                "接下来你将完成静息和算术填空任务。\n\n"
                "算术题中，请输入计算结果并按 Enter 提交。\n"
                "请在保持头部和身体稳定的情况下尽快准确作答。\n\n"
                "如果需要紧急停止，请按 ESC。流程测试时可按 S 跳过当前部分。"
            ),
        )
        wait_for_space_or_skip()

        gui_start_stage("eyes_open")
        run_rest_block(
            win,
            markers,
            config,
            log_path,
            FIELDNAMES,
            stage="eyes_open",
            title="睁眼静息",
            instruction="请睁眼注视屏幕中央，保持放松。",
        )
        gui_stop()
        run_vas(win, markers, log_path, FIELDNAMES, after_stage="eyes_open")

        gui_start_stage("eyes_closed")
        run_rest_block(
            win,
            markers,
            config,
            log_path,
            FIELDNAMES,
            stage="eyes_closed",
            title="闭眼静息",
            instruction="请闭上眼睛，保持清醒和放松。听到提示后再睁眼。",
        )
        gui_stop()
        run_vas(win, markers, log_path, FIELDNAMES, after_stage="eyes_closed")

        gui_start_stage("practice")
        practice_summary = run_math_block(
            win,
            markers,
            config,
            log_path,
            FIELDNAMES,
            condition="practice",
            title="练习阶段",
        )
        gui_stop()
        run_vas(win, markers, log_path, FIELDNAMES, after_stage="practice")

        gui_start_stage("control")
        control_summary = run_math_block(
            win,
            markers,
            config,
            log_path,
            FIELDNAMES,
            condition="control",
            title="Control Math",
        )
        gui_stop()
        run_vas(win, markers, log_path, FIELDNAMES, after_stage="control")

        peer_average, stress_target = derive_stress_targets(control_summary["accuracy"], config)
        stress_initial_deadline = estimate_stress_deadline(control_summary["correct_rts"], config)
        log_experiment_event(
            log_path,
            "control_summary",
            extra={
                "practice_accuracy": practice_summary["accuracy"],
                "control_accuracy": control_summary["accuracy"],
                "stress_initial_deadline": stress_initial_deadline,
                "peer_average": peer_average,
                "target_performance": stress_target,
            },
        )

        gui_start_stage("stress")
        run_math_block(
            win,
            markers,
            config,
            log_path,
            FIELDNAMES,
            condition="stress",
            title="Stress Math",
            initial_deadline=stress_initial_deadline,
            peer_average=peer_average,
            stress_target=stress_target,
        )
        gui_stop()
        run_vas(win, markers, log_path, FIELDNAMES, after_stage="stress")

        gui_start_stage("recovery")
        run_rest_block(
            win,
            markers,
            config,
            log_path,
            FIELDNAMES,
            stage="recovery",
            title="Recovery",
            instruction="请安静休息，尽量放松。",
        )
        gui_stop()
        run_vas(win, markers, log_path, FIELDNAMES, after_stage="recovery")

        markers.push("EXPERIMENT_END")
        log_experiment_event(log_path, "experiment_end")
        draw_page(
            win,
            "实验结束",
            (
                "感谢你的参与。\n\n"
                "本实验中的同伴平均表现和目标表现用于构造任务情境，"
                "并不代表对你个人能力的真实评价。\n\n"
                f"行为数据已保存至：\n{log_path}"
            ),
            footer="按空格键退出",
            accent=GREEN,
        )
        wait_for_space_or_skip()

    except KeyboardInterrupt:
        markers.push("EXPERIMENT_ABORTED")
        log_experiment_event(log_path, "experiment_aborted")
        draw_page(win, "实验已中止", f"已保存当前日志：\n{log_path}", footer="按空格键退出", accent=RED)
        wait_for_space_or_skip()
    finally:
        if gui is not None:
            try:
                gui.stop()
                gui.disconnect()
            except Exception:
                pass
        win.close()
        core.quit()


if __name__ == "__main__":
    os.chdir(str(Path.home()))
    main()
