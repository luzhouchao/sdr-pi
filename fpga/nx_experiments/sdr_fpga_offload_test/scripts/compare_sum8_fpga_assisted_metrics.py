#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import paramiko

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sdr_fpga_offload_test.fpga_assisted_metrics import (  # noqa: E402
    compare_primitive_metrics,
    dual_rx_cpu_primitives,
    fpga_assisted_aoa_estimate,
    sum8_aggregate_primitives,
)
from sdr_fpga_offload_test.sdr_kernel_client import Sum8AggregateClient  # noqa: E402
from sdr_fpga_offload_test.sdr_kernel_contract import TAP_BASE  # noqa: E402


def parse_devmem(text: str) -> int:
    text = text.strip()
    if not text:
        raise RuntimeError("empty devmem output")
    return int(text.split()[0], 0)


class ParamikoDevmemTransport:
    def __init__(self, host: str, user: str, password: str, timeout_sec: float) -> None:
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(
            host,
            username=user,
            password=password,
            timeout=timeout_sec,
            banner_timeout=timeout_sec,
            auth_timeout=timeout_sec,
        )

    def close(self) -> None:
        self.client.close()

    def _run(self, command: str) -> str:
        stdin, stdout, stderr = self.client.exec_command(command)
        try:
            rc = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            if rc != 0:
                raise RuntimeError(f"{command!r} failed: {err or out}")
            return out
        finally:
            stdin.close()
            stdout.close()
            stderr.close()

    def read32(self, offset: int) -> int:
        return parse_devmem(self._run(f"devmem 0x{TAP_BASE + offset:08x} 32"))

    def write32(self, offset: int, value: int) -> None:
        self._run(f"devmem 0x{TAP_BASE + offset:08x} 32 0x{value & 0xFFFFFFFF:08x}")


def _set_attr(obj, name: str, value: int) -> bool:
    try:
        if name in obj.attrs:
            obj.attrs[name].value = str(int(value))
            return True
    except Exception:
        return False
    return False


def _find_rx_device(ctx, preferred: str = ""):
    if preferred:
        dev = ctx.find_device(preferred)
        if dev is not None:
            return dev
    for name in ("cf-ad9361-lpc", "axi-ad9361-rx-hpc", "axi-ad9361-rx-lpc", "cf-ad9361-A"):
        dev = ctx.find_device(name)
        if dev is not None:
            return dev
    for dev in ctx.devices:
        try:
            if dev.find_channel("voltage0", False) is not None:
                return dev
        except Exception:
            continue
    return None


def _input_channels(rx_dev):
    out = []
    for ch in rx_dev.channels:
        if getattr(ch, "output", False):
            continue
        ch_id = getattr(ch, "id", "") or ""
        if str(ch_id).startswith("voltage"):
            out.append(ch)
    return out


def capture_raw_i16(uri: str, phy_device: str, rx_device: str, sample_rate_hz: int, center_freq_hz: int, buffer_size: int, channels: list[str]) -> np.ndarray:
    try:
        import iio
    except Exception as exc:
        raise RuntimeError("python3-libiio/iio is not available on this NX environment") from exc

    ctx = iio.Context(uri)
    phy = ctx.find_device(phy_device)
    rx_dev = _find_rx_device(ctx, rx_device)
    if phy is None or rx_dev is None:
        raise RuntimeError(f"Cannot find IIO devices: phy={phy_device}, rx={rx_device or 'auto'}")

    for lo_name in ("altvoltage1", "altvoltage0"):
        lo = phy.find_channel(lo_name, True)
        if lo is not None and _set_attr(lo, "frequency", center_freq_hz):
            break
    _set_attr(phy, "sampling_frequency", sample_rate_hz)
    ch0 = phy.find_channel("voltage0", False)
    if ch0 is not None:
        _set_attr(ch0, "sampling_frequency", sample_rate_hz)

    for ch in _input_channels(rx_dev):
        ch.enabled = False
    available = {str(getattr(ch, "id", "") or getattr(ch, "name", "")): ch for ch in _input_channels(rx_dev)}
    missing = [name for name in channels if name not in available]
    if missing:
        raise RuntimeError(f"Requested channels not available: {missing}; available={sorted(available)}")
    for name in channels:
        available[name].enabled = True

    rxbuf = iio.Buffer(rx_dev, int(buffer_size), False)
    try:
        rxbuf.refill()
        return np.frombuffer(rxbuf.read(), dtype=np.int16).copy()
    finally:
        try:
            rxbuf.cancel()
        except Exception:
            pass
        del rxbuf
        for ch in _input_channels(rx_dev):
            try:
                ch.enabled = False
            except Exception:
                pass


def capture_sum8(client: Sum8AggregateClient, frame_len: int, agg_frames: int, poll_sec: float, timeout_sec: float):
    client.arm_aggregate(frame_len=frame_len, agg_frames=agg_frames)
    poll_t0 = time.perf_counter()
    polls = 0
    while True:
        polls += 1
        if client.aggregate_done():
            return client.read_aggregate(), polls, time.perf_counter() - poll_t0
        if time.perf_counter() - poll_t0 > timeout_sec:
            raise TimeoutError("SUM8 aggregate did not finish before timeout")
        time.sleep(max(0.0, poll_sec))


def main() -> None:
    parser = argparse.ArgumentParser(description="Bypass-only side-by-side CPU raw-IQ primitives vs FPGA SUM8/AGG8 primitives.")
    parser.add_argument("--sdr-host", default="192.168.1.10")
    parser.add_argument("--sdr-user", default="root")
    parser.add_argument("--sdr-password", default="")
    parser.add_argument("--uri", default="ip:192.168.1.10")
    parser.add_argument("--phy-device", default="ad9361-phy")
    parser.add_argument("--rx-device", default="")
    parser.add_argument("--center-freq-hz", type=int, default=2_452_000_000)
    parser.add_argument("--sample-rate-hz", type=int, default=2_000_000)
    parser.add_argument("--baseline-m", type=float, default=0.02)
    parser.add_argument("--phase-calibration-deg", type=float, default=0.0)
    parser.add_argument("--frame-len", type=int, default=64)
    parser.add_argument("--agg-frames", type=int, default=64)
    parser.add_argument("--channels", default="voltage0,voltage1,voltage2,voltage3")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--poll-sec", type=float, default=0.01)
    parser.add_argument("--timeout-sec", type=float, default=5.0)
    parser.add_argument("--out-json", default="logs/sum8_fpga_assisted_metrics_20260608.json")
    args = parser.parse_args()

    channels = [token.strip() for token in args.channels.split(",") if token.strip()]
    if len(channels) != 4:
        raise ValueError("This side-by-side check expects four voltage lanes: I0,Q0,I1,Q1")

    transport = ParamikoDevmemTransport(args.sdr_host, args.sdr_user, args.sdr_password, timeout_sec=10.0)
    captures = []
    try:
        client = Sum8AggregateClient(transport)
        client.assert_sum8()
        for iteration in range(max(1, args.repeat)):
            iter_t0 = time.perf_counter()
            raw_t0 = time.perf_counter()
            raw = capture_raw_i16(
                args.uri,
                args.phy_device,
                args.rx_device,
                args.sample_rate_hz,
                args.center_freq_hz,
                args.frame_len * args.agg_frames,
                channels,
            )
            raw_elapsed = time.perf_counter() - raw_t0
            cpu = dual_rx_cpu_primitives(raw)
            fpga_t0 = time.perf_counter()
            aggregate, polls, poll_elapsed = capture_sum8(client, args.frame_len, args.agg_frames, args.poll_sec, args.timeout_sec)
            fpga_elapsed = time.perf_counter() - fpga_t0
            fpga = sum8_aggregate_primitives(aggregate)
            fpga_aoa = fpga_assisted_aoa_estimate(
                aggregate,
                center_freq_hz=args.center_freq_hz,
                baseline_m=args.baseline_m,
                phase_calibration_deg=args.phase_calibration_deg,
            )
            captures.append(
                {
                    "iteration": iteration,
                    "requested": {
                        "frame_len": args.frame_len,
                        "agg_frames": args.agg_frames,
                        "channels": channels,
                    },
                    "cpu_raw_iq": cpu.to_dict(),
                    "fpga_sum8": fpga.to_dict(),
                    "fpga_aoa_estimate_shape": fpga_aoa.to_dict(),
                    "aggregate_raw": aggregate.to_dict(),
                    "deltas": [item.to_dict() for item in compare_primitive_metrics(cpu, fpga)],
                    "timing_sec": {
                        "raw_iio_capture": raw_elapsed,
                        "cpu_primitive_compute": cpu.elapsed_sec,
                        "fpga_aggregate_capture": fpga_elapsed,
                        "fpga_poll_until_done": poll_elapsed,
                        "fpga_poll_count": polls,
                        "iteration_total": time.perf_counter() - iter_t0,
                    },
                    "passed": aggregate.done and not aggregate.overflow and aggregate.sample_count == args.frame_len * args.agg_frames,
                    "note": "CPU raw-IQ and FPGA AGG8 windows are adjacent/nearby, not hardware-synchronized; compare trends and cost, not strict equality.",
                }
            )
    finally:
        transport.close()

    payload = {
        "timestamp_sec": time.time(),
        "operation": "sum8_fpga_assisted_metrics_side_by_side",
        "capture_count": len(captures),
        "pass_count": sum(1 for item in captures if item["passed"]),
        "passed": all(item["passed"] for item in captures),
        "captures": captures,
        "safety": {
            "directory": str(ROOT),
            "bypass_only": True,
            "started_ros": False,
            "started_streaming_runtime": False,
            "modified_robot_control": False,
        },
        "performance_review": {
            "decision": "GO for bypass API comparison only",
            "fpga_role": "fixed-shape multi-frame primitive aggregation",
            "nx_role": "CPU/GPU composition, divide/sqrt/atan2/calibration/AoA/publication later",
            "no_go": "no active robot_control replacement, no FFT/DMA/streaming runtime in this step",
        },
    }
    out_json = ROOT / args.out_json
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
