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
    "BOOT.bin": "58de598eea686e857a5cbb82135fea6fca2c0c79904b65af5f1b4b5f5f259447",
    "devicetree.dtb": "960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a",
    "uEnv.txt": "2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f",
    "uImage": "e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5",
    "uramdisk.image.gz": "0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55",
}

EXPECTED_REGS = {
    "summary_version": (0x040, 0x53554D39),
    "abi_version": (0x0EC, 0x00010003),
    "capability": (0x0F0, 0x000007FF),
    "build_id": (0x0FC, 0x56390001),
    "quality_version": (0x100, 0x51554139),
    "quality_capability": (0x138, 0x0000000F),
    "quality_build_id": (0x13C, 0x51390001),
    "agg_version": (0x180, 0x41474739),
    "agg_capability": (0x1F4, 0x0000001F),
    "agg_build_id": (0x1F8, 0x41390001),
    "spec_version": (0x200, 0x53504339),
    "spec_bin_count": (0x2F0, 0x00000004),
    "spec_capability": (0x2F4, 0x0000000F),
    "spec_build_id": (0x2F8, 0x53390001),
    "spec_abi_version": (0x2FC, 0x00010003),
}

SPEC_OFFSETS = {
    "spec_flags": 0x204,
    "spec_frame_id": 0x208,
    "spec_samples": 0x20C,
    "spec_peak_bin": 0x210,
    "spec_peak_power": 0x214,
    "spec_total_power": 0x218,
    "spec_noise_floor": 0x21C,
    "spec_prominence": 0x220,
    "spec_bin0_power": 0x224,
    "spec_bin1_power": 0x228,
    "spec_bin2_power": 0x22C,
    "spec_bin3_power": 0x230,
    "spec_limit_flags": 0x234,
    "spec_rx_mask": 0x238,
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


def devmem_write(client: paramiko.SSHClient, offset: int, value: int) -> None:
    run(client, f"devmem 0x{TAP_BASE + offset:08x} 32 0x{value & 0xFFFFFFFF:08x}")


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


def capture_spec9(client: paramiko.SSHClient, frame_len: int, timeout_sec: float) -> dict:
    devmem_write(client, 0x004, frame_len)
    devmem_write(client, 0x000, 0x00000002)
    devmem_write(client, 0x000, 0x00000001)
    start = time.perf_counter()
    polls = 0
    while True:
        polls += 1
        flags = devmem_read(client, 0x204)
        if (flags & 1) and not (flags & 2):
            break
        if time.perf_counter() - start > timeout_sec:
            raise TimeoutError(f"SPEC9 timeout flags=0x{flags:08X}")
        time.sleep(0.01)

    values = {name: devmem_read(client, offset) for name, offset in SPEC_OFFSETS.items()}
    bins = [
        values["spec_bin0_power"],
        values["spec_bin1_power"],
        values["spec_bin2_power"],
        values["spec_bin3_power"],
    ]
    checks = {
        "valid": bool(values["spec_flags"] & 1),
        "not_busy": not bool(values["spec_flags"] & 2),
        "samples_ok": values["spec_samples"] == frame_len,
        "peak_bin_range": 0 <= values["spec_peak_bin"] < 4,
        "total_ge_peak": values["spec_total_power"] >= values["spec_peak_power"],
        "peak_equals_selected_bin": values["spec_peak_power"] == bins[values["spec_peak_bin"]],
        "total_ge_sum_bins_or_saturated": values["spec_total_power"] >= sum(bins) or values["spec_total_power"] == 0xFFFFFFFF,
    }
    return {
        "registers": {name: {"value": value, "hex": f"0x{value & 0xFFFFFFFF:08X}"} for name, value in values.items()},
        "bins": bins,
        "checks": checks,
        "passed": all(checks.values()),
        "polls": polls,
        "elapsed_sec": time.perf_counter() - start,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate staged V9A/SPEC9 after physical SDR power-cycle via NX jump.")
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
    parser.add_argument("--frame-len", type=int, default=64)
    parser.add_argument("--repeat", type=int, default=6)
    parser.add_argument("--max-uptime-sec", type=float, default=900.0)
    args = parser.parse_args()

    started = time.time()
    result: dict = {
        "timestamp_sec": started,
        "operation": "validate_v9a_spec9_after_powercycle_via_nx",
        "expected_hashes": EXPECTED_HASHES,
        "expected_registers": {name: {"offset": offset, "expected_hex": f"0x{value:08X}"} for name, (offset, value) in EXPECTED_REGS.items()},
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
            result["iio_info_s"] = run_may_fail(sdr, "command -v iio_info >/dev/null 2>&1 && iio_info -s || true", timeout=60.0)
            result["ad9361_dmesg_tail"] = run_may_fail(
                sdr,
                "dmesg | grep -Ei 'ad9361|cf_axi_adc|cf-ad9361|Calibration|Tuning|PN9' | tail -80",
            )

            regs = {}
            checks = {}
            for name, (offset, expected) in EXPECTED_REGS.items():
                value = devmem_read(sdr, offset)
                regs[name] = {"offset": offset, "value": value, "hex": f"0x{value & 0xFFFFFFFF:08X}", "expected_hex": f"0x{expected:08X}"}
                checks[f"{name}_ok"] = value == expected
            result["version_registers"] = regs
            result["version_register_checks"] = checks
            result["version_registers_ok"] = all(checks.values())

            captures = []
            for iteration in range(max(1, args.repeat)):
                capture = capture_spec9(sdr, args.frame_len, args.timeout_sec)
                capture["iteration"] = iteration
                captures.append(capture)
            frame_ids = [item["registers"]["spec_frame_id"]["value"] for item in captures]
            result["spec9_captures"] = captures
            result["spec9_pass_count"] = sum(1 for item in captures if item["passed"])
            result["spec9_frame_id_monotonic"] = all(b > a for a, b in zip(frame_ids, frame_ids[1:]))
            result["spec9_ok"] = all(item["passed"] for item in captures) and result["spec9_frame_id_monotonic"]
        finally:
            sdr.close()
    finally:
        nx.close()

    result["uptime_powercycle_ok"] = result.get("sdr_uptime_sec", 1e9) <= args.max_uptime_sec
    result["ad9361_iio_ok"] = "ad9361-phy" in result.get("iio_devices", {}).get("stdout", "") and "cf-ad9361-lpc" in result.get("iio_devices", {}).get("stdout", "")
    result["passed"] = all(
        [
            result.get("sd_hashes_ok"),
            result.get("uptime_powercycle_ok"),
            result.get("ad9361_iio_ok"),
            result.get("version_registers_ok"),
            result.get("spec9_ok"),
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
