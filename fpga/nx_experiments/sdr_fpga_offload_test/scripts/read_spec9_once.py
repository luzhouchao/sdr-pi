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

from sdr_fpga_offload_test.sdr_kernel_contract import TAP_BASE  # noqa: E402
from sdr_fpga_offload_test.spec9_client import Spec9Client  # noqa: E402


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Trigger and read one V9A/SPEC9 coarse spectral proxy snapshot.")
    parser.add_argument("--host", default="192.168.1.10")
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--frame-len", type=int, default=64)
    parser.add_argument("--poll-sec", type=float, default=0.01)
    parser.add_argument("--timeout-sec", type=float, default=5.0)
    parser.add_argument("--out-json", default="logs/spec9_once.json")
    args = parser.parse_args()

    transport = ParamikoDevmemTransport(args.host, args.user, args.password, timeout_sec=10.0)
    try:
        client = Spec9Client(transport)
        client.assert_v9a_ids()
        client.trigger_frame(args.frame_len)
        t0 = time.perf_counter()
        polls = 0
        while True:
            polls += 1
            snap = client.assert_spec9()
            if snap.valid and not snap.busy:
                break
            if time.perf_counter() - t0 > args.timeout_sec:
                raise TimeoutError(f"SPEC9 timeout; last={snap.to_dict()}")
            time.sleep(max(0.0, args.poll_sec))
    finally:
        transport.close()

    checks = {
        "valid": snap.valid,
        "not_busy": not snap.busy,
        "samples_ok": snap.samples == args.frame_len,
        "peak_bin_range": 0 <= snap.peak_bin < snap.bin_count,
        "bin_count_ok": snap.bin_count == 4,
        "total_ge_peak": snap.total_power >= snap.peak_power,
    }
    payload = {
        "timestamp_sec": time.time(),
        "operation": "read_spec9_once",
        "requested": {"frame_len": args.frame_len},
        "snapshot": snap.to_dict(),
        "checks": checks,
        "passed": all(checks.values()),
        "polls": polls,
        "elapsed_sec": time.perf_counter() - t0,
        "notes": [
            "Bypass-only register read; no ROS, streaming runtime, robot_control, mapping, RTAB-Map, or motion paths are started.",
            "SPEC9 is a coarse fixed-bin spectral proxy, not a full FFT or calibrated PSD.",
        ],
    }
    out_json = ROOT / args.out_json
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
