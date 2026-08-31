#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare Summary V1 repeated FPGA frames to one-shot raw reference at a statistical level."
    )
    parser.add_argument("--series-json", default="logs/summary_v1_register_frame_series.json")
    parser.add_argument("--raw-json", default="logs/raw_i16_once_reference.json")
    parser.add_argument("--out", default="logs/summary_series_vs_raw_reference.json")
    args = parser.parse_args()

    series = json.loads(Path(args.series_json).read_text(encoding="utf-8"))
    raw = json.loads(Path(args.raw_json).read_text(encoding="utf-8"))
    frames = list(series.get("frames") or [])
    rssis = [float(item["rssi_dbfs"]) for item in frames if item.get("rssi_dbfs") is not None]
    sums = [int(item["sum_power_raw"]) for item in frames if item.get("sum_power_raw") is not None]
    reference = raw.get("reference") or {}
    raw_rssi = float(reference["rssi_dbfs"])
    raw_sum = int(reference["sum_power_raw"])

    payload = {
        "series_json": args.series_json,
        "raw_json": args.raw_json,
        "raw_reference": reference,
        "series_summary": {
            "frames": len(frames),
            "rssi_dbfs_min": min(rssis) if rssis else None,
            "rssi_dbfs_median": statistics.median(rssis) if rssis else None,
            "rssi_dbfs_max": max(rssis) if rssis else None,
            "sum_power_min": min(sums) if sums else None,
            "sum_power_median": statistics.median(sums) if sums else None,
            "sum_power_max": max(sums) if sums else None,
        },
        "delta_to_series_median": {
            "rssi_db": raw_rssi - statistics.median(rssis) if rssis else None,
            "sum_power_raw": raw_sum - statistics.median(sums) if sums else None,
        },
        "note": (
            "This is not a pass/fail equivalence test because FPGA register frames and raw IIO "
            "capture are not triggered from the exact same sample window."
        ),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
