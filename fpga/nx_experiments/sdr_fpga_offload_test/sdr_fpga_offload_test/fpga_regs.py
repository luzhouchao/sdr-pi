from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


TAP_BASE = 0x43C00000

DIAG_REGISTERS = {
    "debug_flags": 0x43C00030,
    "debug_clk": 0x43C00034,
    "debug_valid": 0x43C00038,
    "debug_accept": 0x43C0003C,
}

LEGACY_SUMMARY_REGISTERS = {
    "legacy_status": TAP_BASE + 0x08,
    "legacy_sample_count": TAP_BASE + 0x0C,
    "legacy_peak_power_lo": TAP_BASE + 0x10,
    "legacy_peak_power_hi": TAP_BASE + 0x14,
    "legacy_peak_index": TAP_BASE + 0x18,
    "legacy_sum_power_lo": TAP_BASE + 0x1C,
    "legacy_sum_power_hi": TAP_BASE + 0x20,
    "legacy_frame_count": TAP_BASE + 0x24,
    "legacy_last_power_lo": TAP_BASE + 0x28,
    "legacy_last_power_hi": TAP_BASE + 0x2C,
}

SUMMARY_REGISTERS = {
    "summary_version": TAP_BASE + 0x40,
    "summary_flags": TAP_BASE + 0x44,
    "frame_counter": TAP_BASE + 0x48,
    "sample_count": TAP_BASE + 0x4C,
    "sum_power_lo": TAP_BASE + 0x50,
    "sum_power_hi": TAP_BASE + 0x54,
    "peak_power": TAP_BASE + 0x58,
    "peak_index": TAP_BASE + 0x5C,
}

PROPOSED_AOA_REGISTERS = {
    "i_accum_lo": TAP_BASE + 0x60,
    "i_accum_hi": TAP_BASE + 0x64,
    "q_accum_lo": TAP_BASE + 0x68,
    "q_accum_hi": TAP_BASE + 0x6C,
    "rx0_power_lo": TAP_BASE + 0x70,
    "rx0_power_hi": TAP_BASE + 0x74,
    "rx1_power_lo": TAP_BASE + 0x78,
    "rx1_power_hi": TAP_BASE + 0x7C,
    "cross_re_lo": TAP_BASE + 0x80,
    "cross_re_hi": TAP_BASE + 0x84,
    "cross_im_lo": TAP_BASE + 0x88,
    "cross_im_hi": TAP_BASE + 0x8C,
}


@dataclass(frozen=True)
class SdrSshConfig:
    host: str = "192.168.1.10"
    user: str = "root"
    password: str = ""
    timeout_sec: float = 8.0


def _parse_devmem_value(text: str) -> int:
    match = re.search(r"0x[0-9a-fA-F]+|\b\d+\b", text)
    if not match:
        raise RuntimeError(f"Cannot parse devmem value from: {text!r}")
    return int(match.group(0), 0)


def read_registers_via_ssh(
    registers: dict[str, int],
    config: SdrSshConfig = SdrSshConfig(),
) -> dict[str, int]:
    try:
        import paramiko
    except Exception as exc:
        raise RuntimeError("paramiko is required for SDR SSH register reads") from exc

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=config.host,
        username=config.user,
        password=config.password,
        timeout=float(config.timeout_sec),
        banner_timeout=float(config.timeout_sec),
        auth_timeout=float(config.timeout_sec),
    )
    try:
        values: dict[str, int] = {}
        for name, addr in registers.items():
            stdin, stdout, stderr = client.exec_command(f"devmem 0x{addr:08x} 32")
            try:
                rc = stdout.channel.recv_exit_status()
                out = stdout.read().decode("utf-8", errors="replace").strip()
                err = stderr.read().decode("utf-8", errors="replace").strip()
            finally:
                stdin.close()
                stdout.close()
                stderr.close()
            if rc != 0:
                raise RuntimeError(f"devmem failed for {name} 0x{addr:08x}: {err or out}")
            values[name] = _parse_devmem_value(out)
        return values
    finally:
        client.close()


def read_registers_via_nested_ssh(registers: dict[str, int], host: str = "root@192.168.1.10") -> dict[str, int]:
    values: dict[str, int] = {}
    for name, addr in registers.items():
        result = subprocess.run(
            ["ssh", host, f"devmem 0x{addr:08x} 32"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(f"devmem failed for {name} 0x{addr:08x}: {result.stderr.strip()}")
        values[name] = _parse_devmem_value(result.stdout)
    return values


def build_snapshot(values: dict[str, int], kind: str) -> dict:
    return {
        "kind": kind,
        "timestamp_sec": time.time(),
        "tap_base": f"0x{TAP_BASE:08x}",
        "registers": {
            name: {
                "value": int(value),
                "hex": f"0x{int(value) & 0xffffffff:08x}",
            }
            for name, value in values.items()
        },
    }


def write_json(path: str | Path, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
