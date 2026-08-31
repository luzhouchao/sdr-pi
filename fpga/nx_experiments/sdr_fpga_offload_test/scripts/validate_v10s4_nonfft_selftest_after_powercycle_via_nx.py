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
SELFTEST_BASE = 0x43C20000
FILES = ["BOOT.bin", "devicetree.dtb", "uEnv.txt", "uImage", "uramdisk.image.gz"]

EXPECTED_HASHES = {
    "BOOT.bin": "df773e5b8b01f301634ff838f462464289213cfb4bba6c11855d022e08a377ce",
    "devicetree.dtb": "960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a",
    "uEnv.txt": "2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f",
    "uImage": "e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5",
    "uramdisk.image.gz": "0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55",
}

EXPECTED_V8D0_REGS = {
    "summary_version": (0x040, 0x53554D38),
    "summary_build_id": (0x0FC, 0x56384430),
    "quality_version": (0x100, 0x51554138),
    "quality_build_id": (0x13C, 0x51384430),
    "agg_version": (0x180, 0x41474738),
    "agg_capability": (0x1F4, 0x0000003F),
    "agg_build_id": (0x1F8, 0x41384430),
    "spec_version_zero": (0x200, 0x00000000),
    "spec_bin_count_zero": (0x2F0, 0x00000000),
    "spec_capability_zero": (0x2F4, 0x00000000),
    "spec_build_id_zero": (0x2F8, 0x00000000),
    "spec_abi_zero": (0x2FC, 0x00000000),
}

EXPECTED_V10S4_REGS_BEFORE_START = {
    "version": (0x00, 0x53345430),
    "capability": (0x18, 0x00000007),
    "build_id": (0x1C, 0x56313034),
    "abi_version": (0x20, 0x000A4000),
    "expect_done_mask": (0xE0, 0x00000007),
    "expect_error": (0xE4, 0x00000000),
    "test_capability": (0xF4, 0x00000007),
    "test_build_id": (0xF8, 0x56313034),
    "test_abi_version": (0xFC, 0x000A4000),
}

EXPECTED_V10S4_REGS_AFTER_START = {
    "done_mask": (0x0C, 0x00000007),
    "error_mask": (0x10, 0x00000000),
    "quality_count": (0x34, 8),
    "quality_sum_i": (0x38, 0x00008374),
    "quality_sum_q": (0x3C, 0xFFFF7B9C),
    "quality_sum_i2": (0x40, 0x400E6D8C),
    "quality_sum_q2": (0x44, 0x400FE730),
    "quality_sum_iq": (0x48, 0xBFF187E8),
    "quality_peak": (0x4C, 32768),
    "quality_clip": (0x50, 0x00010001),
    "quality_sat": (0x54, 0x00010001),
    "quality_valid": (0x58, 8),
    "quality_drop": (0x5C, 0),
    "window_raw": (0x74, 8),
    "window_accepted": (0x78, 8),
    "window_dropped": (0x7C, 0),
    "window_overflow": (0x80, 0),
    "window_frame_id": (0x84, 1),
    "energy_frame_id": (0xA4, 1),
    "energy_count": (0xA8, 8),
    "energy_total": (0xAC, 309),
    "energy_noise": (0xB0, 2),
    "energy_peak": (0xB4, 100),
    "energy_peak_index": (0xB8, 4),
    "energy_second": (0xBC, 90),
    "energy_second_index": (0xC0, 6),
    "energy_prominence": (0xC4, 98),
    "energy_threshold_count": (0xC8, 3),
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


def devmem_read(client: paramiko.SSHClient, addr: int) -> int:
    out = run(client, f"devmem 0x{addr:08x} 32")
    return int(out.split()[0], 0)


def devmem_write(client: paramiko.SSHClient, addr: int, value: int) -> None:
    run(client, f"devmem 0x{addr:08x} 32 0x{value & 0xFFFFFFFF:08x}")


def read_expected_regs(client: paramiko.SSHClient, base: int, expected: dict[str, tuple[int, int]]) -> dict:
    observed: dict[str, dict] = {}
    for name, (offset, exp) in expected.items():
        got = devmem_read(client, base + offset)
        observed[name] = {
            "addr_hex": f"0x{base + offset:08X}",
            "offset_hex": f"0x{offset:02X}",
            "expected_hex": f"0x{exp:08X}",
            "observed_hex": f"0x{got:08X}",
            "passed": got == exp,
        }
    return observed


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
    parser = argparse.ArgumentParser(description="Validate V10S4 non-FFT self-test after physical SDR power-cycle.")
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

    result: dict = {
        "timestamp_sec": time.time(),
        "operation": "validate_v10s4_nonfft_selftest_after_powercycle_via_nx",
        "expected_hashes": EXPECTED_HASHES,
        "tap_base_hex": f"0x{TAP_BASE:08X}",
        "selftest_base_hex": f"0x{SELFTEST_BASE:08X}",
        "safety": {
            "no_ros": True,
            "no_streaming_runtime": True,
            "no_robot_control": True,
            "no_cmd_vel_or_motion": True,
            "devmem_only": True,
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
            result["uptime_powercycle_ok"] = result["sdr_uptime_sec"] <= args.max_uptime_sec

            result["sd_hashes"] = remote_hashes(sdr, args.remote_sd)
            result["sd_hashes_ok"] = result["sd_hashes"] == EXPECTED_HASHES

            result["iio_devices"] = run_may_fail(
                sdr,
                "set -eu; for f in /sys/bus/iio/devices/iio:device*/name; do [ -e \"$f\" ] && echo \"$(basename $(dirname $f))=$(cat $f)\"; done",
            )
            result["iio_info_s"] = run_may_fail(sdr, "iio_info -s", timeout=60.0)
            result["dmesg_ad9361_tail"] = run_may_fail(
                sdr,
                "dmesg | grep -Ei 'ad9361|cf_axi_adc|cf-ad9361|Tuning TX FAILED|79020000|probe' | tail -120",
            )
            iio_text = (result["iio_devices"].get("stdout", "") + "\n" + result["iio_info_s"].get("stdout", "")).lower()
            dmesg_text = result["dmesg_ad9361_tail"].get("stdout", "")
            result["iio_health"] = {
                "ad9361_phy_present": "ad9361-phy" in iio_text,
                "cf_ad9361_lpc_present": "cf-ad9361-lpc" in iio_text,
                "iio_info_s_rc_ok": result["iio_info_s"].get("rc") == 0,
                "no_tuning_tx_failed": "Tuning TX FAILED" not in dmesg_text,
                "no_cf_axi_adc_probe_error_minus5": "failed with error -5" not in dmesg_text,
            }
            result["iio_health"]["passed"] = all(result["iio_health"].values())

            result["v8d0_regs"] = read_expected_regs(sdr, TAP_BASE, EXPECTED_V8D0_REGS)
            result["v10s4_regs_before_start"] = read_expected_regs(
                sdr, SELFTEST_BASE, EXPECTED_V10S4_REGS_BEFORE_START
            )
            run_id_before = devmem_read(sdr, SELFTEST_BASE + 0x14)
            result["v10s4_run_id_before"] = run_id_before

            devmem_write(sdr, SELFTEST_BASE + 0x04, 0x00000004)
            devmem_write(sdr, SELFTEST_BASE + 0x04, 0x00000003)
            status = 0
            polls = 0
            poll_start = time.time()
            while time.time() - poll_start < 5.0:
                status = devmem_read(sdr, SELFTEST_BASE + 0x08)
                polls += 1
                if status & 0x00000004:
                    break
                time.sleep(0.01)

            run_id_after = devmem_read(sdr, SELFTEST_BASE + 0x14)
            result["v10s4_status_after_start_hex"] = f"0x{status:08X}"
            result["v10s4_status_poll_count"] = polls
            result["v10s4_done_bit"] = bool(status & 0x00000004)
            result["v10s4_fail_bit"] = bool(status & 0x00000008)
            result["v10s4_run_id_after"] = run_id_after
            result["v10s4_run_id_increment_ok"] = run_id_after == ((run_id_before + 1) & 0xFFFFFFFF)

            result["v10s4_regs_after_start"] = read_expected_regs(
                sdr, SELFTEST_BASE, EXPECTED_V10S4_REGS_AFTER_START
            )
            energy_flags = devmem_read(sdr, SELFTEST_BASE + 0xA0)
            result["v10s4_energy_flags_hex"] = f"0x{energy_flags:08X}"
            result["v10s4_energy_flags_mask_ok"] = (energy_flags & 0x00000117) == 0x00000111
        finally:
            sdr.close()
    finally:
        nx.close()

    v8d0_ok = all(item["passed"] for item in result["v8d0_regs"].values())
    pre_ok = all(item["passed"] for item in result["v10s4_regs_before_start"].values())
    post_ok = all(item["passed"] for item in result["v10s4_regs_after_start"].values())
    result["passed"] = bool(
        result["sd_hashes_ok"]
        and result["uptime_powercycle_ok"]
        and result["iio_health"]["passed"]
        and v8d0_ok
        and pre_ok
        and result["v10s4_done_bit"]
        and not result["v10s4_fail_bit"]
        and result["v10s4_run_id_increment_ok"]
        and post_ok
        and result["v10s4_energy_flags_mask_ok"]
    )

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))

    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
