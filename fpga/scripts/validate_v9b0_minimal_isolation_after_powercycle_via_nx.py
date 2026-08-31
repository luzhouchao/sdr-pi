#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import posixpath
import shlex
import time
from pathlib import Path

import paramiko


TAP_BASE = 0x43C00000
FILES = ["BOOT.bin", "devicetree.dtb", "uEnv.txt", "uImage", "uramdisk.image.gz"]

EXPECTED_HASHES = {
    "BOOT.bin": "0051864c24513248e78fde9bb6ced7d465b4a0c5df6cee804bbafb50d55d35e2",
    "devicetree.dtb": "960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a",
    "uEnv.txt": "2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f",
    "uImage": "e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5",
    "uramdisk.image.gz": "0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55",
}

EXPECTED_REGS = {
    "summary_version": (0x040, 0x53394230),
    "abi_version": (0x0EC, 0x00010002),
    "capability": (0x0F0, 0x000003FF),
    "build_id": (0x0FC, 0x56394230),
    "quality_version": (0x100, 0x51394230),
    "quality_capability": (0x138, 0x0000000F),
    "quality_build_id": (0x13C, 0x51394230),
    "agg_version": (0x180, 0x41394230),
    "agg_capability": (0x1F4, 0x0000001F),
    "agg_build_id": (0x1F8, 0x41394230),
    "spec_version": (0x200, 0x00000000),
    "spec_bin_count": (0x2F0, 0x00000000),
    "spec_capability": (0x2F4, 0x00000000),
    "spec_build_id": (0x2F8, 0x00000000),
    "spec_abi_version": (0x2FC, 0x00000000),
}


def run(client: paramiko.SSHClient, command: str, timeout: float = 30.0) -> str:
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    try:
        rc = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if rc != 0:
            raise RuntimeError(f"remote command failed ({rc}): {command}\nSTDOUT:\n{out}\nSTDERR:\n{err}")
        return out.strip()
    finally:
        stdin.close()
        stdout.close()
        stderr.close()


def run_may_fail(client: paramiko.SSHClient, command: str, timeout: float = 30.0) -> dict:
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    try:
        rc = stdout.channel.recv_exit_status()
        return {
            "rc": rc,
            "stdout": stdout.read().decode("utf-8", errors="replace").strip(),
            "stderr": stderr.read().decode("utf-8", errors="replace").strip(),
        }
    finally:
        stdin.close()
        stdout.close()
        stderr.close()


def parse_uptime(text: str) -> float:
    return float(text.split()[0])


def remote_hashes(client: paramiko.SSHClient, prefix: str) -> dict[str, str]:
    quoted = " ".join(shlex.quote(posixpath.join(prefix, name)) for name in FILES)
    out = run(client, f"set -eu; sha256sum {quoted}")
    hashes: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            hashes[posixpath.basename(parts[1])] = parts[0].lower()
    return hashes


def devmem_read(client: paramiko.SSHClient, offset: int) -> int:
    out = run(client, f"devmem 0x{TAP_BASE + offset:08x} 32")
    return int(out.split()[0], 0)


def connect_nx(args: argparse.Namespace) -> paramiko.SSHClient:
    key = paramiko.Ed25519Key.from_private_key_file(str(args.nx_key))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        args.nx_host,
        username=args.nx_user,
        pkey=key,
        timeout=args.timeout_sec,
        banner_timeout=args.timeout_sec,
        auth_timeout=args.timeout_sec,
    )
    return client


def connect_sdr_via_nx(nx: paramiko.SSHClient, args: argparse.Namespace) -> paramiko.SSHClient:
    transport = nx.get_transport()
    if transport is None:
        raise RuntimeError("NX SSH transport is not available")
    channel = transport.open_channel("direct-tcpip", (args.sdr_host, args.sdr_port), ("127.0.0.1", 0))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        args.sdr_host,
        port=args.sdr_port,
        username=args.sdr_user,
        password=args.sdr_password,
        sock=channel,
        timeout=args.timeout_sec,
        banner_timeout=args.timeout_sec,
        auth_timeout=args.timeout_sec,
    )
    return client


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate V9B0 minimal isolation after physical SDR power-cycle.")
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--nx-host", default="192.168.2.193")
    parser.add_argument("--nx-user", default="wheeltec")
    parser.add_argument("--nx-key", type=Path, default=Path.home() / ".ssh" / "codex_nx_ed25519")
    parser.add_argument("--sdr-host", default="192.168.1.10")
    parser.add_argument("--sdr-port", type=int, default=22)
    parser.add_argument("--sdr-user", default="root")
    parser.add_argument("--sdr-password", default="")
    parser.add_argument("--timeout-sec", type=float, default=15.0)
    parser.add_argument("--remote-sd", default="/sd")
    parser.add_argument("--max-uptime-sec", type=float, default=1200.0)
    args = parser.parse_args()

    started = time.time()
    result: dict = {
        "timestamp_sec": started,
        "operation": "validate_v9b0_minimal_isolation_after_powercycle_via_nx",
        "expected_hashes": EXPECTED_HASHES,
        "expected_registers": {
            name: {"offset": offset, "expected_hex": f"0x{value:08X}"}
            for name, (offset, value) in EXPECTED_REGS.items()
        },
        "safety": {
            "no_ros": True,
            "no_streaming_runtime": True,
            "no_robot_control": True,
            "no_cmd_vel_or_motion": True,
            "no_original_windows_sd_backup_touch": True,
            "no_vendor_package_touch": True,
        },
    }

    nx = connect_nx(args)
    try:
        result["nx_uname"] = run(nx, "uname -a")
        sdr = connect_sdr_via_nx(nx, args)
        try:
            result["sdr_uname"] = run(sdr, "uname -a")
            uptime_text = run(sdr, "cat /proc/uptime")
            result["sdr_uptime"] = uptime_text
            result["sdr_uptime_sec"] = parse_uptime(uptime_text)
            result["sd_hashes"] = remote_hashes(sdr, args.remote_sd)
            result["sd_hashes_ok"] = result["sd_hashes"] == EXPECTED_HASHES

            result["iio_devices"] = run_may_fail(
                sdr,
                "set -eu; for f in /sys/bus/iio/devices/iio:device*/name; do [ -e \"$f\" ] && echo \"$(basename $(dirname $f))=$(cat $f)\"; done",
            )
            result["iio_info_s"] = run_may_fail(
                sdr,
                "command -v iio_info >/dev/null 2>&1 && iio_info -s || true",
                timeout=60.0,
            )
            result["ad9361_dmesg_tail"] = run_may_fail(
                sdr,
                "dmesg | grep -Ei 'ad9361|cf_axi_adc|cf-ad9361|Calibration|Tuning|PN9|probe' | tail -100",
            )

            regs = {}
            checks = {}
            for name, (offset, expected) in EXPECTED_REGS.items():
                value = devmem_read(sdr, offset)
                regs[name] = {
                    "offset": offset,
                    "value": value,
                    "hex": f"0x{value & 0xFFFFFFFF:08X}",
                    "expected_hex": f"0x{expected:08X}",
                }
                checks[f"{name}_ok"] = value == expected
            result["version_registers"] = regs
            result["version_register_checks"] = checks
            result["version_registers_ok"] = all(checks.values())
        finally:
            sdr.close()
    finally:
        nx.close()

    iio_stdout = result.get("iio_devices", {}).get("stdout", "")
    dmesg_stdout = result.get("ad9361_dmesg_tail", {}).get("stdout", "")
    result["uptime_powercycle_ok"] = result.get("sdr_uptime_sec", 1e9) <= args.max_uptime_sec
    result["ad9361_iio_ok"] = "ad9361-phy" in iio_stdout and "cf-ad9361-lpc" in iio_stdout
    result["no_known_v9a_iio_failure"] = (
        "Tuning TX FAILED" not in dmesg_stdout
        and "cf_axi_adc: probe of 79020000.cf-ad9361-lpc failed" not in dmesg_stdout
    )
    result["passed"] = all(
        [
            result.get("sd_hashes_ok"),
            result.get("uptime_powercycle_ok"),
            result.get("ad9361_iio_ok"),
            result.get("no_known_v9a_iio_failure"),
            result.get("version_registers_ok"),
        ]
    )
    result["elapsed_sec"] = time.time() - started

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))

    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
