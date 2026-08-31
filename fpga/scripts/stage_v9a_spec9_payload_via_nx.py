#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import shlex
import time
from pathlib import Path

import paramiko


FILES = ["BOOT.bin", "devicetree.dtb", "uEnv.txt", "uImage", "uramdisk.image.gz"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def remote_hashes(client: paramiko.SSHClient, prefix: str) -> dict[str, str]:
    quoted = " ".join(shlex.quote(posixpath.join(prefix, name)) for name in FILES)
    out = run(client, f"set -eu; sha256sum {quoted}")
    hashes: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            hashes[posixpath.basename(parts[1])] = parts[0].lower()
    return hashes


def mkdir_sftp(sftp: paramiko.SFTPClient, path: str) -> None:
    parts = [part for part in path.split("/") if part]
    cur = ""
    for part in parts:
        cur = f"{cur}/{part}"
        try:
            sftp.mkdir(cur)
        except OSError:
            pass


def upload_file_exec(client: paramiko.SSHClient, local_path: Path, remote_path: str, timeout: float = 60.0) -> None:
    remote_dir = posixpath.dirname(remote_path)
    command = f"set -eu; mkdir -p {shlex.quote(remote_dir)}; cat > {shlex.quote(remote_path)}"
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    try:
        with local_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(256 * 1024), b""):
                stdin.write(chunk)
        stdin.channel.shutdown_write()
        rc = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if rc != 0:
            raise RuntimeError(f"upload failed ({rc}) for {remote_path}\nSTDOUT:\n{out}\nSTDERR:\n{err}")
    finally:
        stdin.close()
        stdout.close()
        stderr.close()


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
    channel = transport.open_channel(
        "direct-tcpip",
        (args.sdr_host, args.sdr_port),
        ("127.0.0.1", 0),
    )
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
    parser = argparse.ArgumentParser(description="Stage a prepared P201Pro SD payload to SDR /sd via NX SSH jump.")
    parser.add_argument("--payload-dir", type=Path, required=True)
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
    parser.add_argument("--remote-tmp-prefix", default="/tmp/p201_v9a_spec9_payload")
    parser.add_argument("--operation", default="stage_v9a_spec9_payload_via_nx")
    args = parser.parse_args()

    payload_dir = args.payload_dir.resolve()
    missing = [name for name in FILES if not (payload_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"payload missing files: {missing}")

    expected = {name: sha256_file(payload_dir / name) for name in FILES}
    started = time.time()
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(started))
    remote_tmp = f"{args.remote_tmp_prefix}_{stamp}"

    result: dict = {
        "timestamp_sec": started,
        "operation": args.operation,
        "payload_dir": str(payload_dir),
        "remote_sd": args.remote_sd,
        "remote_tmp": remote_tmp,
        "expected_hashes": expected,
        "safety": {
            "no_ros": True,
            "no_streaming_runtime": True,
            "no_robot_control": True,
            "no_cmd_vel_or_motion": True,
            "no_original_windows_sd_backup_touch": True,
            "no_vendor_package_touch": True,
            "requires_physical_power_cycle_after_staging": True,
        },
    }

    nx = connect_nx(args)
    try:
        result["nx_uname"] = run(nx, "uname -a")
        sdr = connect_sdr_via_nx(nx, args)
        try:
            result["sdr_uname_before"] = run(sdr, "uname -a")
            result["sdr_uptime_before"] = run(sdr, "cat /proc/uptime")
            result["sd_df_before"] = run(sdr, f"df -k {shlex.quote(args.remote_sd)}")
            result["remote_before_hashes"] = remote_hashes(sdr, args.remote_sd)

            try:
                sftp = sdr.open_sftp()
            except Exception as exc:
                result["upload_method"] = "ssh_exec_cat"
                result["sftp_error"] = repr(exc)
                for name in FILES:
                    upload_file_exec(sdr, payload_dir / name, posixpath.join(remote_tmp, name))
            else:
                result["upload_method"] = "sftp"
                try:
                    mkdir_sftp(sftp, remote_tmp)
                    for name in FILES:
                        sftp.put(str(payload_dir / name), posixpath.join(remote_tmp, name))
                finally:
                    sftp.close()

            result["remote_tmp_hashes"] = remote_hashes(sdr, remote_tmp)
            if result["remote_tmp_hashes"] != expected:
                raise RuntimeError(
                    "remote tmp hashes do not match expected: "
                    + json.dumps(result["remote_tmp_hashes"], sort_keys=True)
                )

            copy_lines = [
                "set -eu",
                f"test -d {shlex.quote(args.remote_sd)}",
            ]
            for name in FILES:
                src = shlex.quote(posixpath.join(remote_tmp, name))
                dst = shlex.quote(posixpath.join(args.remote_sd, name))
                copy_lines.append(f"cp {src} {dst}")
            copy_lines.extend(["sync", "sync"])
            result["copy_stdout"] = run(sdr, "\n".join(copy_lines), timeout=60.0)

            result["remote_after_hashes"] = remote_hashes(sdr, args.remote_sd)
            result["sd_df_after"] = run(sdr, f"df -k {shlex.quote(args.remote_sd)}")
            result["sdr_uptime_after"] = run(sdr, "cat /proc/uptime")
            result["passed"] = result["remote_after_hashes"] == expected
        finally:
            sdr.close()
    finally:
        nx.close()

    result["elapsed_sec"] = time.time() - started
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))

    if not result.get("passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
