#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HELPER_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = HELPER_ROOT.parent

REQUIRED_HELPER_FIELDS = {
    "operation",
    "passed",
    "sample_count",
    "bytes_per_refill",
    "repeat",
    "context_open_ms",
    "buffer_create_ms",
    "refill_min_ms",
    "refill_median_ms",
    "refill_max_ms",
    "copy_min_ms",
    "copy_median_ms",
    "copy_max_ms",
    "notes",
}


def _resolve_path(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return HELPER_ROOT / path


def _default_out_path() -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return EXPERIMENT_ROOT / "logs" / f"highres_iio_phase1_{stamp}.json"


def _load_json_from_stdout(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        raise ValueError("helper stdout is empty")
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            raise
        loaded = json.loads(text[start : end + 1])
    if not isinstance(loaded, dict):
        raise ValueError("helper stdout JSON is not an object")
    return loaded


def _validate_helper_json(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_HELPER_FIELDS.difference(payload))
    if missing:
        errors.append(f"missing fields: {', '.join(missing)}")
    for key in ("sample_count", "bytes_per_refill", "repeat"):
        if key in payload and not isinstance(payload[key], int):
            errors.append(f"{key} must be an integer")
    for key in (
        "context_open_ms",
        "buffer_create_ms",
        "refill_min_ms",
        "refill_median_ms",
        "refill_max_ms",
        "copy_min_ms",
        "copy_median_ms",
        "copy_max_ms",
    ):
        if key in payload and not isinstance(payload[key], (int, float)):
            errors.append(f"{key} must be numeric")
    if "passed" in payload and not isinstance(payload["passed"], bool):
        errors.append("passed must be a boolean")
    return errors


def _run_command(argv: list[str], timeout_s: float | None = None) -> tuple[subprocess.CompletedProcess[str], float]:
    started = time.perf_counter()
    proc = subprocess.run(
        argv,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_s,
    )
    return proc, (time.perf_counter() - started) * 1000.0


def _helper_args(args: argparse.Namespace) -> list[str]:
    helper_args = [
        "--sample-count",
        str(args.sample_count),
        "--repeat",
        str(args.repeat),
        "--rx-device",
        args.rx_device,
    ]
    if args.fake:
        helper_args.append("--fake")
    if args.no_copy:
        helper_args.append("--no-copy")
    if args.allow_scan_enable:
        helper_args.append("--allow-scan-enable")
    if args.extra_helper_arg:
        helper_args.extend(args.extra_helper_arg)
    return helper_args


def _run_local(args: argparse.Namespace) -> tuple[subprocess.CompletedProcess[str], float, list[str]]:
    helper = _resolve_path(args.helper)
    argv = [str(helper), *_helper_args(args)]
    proc, wall_ms = _run_command(argv, args.timeout_s)
    return proc, wall_ms, argv


def _ssh_base(args: argparse.Namespace) -> list[str]:
    argv = [args.ssh_bin]
    if args.identity:
        argv.extend(["-i", args.identity])
    if args.ssh_port:
        argv.extend(["-p", str(args.ssh_port)])
    argv.append(args.ssh_target)
    return argv


def _upload_helper(args: argparse.Namespace) -> list[dict[str, Any]]:
    if not args.upload_helper:
        return []
    local_helper = _resolve_path(args.upload_helper)
    remote_dir = args.remote_dir.rstrip("/")
    events: list[dict[str, Any]] = []

    mkdir_cmd = [*_ssh_base(args), "mkdir", "-p", remote_dir]
    mkdir_proc, mkdir_wall_ms = _run_command(mkdir_cmd, args.timeout_s)
    events.append(
        {
            "operation": "ssh_mkdir_remote_dir",
            "argv": mkdir_cmd,
            "returncode": mkdir_proc.returncode,
            "wall_ms": mkdir_wall_ms,
            "stderr": mkdir_proc.stderr,
        }
    )
    if mkdir_proc.returncode != 0:
        return events

    scp_cmd = [args.scp_bin]
    if args.identity:
        scp_cmd.extend(["-i", args.identity])
    if args.ssh_port:
        scp_cmd.extend(["-P", str(args.ssh_port)])
    scp_cmd.extend([str(local_helper), f"{args.ssh_target}:{remote_dir}/"])
    scp_proc, scp_wall_ms = _run_command(scp_cmd, args.timeout_s)
    events.append(
        {
            "operation": "scp_upload_helper",
            "argv": scp_cmd,
            "returncode": scp_proc.returncode,
            "wall_ms": scp_wall_ms,
            "stderr": scp_proc.stderr,
        }
    )
    return events


def _run_ssh(args: argparse.Namespace) -> tuple[subprocess.CompletedProcess[str], float, list[str], list[dict[str, Any]]]:
    upload_events = _upload_helper(args)
    remote_helper = args.helper
    remote_args = [remote_helper, *_helper_args(args)]
    remote_command = " ".join(shlex.quote(part) for part in remote_args)
    argv = [*_ssh_base(args), remote_command]
    proc, wall_ms = _run_command(argv, args.timeout_s)
    return proc, wall_ms, argv, upload_events


def _run_ssh_paramiko(
    args: argparse.Namespace,
) -> tuple[subprocess.CompletedProcess[str], float, list[str], list[dict[str, Any]]]:
    if args.upload_helper:
        raise ValueError("--upload-helper is not supported with --ssh-password; pre-stage the helper first")
    try:
        import paramiko
    except ImportError as exc:
        raise RuntimeError("paramiko is required when --ssh-password is used") from exc

    remote_args = [args.helper, *_helper_args(args)]
    remote_command = " ".join(shlex.quote(part) for part in remote_args)
    argv = ["paramiko-ssh", args.ssh_target, remote_command]
    host = args.ssh_target
    username = None
    if "@" in host:
        username, host = host.split("@", 1)
    port = args.ssh_port if args.ssh_port else 22
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    started = time.perf_counter()
    try:
        client.connect(
            host,
            port=port,
            username=username,
            password=args.ssh_password,
            timeout=args.timeout_s,
            banner_timeout=args.timeout_s,
            auth_timeout=args.timeout_s,
            look_for_keys=False,
            allow_agent=False,
        )
        stdin, stdout, stderr = client.exec_command(remote_command, timeout=args.timeout_s)
        stdin.close()
        returncode = stdout.channel.recv_exit_status()
        proc = subprocess.CompletedProcess(
            argv,
            returncode,
            stdout.read().decode("utf-8", errors="replace"),
            stderr.read().decode("utf-8", errors="replace"),
        )
    finally:
        client.close()
    wall_ms = (time.perf_counter() - started) * 1000.0
    return proc, wall_ms, argv, []


def _write_payload(path_text: str | None, payload: dict[str, Any]) -> Path:
    out_path = Path(path_text) if path_text else _default_out_path()
    if not out_path.is_absolute():
        out_path = EXPERIMENT_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out_path


def _smoke_json(path_text: str) -> int:
    path = _resolve_path(path_text)
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            text = ""
    if not text:
        text = raw.decode("utf-8", errors="replace")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("smoke JSON is not an object")
    errors = _validate_helper_json(payload)
    result = {
        "operation": "highres_iio_helper_json_smoke_check",
        "path": str(path),
        "passed": not errors and bool(payload.get("passed", False)),
        "errors": errors,
        "helper_operation": payload.get("operation"),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run or validate the P201 high-resolution SDR-local IIO benchmark."
    )
    parser.add_argument("--smoke-json", help="Validate a helper JSON file and exit.")
    parser.add_argument("--local", action="store_true", help="Run helper directly on this host.")
    parser.add_argument("--ssh-target", default="", help="SSH target such as root@192.168.1.10.")
    parser.add_argument("--ssh-bin", default="ssh")
    parser.add_argument("--scp-bin", default="scp")
    parser.add_argument("--identity", default="")
    parser.add_argument("--ssh-password", default="", help="Use Paramiko password SSH instead of the ssh binary.")
    parser.add_argument("--ssh-port", type=int, default=0)
    parser.add_argument("--remote-dir", default="/tmp/p201_highres_iio_helper_phase1")
    parser.add_argument("--upload-helper", default="", help="Optional local helper binary to copy before SSH run.")
    parser.add_argument("--helper", default="build/p201_highres_iio_bench")
    parser.add_argument("--sample-count", type=int, default=8192)
    parser.add_argument("--repeat", type=int, default=20)
    parser.add_argument("--rx-device", default="cf-ad9361-lpc")
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--no-copy", action="store_true")
    parser.add_argument(
        "--allow-scan-enable",
        action="store_true",
        help="Pass through helper option for an approved isolated benchmark.",
    )
    parser.add_argument("--extra-helper-arg", action="append", default=[])
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--out-json", default=None)
    args = parser.parse_args()

    if args.smoke_json:
        return _smoke_json(args.smoke_json)

    mode = "local" if args.local or not args.ssh_target else "ssh"
    upload_events: list[dict[str, Any]] = []
    if mode == "local":
        proc, wrapper_wall_ms, argv = _run_local(args)
    elif args.ssh_password:
        proc, wrapper_wall_ms, argv, upload_events = _run_ssh_paramiko(args)
    else:
        proc, wrapper_wall_ms, argv, upload_events = _run_ssh(args)

    helper_json: dict[str, Any] | None = None
    parse_errors: list[str] = []
    try:
        helper_json = _load_json_from_stdout(proc.stdout)
        parse_errors = _validate_helper_json(helper_json)
    except Exception as exc:  # noqa: BLE001 - preserve raw stdout for handoff debugging.
        parse_errors = [f"helper JSON parse failed: {exc}"]

    passed = proc.returncode == 0 and helper_json is not None and not parse_errors and bool(helper_json.get("passed"))
    payload: dict[str, Any] = {
        "operation": "p201_highres_iio_bench_launcher",
        "passed": passed,
        "mode": mode,
        "argv": argv,
        "wrapper_wall_ms": wrapper_wall_ms,
        "helper_returncode": proc.returncode,
        "helper_stdout": proc.stdout,
        "helper_stderr": proc.stderr,
        "helper_json": helper_json,
        "helper_json_errors": parse_errors,
        "upload_events": upload_events,
        "notes": [
            "SSH wrapper wall time is validation scaffolding only and is not the helper hot path.",
            "This launcher does not start ROS, SDR streaming runtime, robot_control, mapping, navigation, cmd_vel, or motion.",
        ],
    }
    out_path = _write_payload(args.out_json, payload)
    payload["out_json"] = str(out_path)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
