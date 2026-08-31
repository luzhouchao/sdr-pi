#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import posixpath
import shlex
import time
from pathlib import Path

import paramiko


TAP_BASE = 0x43C00000
FILES = ["BOOT.bin", "devicetree.dtb", "uEnv.txt", "uImage", "uramdisk.image.gz"]

EXPECTED_HASHES = {
    "BOOT.bin": "3e2c59a32a6ba8b6a80fc9cfe4c4a0ec94a43051cbb1d383f99cbd596417f883",
    "devicetree.dtb": "960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a",
    "uEnv.txt": "2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f",
    "uImage": "e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5",
    "uramdisk.image.gz": "0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55",
}

EXPECTED_REGS = {
    "summary_version": (0x040, 0x53554D38),
    "abi_version": (0x0EC, 0x00010002),
    "capability": (0x0F0, 0x000003FF),
    "build_id": (0x0FC, 0x56384430),
    "quality_version": (0x100, 0x51554138),
    "quality_capability": (0x138, 0x0000000F),
    "quality_build_id": (0x13C, 0x51384430),
    "agg_version": (0x180, 0x41474738),
    "agg_capability": (0x1F4, 0x0000003F),
    "agg_build_id": (0x1F8, 0x41384430),
    "spec_version": (0x200, 0x00000000),
    "spec_bin_count": (0x2F0, 0x00000000),
    "spec_capability": (0x2F4, 0x00000000),
    "spec_build_id": (0x2F8, 0x00000000),
    "spec_abi_version": (0x2FC, 0x00000000),
}

AGG_MAX_FRAMES = 65535


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


def signed96(lo: int, mid: int, hi: int) -> int:
    value = ((hi & 0xFFFFFFFF) << 64) | ((mid & 0xFFFFFFFF) << 32) | (lo & 0xFFFFFFFF)
    return value - (1 << 96) if value & (1 << 95) else value


def unsigned96(lo: int, mid: int, hi: int) -> int:
    return ((hi & 0xFFFFFFFF) << 64) | ((mid & 0xFFFFFFFF) << 32) | (lo & 0xFFFFFFFF)


def derived_metrics(rx0_corr: int, rx1_corr: int, cross_re: int, cross_im: int, samples: int) -> dict[str, float | None]:
    phase_deg = math.degrees(math.atan2(cross_im, cross_re)) if (cross_re or cross_im) else None
    denom = math.sqrt(float(rx0_corr) * float(rx1_corr)) if rx0_corr > 0 and rx1_corr > 0 else 0.0
    coherence = math.sqrt(float(cross_re * cross_re + cross_im * cross_im)) / denom if denom > 0.0 else None
    return {
        "phase_deg": phase_deg,
        "coherence": coherence,
        "rx0_avg_power": float(rx0_corr) / float(samples) if rx0_corr > 0 and samples > 0 else None,
        "rx1_avg_power": float(rx1_corr) / float(samples) if rx1_corr > 0 and samples > 0 else None,
    }


def capture_agg(client: paramiko.SSHClient, frame_len: int, agg_frames: int, poll_sec: float, timeout_sec: float) -> dict:
    frame_len = max(1, min(65535, int(frame_len)))
    agg_frames = max(1, min(AGG_MAX_FRAMES, int(agg_frames)))
    total_t0 = time.perf_counter()

    devmem_write(client, 0x004, frame_len)
    devmem_write(client, 0x188, agg_frames)
    devmem_write(client, 0x184, 0x00000003)
    devmem_write(client, 0x184, 0x00000001)
    devmem_write(client, 0x000, 0x00000002)
    devmem_write(client, 0x000, 0x00000001)

    polls = 0
    poll_t0 = time.perf_counter()
    while True:
        control = devmem_read(client, 0x184)
        polls += 1
        if control & (1 << 4):
            break
        if time.perf_counter() - poll_t0 > timeout_sec:
            raise TimeoutError(f"AGG8 did not finish in {timeout_sec} seconds; last control=0x{control:08X}")
        time.sleep(max(0.0, poll_sec))

    agg_frame_count = devmem_read(client, 0x18C)
    agg_sample_count = devmem_read(client, 0x190)
    rx0_corr = signed96(devmem_read(client, 0x194), devmem_read(client, 0x198), devmem_read(client, 0x19C))
    rx1_corr = signed96(devmem_read(client, 0x1A0), devmem_read(client, 0x1A4), devmem_read(client, 0x1A8))
    cross_re = signed96(devmem_read(client, 0x1AC), devmem_read(client, 0x1B0), devmem_read(client, 0x1B4))
    cross_im = signed96(devmem_read(client, 0x1B8), devmem_read(client, 0x1BC), devmem_read(client, 0x1C0))
    rx0_raw = unsigned96(devmem_read(client, 0x1C4), devmem_read(client, 0x1C8), devmem_read(client, 0x1CC))
    rx1_raw = unsigned96(devmem_read(client, 0x1D0), devmem_read(client, 0x1D4), devmem_read(client, 0x1D8))
    rx0_clip = devmem_read(client, 0x1DC)
    rx1_clip = devmem_read(client, 0x1E0)
    rx0_zc = devmem_read(client, 0x1E4)
    rx1_zc = devmem_read(client, 0x1E8)
    sign_same = devmem_read(client, 0x1EC)
    last_frame = devmem_read(client, 0x1F0)
    agg_cap = devmem_read(client, 0x1F4)
    agg_build = devmem_read(client, 0x1F8)
    agg_limit = devmem_read(client, 0x1FC)

    checks = {
        "agg_done": bool(control & (1 << 4)),
        "agg_no_overflow": not bool(control & (1 << 5)),
        "agg_frames_ok": agg_frame_count == agg_frames,
        "agg_samples_ok": agg_sample_count == agg_frames * frame_len,
        "agg_capability_ok": agg_cap == 0x0000003F,
        "agg_build_id_ok": agg_build == 0x41384430,
        "agg_limit_ok": agg_limit == AGG_MAX_FRAMES,
    }

    return {
        "requested": {"frame_len": frame_len, "agg_frames": agg_frames},
        "control_hex": f"0x{control:08X}",
        "frame_count": agg_frame_count,
        "sample_count": agg_sample_count,
        "rx0_corr_power_num": rx0_corr,
        "rx1_corr_power_num": rx1_corr,
        "corr_cross_re_num": cross_re,
        "corr_cross_im_num": cross_im,
        "rx0_raw_power": rx0_raw,
        "rx1_raw_power": rx1_raw,
        "rx0_clip_count": rx0_clip,
        "rx1_clip_count": rx1_clip,
        "rx0_zero_cross_count": rx0_zc,
        "rx1_zero_cross_count": rx1_zc,
        "same_sign_count": sign_same,
        "last_frame": last_frame,
        "agg_capability_hex": f"0x{agg_cap:08X}",
        "agg_build_id_hex": f"0x{agg_build:08X}",
        "agg_limit": agg_limit,
        "derived": derived_metrics(rx0_corr, rx1_corr, cross_re, cross_im, agg_sample_count),
        "checks": checks,
        "passed": all(checks.values()),
        "poll_count": polls,
        "elapsed_sec": time.perf_counter() - total_t0,
    }


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
    parser = argparse.ArgumentParser(description="Validate V8D0 layout probe after physical SDR power-cycle.")
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
    parser.add_argument("--frame-len", type=int, default=64)
    parser.add_argument("--agg-frames", type=int, default=16)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--poll-sec", type=float, default=0.01)
    parser.add_argument("--capture-timeout-sec", type=float, default=3.0)
    args = parser.parse_args()

    started = time.time()
    result: dict = {
        "timestamp_sec": started,
        "operation": "validate_v8d0_layout_probe_after_powercycle_via_nx",
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
            "devmem_only_capture": True,
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
                "dmesg | grep -Ei 'ad9361|cf_axi_adc|cf-ad9361|Calibration|Tuning|PN9|probe' | tail -120",
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

            captures = []
            capture_error = ""
            try:
                for _ in range(max(1, int(args.repeat))):
                    captures.append(
                        capture_agg(
                            sdr,
                            frame_len=args.frame_len,
                            agg_frames=args.agg_frames,
                            poll_sec=args.poll_sec,
                            timeout_sec=args.capture_timeout_sec,
                        )
                    )
            except Exception as exc:
                capture_error = repr(exc)
            result["captures"] = captures
            result["capture_error"] = capture_error
            result["captures_ok"] = bool(captures) and not capture_error and all(item["passed"] for item in captures)
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
            result.get("captures_ok"),
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
