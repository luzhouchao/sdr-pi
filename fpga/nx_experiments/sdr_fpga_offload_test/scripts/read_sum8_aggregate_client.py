#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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


def capture_once(client: Sum8AggregateClient, frame_len: int, agg_frames: int, poll_sec: float, timeout_sec: float) -> dict:
    total_t0 = time.perf_counter()
    client.arm_aggregate(frame_len=frame_len, agg_frames=agg_frames)
    polls = 0
    poll_t0 = time.perf_counter()
    while True:
        polls += 1
        if client.aggregate_done():
            break
        if time.perf_counter() - poll_t0 > timeout_sec:
            aggregate = client.read_aggregate()
            raise TimeoutError(f"SUM8 aggregate timeout; partial={aggregate.to_dict()}")
        time.sleep(max(0.0, poll_sec))
    aggregate = client.read_aggregate()
    checks = {
        "done": aggregate.done,
        "no_overflow": not aggregate.overflow,
        "target_frames_ok": aggregate.target_frames == agg_frames,
        "frame_count_ok": aggregate.frame_count == agg_frames,
        "sample_count_ok": aggregate.sample_count == frame_len * agg_frames,
    }
    return {
        "requested": {"frame_len": frame_len, "agg_frames": agg_frames},
        "aggregate": aggregate.to_dict(),
        "checks": checks,
        "passed": all(checks.values()),
        "timing_sec": {
            "poll_until_done": time.perf_counter() - poll_t0,
            "total_capture": time.perf_counter() - total_t0,
            "poll_count": polls,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Use the reusable SUM8/AGG8 client to read FPGA aggregate primitives.")
    parser.add_argument("--host", default="192.168.1.10")
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--frame-len", type=int, default=64)
    parser.add_argument("--agg-frames", type=int, nargs="+", default=[4, 16, 64])
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--poll-sec", type=float, default=0.01)
    parser.add_argument("--timeout-sec", type=float, default=5.0)
    parser.add_argument("--out-json", default="logs/sum8_aggregate_client.json")
    args = parser.parse_args()

    transport = ParamikoDevmemTransport(args.host, args.user, args.password, timeout_sec=10.0)
    try:
        client = Sum8AggregateClient(transport)
        client.assert_sum8()
        captures = []
        for frame_count in args.agg_frames:
            for iteration in range(max(1, args.repeat)):
                item = capture_once(client, args.frame_len, frame_count, args.poll_sec, args.timeout_sec)
                item["iteration"] = iteration
                captures.append(item)
    finally:
        transport.close()

    payload = {
        "timestamp_sec": time.time(),
        "operation": "sum8_aggregate_client",
        "capture_count": len(captures),
        "pass_count": sum(1 for item in captures if item["passed"]),
        "passed": all(item["passed"] for item in captures),
        "captures": captures,
        "notes": [
            "This is a bypass-only client API check; it does not start ROS, streaming runtime, robot_control, mapping, RTAB-Map, or motion paths.",
            "FPGA performs fixed-shape aggregate primitives. NX keeps divide/sqrt/atan2/calibration/AoA/backend composition.",
        ],
    }
    out_json = ROOT / args.out_json
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
