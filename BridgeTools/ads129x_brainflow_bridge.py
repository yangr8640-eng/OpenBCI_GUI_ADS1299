#!/usr/bin/env python3
"""Bridge ADS129X packets to a BrainFlow Streaming Board multicast stream."""

from __future__ import annotations

import argparse
import logging
import math
import os
import signal
import socket
import struct
import sys
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence


FRAME_HEAD = b"\xA5\xA5"
FRAME_TAIL = b"\x5A\x5A"

SAMPLE_RATE_BY_CODE = {
    0: 32000,
    1: 16000,
    2: 8000,
    3: 4000,
    4: 2000,
    5: 1000,
    6: 500,
    7: 250,
}

GAIN_BY_CODE = {
    0: 24,
    1: 12,
    2: 8,
    3: 6,
    4: 4,
    5: 3,
    6: 2,
    7: 1,
}

CHANNELS_BY_MASK = {
    0x20: 32,
    0x10: 16,
    0x08: 8,
    0x04: 4,
    0x02: 2,
    0x01: 1,
}

CHIP_TYPE_BY_CODE = {
    0: "ADS1299",
    1: "ADS1298/ADS1292",
    2: "reserved",
    3: "reserved",
}

# Values from the vendor protocol document.
ADS1299_LSB_UV = 4_500_000.0 / ((1 << 23) - 1)
ADS1298_LSB_UV = 2_400_000.0 / ((1 << 23) - 1)

# BrainFlow Synthetic Board layout. OpenBCI GUI v5.2.x exposes this as a
# Streaming Board master board option and it has 16 EXG channels at 250 Hz.
SYNTHETIC_NUM_ROWS = 32
SYNTHETIC_PACKAGE_NUM_CHANNEL = 0
SYNTHETIC_EXG_START_CHANNEL = 1
SYNTHETIC_EXG_CHANNELS = 16
SYNTHETIC_BATTERY_CHANNEL = 29
SYNTHETIC_TIMESTAMP_CHANNEL = 30
SYNTHETIC_MARKER_CHANNEL = 31
SYNTHETIC_SAMPLING_RATE = 250


class BridgeStop(Exception):
    pass


@dataclass
class ADS129xFrame:
    device_id: int
    function: int
    sequence: int
    chip_type_code: int
    chip_type: str
    channel_count: int
    signal_strength: int
    battery: int
    sample_rate: Optional[int]
    gain: Optional[int]
    lead_status: int
    raw_samples: List[List[int]]

    @property
    def has_raw_samples(self) -> bool:
        return bool(self.raw_samples)

    @property
    def is_eeg_frame(self) -> bool:
        return self.function == 0x05 and bool(self.raw_samples)


class ADS129xParser:
    def __init__(self, *, strict_checksum: bool = True) -> None:
        self.buffer = bytearray()
        self.strict_checksum = strict_checksum
        self.frames = 0
        self.sample_frames = 0
        self.bad_tail = 0
        self.bad_checksum = 0
        self.bad_length = 0
        self.bytes_discarded = 0

    def feed(self, data: bytes) -> List[ADS129xFrame]:
        self.buffer.extend(data)
        frames: List[ADS129xFrame] = []

        while True:
            start = self.buffer.find(FRAME_HEAD)
            if start < 0:
                if self.buffer.endswith(FRAME_HEAD[:1]):
                    del self.buffer[:-1]
                else:
                    self.bytes_discarded += len(self.buffer)
                    self.buffer.clear()
                break

            if start:
                self.bytes_discarded += start
                del self.buffer[:start]

            if len(self.buffer) < 16:
                break

            data_len = int.from_bytes(self.buffer[14:16], byteorder="big", signed=False)
            total_len = 16 + data_len + 2 + 2
            if len(self.buffer) < total_len:
                break

            raw = bytes(self.buffer[:total_len])
            if raw[-2:] != FRAME_TAIL:
                self.bad_tail += 1
                del self.buffer[0]
                continue

            expected_checksum = int.from_bytes(raw[16 + data_len : 18 + data_len], "big")
            actual_checksum = sum(raw[: 16 + data_len]) & 0xFFFF
            if expected_checksum != actual_checksum:
                self.bad_checksum += 1
                del self.buffer[:total_len]
                if self.strict_checksum:
                    continue

            frame = self._parse_frame(raw, data_len)
            if frame is not None:
                self.frames += 1
                if frame.is_eeg_frame:
                    self.sample_frames += 1
                frames.append(frame)

            del self.buffer[:total_len]

        return frames

    def _parse_frame(self, raw: bytes, data_len: int) -> Optional[ADS129xFrame]:
        channel_byte = raw[8]
        chip_type_code = (channel_byte >> 6) & 0x03
        channel_count = CHANNELS_BY_MASK.get(channel_byte & 0x3F, channel_byte & 0x3F)
        if channel_count <= 0:
            self.bad_length += 1
            return None

        sample_rate_gain = raw[11]
        sample_rate = SAMPLE_RATE_BY_CODE.get((sample_rate_gain >> 4) & 0x0F)
        gain = GAIN_BY_CODE.get(sample_rate_gain & 0x0F)
        payload = raw[16 : 16 + data_len]
        raw_samples: List[List[int]] = []

        if raw[3] == 0x05:
            sample_width = 3 * channel_count
            if data_len % sample_width != 0:
                self.bad_length += 1
                return None
            for offset in range(0, data_len, sample_width):
                sample = []
                sample_bytes = payload[offset : offset + sample_width]
                for ch in range(channel_count):
                    sample.append(parse_int24_be(sample_bytes[ch * 3 : ch * 3 + 3]))
                raw_samples.append(sample)

        return ADS129xFrame(
            device_id=raw[2],
            function=raw[3],
            sequence=int.from_bytes(raw[4:8], "big", signed=False),
            chip_type_code=chip_type_code,
            chip_type=CHIP_TYPE_BY_CODE.get(chip_type_code, "unknown"),
            channel_count=channel_count,
            signal_strength=raw[9],
            battery=raw[10],
            sample_rate=sample_rate,
            gain=gain,
            lead_status=int.from_bytes(raw[12:14], "big", signed=False),
            raw_samples=raw_samples,
        )


def parse_int24_be(value: bytes) -> int:
    if len(value) != 3:
        raise ValueError("int24 values must contain exactly 3 bytes")
    result = int.from_bytes(value, byteorder="big", signed=False)
    if result & 0x800000:
        result -= 0x1000000
    return result


def adc_to_uv(raw: int, chip_type_code: int, gain: Optional[int]) -> float:
    lsb_uv = ADS1299_LSB_UV if chip_type_code == 0 else ADS1298_LSB_UV
    return raw * lsb_uv / (gain or 1)


class FractionalDownsampler:
    def __init__(self, target_rate: int) -> None:
        self.target_rate = target_rate
        self.source_rate: Optional[int] = None
        self.accumulator = 0.0

    def update_source_rate(self, source_rate: Optional[int]) -> None:
        if source_rate is None or source_rate <= 0:
            return
        if self.source_rate != source_rate:
            self.source_rate = source_rate
            self.accumulator = max(0.0, float(source_rate - self.target_rate))
            if source_rate != self.target_rate:
                logging.info(
                    "source sample rate %s Hz -> output %s Hz",
                    source_rate,
                    min(source_rate, self.target_rate),
                )

    def accept(self) -> bool:
        if self.source_rate is None:
            return True
        if self.source_rate <= self.target_rate:
            return True

        self.accumulator += self.target_rate
        if self.accumulator >= self.source_rate:
            self.accumulator -= self.source_rate
            return True
        return False


class BrainFlowSyntheticStreamer:
    def __init__(
        self,
        multicast_ip: str,
        multicast_port: int,
        *,
        batch_size: int,
        target_rate: int,
        ttl: int = 1,
        interface_ip: Optional[str] = None,
    ) -> None:
        self.multicast_ip = multicast_ip
        self.multicast_port = multicast_port
        self.batch_size = batch_size
        self.target_rate = target_rate
        self.package_num = 0
        self.pending: List[List[float]] = []
        self.sent_samples = 0
        self.sent_packets = 0
        self.first_timestamp: Optional[float] = None

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        if interface_ip:
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(interface_ip))

    def add_sample(
        self,
        values_uv: Sequence[float],
        *,
        battery: int = 0,
        timestamp: Optional[float] = None,
    ) -> None:
        if timestamp is None:
            if self.first_timestamp is None:
                self.first_timestamp = time.time()
            timestamp = self.first_timestamp + self.sent_samples / float(self.target_rate)

        row = [0.0] * SYNTHETIC_NUM_ROWS
        row[SYNTHETIC_PACKAGE_NUM_CHANNEL] = float(self.package_num)
        for index, value in enumerate(values_uv[:SYNTHETIC_EXG_CHANNELS]):
            row[SYNTHETIC_EXG_START_CHANNEL + index] = float(value)
        row[SYNTHETIC_BATTERY_CHANNEL] = float(battery)
        row[SYNTHETIC_TIMESTAMP_CHANNEL] = float(timestamp)
        row[SYNTHETIC_MARKER_CHANNEL] = 0.0

        self.pending.append(row)
        self.package_num = (self.package_num + 1) % 1_000_000_000
        self.sent_samples += 1
        if len(self.pending) >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        if not self.pending:
            return
        flat = [value for row in self.pending for value in row]
        payload = struct.pack("<" + "d" * len(flat), *flat)
        self.sock.sendto(payload, (self.multicast_ip, self.multicast_port))
        self.sent_packets += 1
        self.pending.clear()

    def close(self) -> None:
        self.flush()
        self.sock.close()


class Bridge:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.parser = ADS129xParser(strict_checksum=not args.allow_bad_checksum)
        self.downsampler = FractionalDownsampler(args.target_rate)
        self.stop_event = threading.Event()
        self.streamer = BrainFlowSyntheticStreamer(
            args.multicast_ip,
            args.multicast_port,
            batch_size=args.batch_size,
            target_rate=args.target_rate,
            ttl=args.ttl,
            interface_ip=args.multicast_interface,
        )
        self.raw_samples = 0
        self.output_samples = 0
        self.last_status = time.monotonic()
        self.last_sequence: Optional[int] = None
        self.dropped_frames = 0

    def handle_bytes(self, data: bytes) -> None:
        for frame in self.parser.feed(data):
            self.handle_frame(frame)

    def handle_frame(self, frame: ADS129xFrame) -> None:
        if not frame.is_eeg_frame:
            logging.debug("ignored function 0x%02X frame", frame.function)
            return

        self._track_sequence(frame.sequence)
        self.downsampler.update_source_rate(frame.sample_rate)

        for raw_sample in frame.raw_samples:
            values_uv = [adc_to_uv(value, frame.chip_type_code, frame.gain) for value in raw_sample]
            self.raw_samples += 1
            if not self.downsampler.accept():
                continue
            self.streamer.add_sample(values_uv, battery=frame.battery)
            self.output_samples += 1

        now = time.monotonic()
        if now - self.last_status >= self.args.status_interval:
            self.last_status = now
            logging.info(
                "frames=%s raw_samples=%s output_samples=%s udp_packets=%s bad_checksum=%s bad_tail=%s bad_length=%s dropped_seq=%s",
                self.parser.sample_frames,
                self.raw_samples,
                self.output_samples,
                self.streamer.sent_packets,
                self.parser.bad_checksum,
                self.parser.bad_tail,
                self.parser.bad_length,
                self.dropped_frames,
            )

    def _track_sequence(self, sequence: int) -> None:
        if self.last_sequence is None:
            self.last_sequence = sequence
            return
        expected = (self.last_sequence + 1) & 0xFFFFFFFF
        if sequence != expected:
            gap = (sequence - expected) & 0xFFFFFFFF
            if gap:
                self.dropped_frames += gap
                logging.warning("packet sequence jump: expected %s, got %s", expected, sequence)
        self.last_sequence = sequence

    def close(self) -> None:
        self.stop_event.set()
        self.streamer.close()


def run_tcp_server(args: argparse.Namespace, bridge: Bridge) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.listen_host, args.listen_port))
        server.listen(1)
        server.settimeout(1.0)
        logging.info("listening for ADS129X TCP client on %s:%s", args.listen_host, args.listen_port)

        while not bridge.stop_event.is_set():
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue
            logging.info("ADS129X client connected from %s:%s", addr[0], addr[1])
            with conn:
                conn.settimeout(1.0)
                while not bridge.stop_event.is_set():
                    try:
                        data = conn.recv(args.read_size)
                    except socket.timeout:
                        continue
                    if not data:
                        logging.warning("ADS129X client disconnected")
                        break
                    bridge.handle_bytes(data)


def run_tcp_client(args: argparse.Namespace, bridge: Bridge) -> None:
    while not bridge.stop_event.is_set():
        try:
            logging.info("connecting to ADS129X TCP server %s:%s", args.connect_host, args.connect_port)
            with socket.create_connection((args.connect_host, args.connect_port), timeout=5.0) as conn:
                conn.settimeout(1.0)
                logging.info("connected to ADS129X TCP server")
                while not bridge.stop_event.is_set():
                    try:
                        data = conn.recv(args.read_size)
                    except socket.timeout:
                        continue
                    if not data:
                        raise ConnectionError("remote closed connection")
                    bridge.handle_bytes(data)
        except OSError as exc:
            logging.warning("TCP client error: %s; retrying in %.1fs", exc, args.reconnect_delay)
            bridge.stop_event.wait(args.reconnect_delay)


def run_serial(args: argparse.Namespace, bridge: Bridge) -> None:
    try:
        import serial  # type: ignore
    except ImportError as exc:
        raise RuntimeError("serial input requires pyserial: python -m pip install pyserial") from exc

    logging.info("opening serial port %s at %s baud", args.serial_port, args.baudrate)
    with serial.Serial(args.serial_port, args.baudrate, timeout=1.0) as ser:
        while not bridge.stop_event.is_set():
            data = ser.read(args.read_size)
            if data:
                bridge.handle_bytes(data)


def run_simulate(args: argparse.Namespace, bridge: Bridge) -> None:
    logging.info(
        "simulating BrainFlow Synthetic stream to %s:%s at %s Hz",
        args.multicast_ip,
        args.multicast_port,
        args.target_rate,
    )
    next_tick = time.perf_counter()
    sample_index = 0
    while not bridge.stop_event.is_set():
        now = time.perf_counter()
        if now < next_tick:
            bridge.stop_event.wait(min(0.01, next_tick - now))
            continue
        t = sample_index / float(args.target_rate)
        values = [
            40.0 * math.sin(2.0 * math.pi * (8.0 + ch * 0.25) * t) + ch * 5.0
            for ch in range(SYNTHETIC_EXG_CHANNELS)
        ]
        bridge.streamer.add_sample(values, battery=100)
        bridge.output_samples += 1
        sample_index += 1
        next_tick += 1.0 / args.target_rate


def run_input(args: argparse.Namespace, bridge: Bridge) -> None:
    if args.input == "tcp-server":
        run_tcp_server(args, bridge)
    elif args.input == "tcp-client":
        run_tcp_client(args, bridge)
    elif args.input == "serial":
        run_serial(args, bridge)
    elif args.input == "simulate":
        run_simulate(args, bridge)
    else:
        raise ValueError(f"unsupported input mode: {args.input}")


def default_batch_size() -> int:
    raw = os.environ.get("BRAINFLOW_BATCH_SIZE")
    if not raw:
        return 3
    try:
        parsed = int(raw)
    except ValueError:
        return 3
    return parsed if 1 < parsed < 100 else 3


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bridge vendor ADS129X EEG packets to OpenBCI GUI via BrainFlow Streaming Board.",
    )
    parser.add_argument(
        "--input",
        choices=("tcp-server", "tcp-client", "serial", "simulate"),
        default="tcp-server",
        help="source for ADS129X packets",
    )
    parser.add_argument("--listen-host", default="0.0.0.0", help="TCP server bind host")
    parser.add_argument("--listen-port", type=int, default=1234, help="TCP server bind port")
    parser.add_argument("--connect-host", default="127.0.0.1", help="TCP client remote host")
    parser.add_argument("--connect-port", type=int, default=1234, help="TCP client remote port")
    parser.add_argument("--reconnect-delay", type=float, default=2.0, help="TCP reconnect delay in seconds")
    parser.add_argument("--serial-port", default="COM3", help="serial port for --input serial")
    parser.add_argument("--baudrate", type=int, default=115200, help="serial baudrate for --input serial")
    parser.add_argument("--read-size", type=int, default=4096, help="bytes to read at once")

    parser.add_argument("--multicast-ip", default="225.1.1.1", help="BrainFlow multicast group")
    parser.add_argument("--multicast-port", type=int, default=6677, help="BrainFlow multicast port")
    parser.add_argument("--multicast-interface", default=None, help="local IPv4 address for multicast output")
    parser.add_argument("--ttl", type=int, default=1, help="multicast TTL")
    parser.add_argument("--batch-size", type=int, default=default_batch_size(), help="BrainFlow batch size")
    parser.add_argument(
        "--target-rate",
        type=int,
        default=SYNTHETIC_SAMPLING_RATE,
        help="output rate for Synthetic master board; higher source rates are downsampled",
    )
    parser.add_argument("--allow-bad-checksum", action="store_true", help="parse frames even if checksum fails")
    parser.add_argument("--status-interval", type=float, default=5.0, help="status log interval in seconds")
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return parser


def install_signal_handlers() -> None:
    def stop(_signum: int, _frame: object) -> None:
        raise BridgeStop()

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    install_signal_handlers()

    bridge = Bridge(args)
    logging.info(
        "BrainFlow Streaming Board output: master=Synthetic, ip=%s, port=%s, batch=%s",
        args.multicast_ip,
        args.multicast_port,
        args.batch_size,
    )
    try:
        run_input(args, bridge)
    except BridgeStop:
        logging.info("stopping bridge")
    finally:
        bridge.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
