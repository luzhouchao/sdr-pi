#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
TAP_BASE = 0x43C00000


def parse32(text: str) -> int:
    return int(text.strip().split()[0], 0)


def signed48(lo: int, hi: int) -> int:
    value = ((hi & 0xFFFF) << 32) | (lo & 0xFFFFFFFF)
    return value - (1 << 48) if value & (1 << 47) else value


def connect(host: str, user: str, password: str) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=10, banner_timeout=10, auth_timeout=10)
    return client


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe raw V5 Q1 sum register words through safe SDR SSH.")
    parser.add_argument("--host", default="192.168.1.10")
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--repeat", type=int, default=20)
    parser.add_argument("--frame-len", type=int, default=64)
    parser.add_argument("--settle-sec", type=float, default=0.05)
    parser.add_argument("--out-json", default="logs/probe_v5_q1_sum_registers.json")
    args = parser.parse_args()

    client = connect(args.host, args.user, args.password)

    def run(cmd: str) -> str:
        stdin, stdout, stderr = client.exec_command(cmd)
        try:
            rc = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            if rc != 0:
                raise RuntimeError(f"{cmd!r} failed: {err or out}")
            return out
        finally:
            stdin.close()
            stdout.close()
            stderr.close()

    def read32(offset: int) -> int:
        return parse32(run(f"devmem 0x{TAP_BASE + offset:08x} 32"))

    def write32(offset: int, value: int) -> None:
        run(f"devmem 0x{TAP_BASE + offset:08x} 32 0x{value & 0xFFFFFFFF:08x}")

    rows = []
    try:
        for i in range(args.repeat):
            write32(0x04, int(args.frame_len))
            write32(0x00, 0x00000001)
            time.sleep(args.settle_sec)
            regs = {
                "iteration": i,
                "summary_version": read32(0x40),
                "flags": read32(0x44),
                "frame_counter": read32(0x48),
                "sample_count": read32(0x4C),
                "dual_samples": read32(0x70),
                "i1_lo": read32(0xAC),
                "i1_hi": read32(0xB0),
                "q1_lo": read32(0xB4),
                "q1_hi": read32(0xB8),
                "rx1_corr_lo": read32(0xC8),
                "rx1_corr_mid": read32(0xCC),
                "rx1_corr_hi": read32(0xD0),
            }
            regs["i1_sum"] = signed48(regs["i1_lo"], regs["i1_hi"])
            regs["q1_sum"] = signed48(regs["q1_lo"], regs["q1_hi"])
            regs["q1_hi_low16_hex"] = f"0x{regs['q1_hi'] & 0xFFFF:04X}"
            rows.append(regs)
    finally:
        client.close()

    result = {
        "operation": "probe_v5_q1_sum_registers",
        "frame_len": args.frame_len,
        "repeat": args.repeat,
        "rows": rows,
        "anomalies": [r for r in rows if abs(int(r["q1_sum"])) > args.frame_len * 32768],
    }
    out = ROOT / args.out_json
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
