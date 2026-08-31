#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import paramiko
from paramiko.ssh_exception import SSHException


ROOT = Path(__file__).resolve().parents[1]
PAYLOAD_ROOT = ROOT / "boot_payload"
BOOT_FILES = ["BOOT.bin", "devicetree.dtb", "uEnv.txt", "uImage", "uramdisk.image.gz"]

EXPECTED = {
    "v4": {
        "boot_sha256": "fd7c080532ee0668eb462db83208b220bbdbc3ace7a61b23e34f2b6a0699accd",
        "version_reg": "0x53554D34",
    },
    "v5": {
        "boot_sha256": "a9849d26185671c9fb276cdab032913864b379b3c8fcca9286d472be964f0544",
        "version_reg": "0x53554D35",
    },
    "v6": {
        "boot_sha256": "e47c012ad5f8f14bc769620f00add18ef75be74bd09dbaaddaa91aaf62ade60b",
        "version_reg": "0x53554D36",
    },
    "v7": {
        "boot_sha256": "ca7af9cfa33ddb26a5817b9a0117e550e295f3b1a992cf5236d040dabfe405d1",
        "version_reg": "0x53554D37",
    },
    "v8": {
        "boot_sha256": "6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb",
        "version_reg": "0x53554D38",
    },
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(client: paramiko.SSHClient, cmd: str) -> str:
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


def connect(host: str, user: str, password: str) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=10, banner_timeout=10, auth_timeout=10)
    return client


def upload_file(client: paramiko.SSHClient, local_path: Path, remote_path: str) -> str:
    try:
        sftp = client.open_sftp()
        try:
            sftp.put(str(local_path), remote_path)
        finally:
            sftp.close()
        return "sftp"
    except SSHException:
        transport = client.get_transport()
        if transport is None:
            raise RuntimeError("SSH transport is not available")
        channel = transport.open_session()
        channel.exec_command(f"cat > {remote_path}")
        with local_path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                channel.sendall(chunk)
        channel.shutdown_write()
        rc = channel.recv_exit_status()
        if rc != 0:
            raise RuntimeError(f"cat upload failed for {remote_path}: rc={rc}")
        return "ssh-cat"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage one prepared P201Pro FPGA SD payload to SDR /sd through the independent NX test directory."
    )
    parser.add_argument("version", choices=["v8", "v7", "v6", "v4", "v5"], help="Active test order is v8, then v7, v6, v4 debug fallback. V5 is historical failed reference.")
    parser.add_argument("--host", default="192.168.1.10")
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--write", action="store_true", help="Actually write the five boot files to /sd.")
    parser.add_argument("--out-json", default="", help="Default: logs/stage_<version>_to_sdr_sd.json")
    args = parser.parse_args()

    version = args.version.lower()
    payload_dir = PAYLOAD_ROOT / version
    missing = [name for name in BOOT_FILES if not (payload_dir / name).is_file()]
    if missing:
        raise SystemExit(f"missing payload files in {payload_dir}: {missing}")

    local_hashes = {name: sha256_file(payload_dir / name) for name in BOOT_FILES}
    expected_boot = EXPECTED[version]["boot_sha256"]
    if local_hashes["BOOT.bin"].lower() != expected_boot:
        raise SystemExit(f"unexpected {version} BOOT.bin hash: {local_hashes['BOOT.bin']} != {expected_boot}")

    result: dict = {
        "timestamp_unix": time.time(),
        "version": version,
        "payload_dir": str(payload_dir),
        "write_requested": bool(args.write),
        "local_hashes": local_hashes,
        "expected": EXPECTED[version],
        "safety": {
            "nx_directory": str(ROOT),
            "writes_only_sdr_sd_when_write_flag_is_set": True,
            "does_not_reboot": True,
            "does_not_start_ros_or_streaming": True,
        },
    }

    client = connect(args.host, args.user, args.password)
    try:
        result["remote_before_hashes"] = run(
            client,
            "sha256sum /sd/BOOT.bin /sd/devicetree.dtb /sd/uEnv.txt /sd/uImage /sd/uramdisk.image.gz 2>/dev/null || true",
        )
        result["remote_mount"] = run(client, "mount | grep ' /sd ' || true")
        if args.write:
            upload_methods = {}
            for name in BOOT_FILES:
                upload_methods[name] = upload_file(client, payload_dir / name, f"/sd/{name}")
            result["upload_methods"] = upload_methods
            run(client, "sync")
            result["remote_after_hashes"] = run(
                client,
                "sha256sum /sd/BOOT.bin /sd/devicetree.dtb /sd/uEnv.txt /sd/uImage /sd/uramdisk.image.gz",
            )
        else:
            result["remote_after_hashes"] = ""
    finally:
        client.close()

    out_json = Path(args.out_json) if args.out_json else ROOT / "logs" / f"stage_{version}_to_sdr_sd.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
