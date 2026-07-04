#!/usr/bin/env python3
"""Send simulated ADS129X vendor TCP frames to the modified OpenBCI GUI."""

from __future__ import annotations

import argparse
import math
import socket
import struct
import time
from typing import Iterable, List


FRAME_HEAD = b"\xA5\xA5"
FRAME_TAIL = b"\x5A\x5A"
CHANNEL_MASK_16 = 0x10

SAMPLE_RATE_CODE = {
    250: 7,
    500: 6,
    1000: 5,
}

GAIN_CODE = {
    24: 0,
    12: 1,
    8: 2,
    6: 3,
    4: 4,
    3: 5,
    2: 6,
    1: 7,
}


def int24be(value: int) -> bytes:
    if value < 0:
        value += 1 << 24
    return value.to_bytes(3, "big", signed=False)


def build_frame(
    sequence: int,
    samples: Iterable[List[int]],
    *,
    sample_rate: int,
    gain: int,
    battery: int = 100,
    lead_status: int = 0,
    corrupt_checksum: bool = False,
) -> bytes:
    payload = bytearray()
    for sample in samples:
        if len(sample) != 16:
            raise ValueError("each sample must have 16 channels")
        for value in sample:
            payload.extend(int24be(value))

    header = bytearray()
    header.extend(FRAME_HEAD)
    header.append(0x01)  # device id
    header.append(0x05)  # EEG data frame
    header.extend(sequence.to_bytes(4, "big", signed=False))
    header.append(CHANNEL_MASK_16)  # ADS1299 + 16 channel mask
    header.append(100)  # signal strength
    header.append(battery & 0xFF)
    header.append((SAMPLE_RATE_CODE[sample_rate] << 4) | GAIN_CODE[gain])
    header.extend(lead_status.to_bytes(2, "big", signed=False))
    header.extend(len(payload).to_bytes(2, "big", signed=False))

    checksum = sum(header + payload) & 0xFFFF
    if corrupt_checksum:
        checksum ^= 0xFFFF
    return bytes(header + payload + checksum.to_bytes(2, "big") + FRAME_TAIL)


def make_samples(start_index: int, count: int, sample_rate: int, amplitude: int) -> List[List[int]]:
    samples: List[List[int]] = []
    for i in range(count):
        t = (start_index + i) / float(sample_rate)
        row = []
        for channel in range(16):
            freq = 8.0 + (channel % 4)
            phase = channel * 0.2
            row.append(int(amplitude * math.sin(2.0 * math.pi * freq * t + phase)))
        samples.append(row)
    return samples


def run_sender(args: argparse.Namespace) -> None:
    sequence = 0
    sent_samples = 0
    batch_samples = args.batch_samples
    end_time = time.monotonic() + args.duration if args.duration > 0 else None

    with socket.create_connection((args.host, args.port), timeout=5.0) as sock:
        print(f"connected to {args.host}:{args.port}")
        next_send = time.perf_counter()
        while end_time is None or time.monotonic() < end_time:
            samples = make_samples(sent_samples, batch_samples, args.rate, args.amplitude)
            corrupt = args.bad_checksum_every > 0 and sequence > 0 and sequence % args.bad_checksum_every == 0
            frame = build_frame(
                sequence,
                samples,
                sample_rate=args.rate,
                gain=args.gain,
                corrupt_checksum=corrupt,
            )
            sock.sendall(frame)
            sent_samples += batch_samples
            sequence += 1
            if args.sequence_gap_after >= 0 and sequence == args.sequence_gap_after:
                sequence += args.sequence_gap_size

            next_send += batch_samples / float(args.rate)
            sleep_for = next_send - time.perf_counter()
            if sleep_for > 0:
                time.sleep(sleep_for)
    print(f"sent {sent_samples} samples")


def self_test() -> None:
    frame = build_frame(1, [[0] * 16, [-1] * 16], sample_rate=250, gain=24)
    assert frame.startswith(FRAME_HEAD)
    assert frame.endswith(FRAME_TAIL)
    data_len = int.from_bytes(frame[14:16], "big")
    assert data_len == 16 * 3 * 2
    checksum = int.from_bytes(frame[16 + data_len : 18 + data_len], "big")
    assert checksum == (sum(frame[: 16 + data_len]) & 0xFFFF)
    print("ads129x fake sender self-test passed")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1234)
    parser.add_argument("--rate", type=int, choices=(250, 500, 1000), default=250)
    parser.add_argument("--gain", type=int, choices=(1, 2, 3, 4, 6, 8, 12, 24), default=24)
    parser.add_argument("--duration", type=float, default=30.0, help="seconds to send; <=0 sends until interrupted")
    parser.add_argument("--batch-samples", type=int, default=5)
    parser.add_argument("--amplitude", type=int, default=12000, help="raw ADC count amplitude")
    parser.add_argument("--bad-checksum-every", type=int, default=0, help="corrupt every Nth frame")
    parser.add_argument("--sequence-gap-after", type=int, default=-1, help="insert a sequence gap after this frame number")
    parser.add_argument("--sequence-gap-size", type=int, default=3)
    parser.add_argument("--self-test", action="store_true")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    run_sender(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
