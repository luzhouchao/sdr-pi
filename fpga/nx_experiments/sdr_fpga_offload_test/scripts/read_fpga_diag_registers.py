#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sdr_fpga_offload_test.fpga_regs import (  # noqa: E402
    DIAG_REGISTERS,
    LEGACY_SUMMARY_REGISTERS,
    PROPOSED_AOA_REGISTERS,
    SUMMARY_REGISTERS,
    SdrSshConfig,
    build_snapshot,
    read_registers_via_ssh,
    write_json,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read P201Pro FPGA diagnostic registers only.")
    parser.add_argument("--host", default="192.168.1.10")
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--include-legacy-summary", action="store_true")
    parser.add_argument("--include-summary", action="store_true")
    parser.add_argument("--include-proposed-aoa", action="store_true")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    registers = dict(DIAG_REGISTERS)
    kind = "diag"
    if args.include_legacy_summary:
        registers.update(LEGACY_SUMMARY_REGISTERS)
        kind = "diag_plus_legacy_summary"
    if args.include_summary:
        registers.update(SUMMARY_REGISTERS)
        kind = "diag_plus_summary"
    if args.include_proposed_aoa:
        registers.update(PROPOSED_AOA_REGISTERS)
        kind = "diag_plus_summary_plus_proposed_aoa"

    values = read_registers_via_ssh(
        registers,
        SdrSshConfig(host=args.host, user=args.user, password=args.password),
    )
    payload = build_snapshot(values, kind)
    if args.out:
        write_json(args.out, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
