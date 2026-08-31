from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class CheckResult:
    name: str
    reference: float | int
    fpga: float | int | None
    tolerance: float
    passed: bool
    detail: str


def compare_numeric(
    name: str,
    reference: float | int,
    fpga: float | int | None,
    tolerance: float,
) -> CheckResult:
    if fpga is None:
        return CheckResult(name, reference, fpga, tolerance, False, "missing_fpga_value")
    delta = abs(float(fpga) - float(reference))
    return CheckResult(
        name=name,
        reference=reference,
        fpga=fpga,
        tolerance=float(tolerance),
        passed=bool(delta <= float(tolerance)),
        detail=f"delta={delta:.6g}",
    )


def compare_spectrum(reference: dict, fpga_summary: dict, *, db_tol: float = 1.0) -> list[CheckResult]:
    checks = [
        compare_numeric("sample_count", int(reference["sample_count"]), fpga_summary.get("sample_count"), 0),
        compare_numeric("peak_index", int(reference["peak_index"]), fpga_summary.get("peak_index"), 1),
        compare_numeric("rssi_dbfs", float(reference["rssi_dbfs"]), fpga_summary.get("rssi_dbfs"), db_tol),
        compare_numeric(
            "peak_power_dbfs",
            float(reference["peak_power_dbfs"]),
            fpga_summary.get("peak_power_dbfs"),
            db_tol,
        ),
    ]
    return checks


def _reg_value(registers: dict, name: str) -> int | None:
    item = registers.get(name)
    if isinstance(item, dict) and "value" in item:
        return int(item["value"])
    if item is not None:
        return int(item)
    return None


def normalize_power_summary(payload: dict) -> dict:
    if isinstance(payload.get("power_summary"), dict):
        return payload["power_summary"]
    if isinstance(payload.get("summary"), dict):
        return payload["summary"]
    registers = payload.get("registers")
    if not isinstance(registers, dict):
        return payload

    sample_count = _reg_value(registers, "sample_count")
    if sample_count is None:
        sample_count = _reg_value(registers, "legacy_sample_count")
    peak_index = _reg_value(registers, "peak_index")
    if peak_index is None:
        peak_index = _reg_value(registers, "legacy_peak_index")
    peak_power = _reg_value(registers, "peak_power")
    if peak_power is None:
        lo = _reg_value(registers, "legacy_peak_power_lo")
        hi = _reg_value(registers, "legacy_peak_power_hi") or 0
        peak_power = None if lo is None else ((hi << 32) | lo)
    sum_lo = _reg_value(registers, "sum_power_lo")
    sum_hi = _reg_value(registers, "sum_power_hi") or 0
    if sum_lo is None:
        sum_lo = _reg_value(registers, "legacy_sum_power_lo")
        sum_hi = _reg_value(registers, "legacy_sum_power_hi") or 0
    sum_power = None if sum_lo is None else ((sum_hi << 32) | sum_lo)

    out = {
        "sample_count": sample_count,
        "sum_power_raw": sum_power,
        "peak_power_raw": peak_power,
        "peak_index": peak_index,
    }
    if sample_count and sum_power is not None:
        mean_power_norm = float(sum_power) / float(sample_count) / float(32768.0 * 32768.0)
        out["rssi_dbfs"] = 10.0 * math.log10(mean_power_norm + 1e-12)
    return out


def compare_power_frame(
    reference: dict,
    fpga_summary: dict,
    *,
    db_tol: float = 0.25,
    raw_power_tol: float = 0.0,
) -> list[CheckResult]:
    normalized = normalize_power_summary(fpga_summary)
    return [
        compare_numeric("sample_count", int(reference["sample_count"]), normalized.get("sample_count"), 0),
        compare_numeric("sum_power_raw", int(reference["sum_power_raw"]), normalized.get("sum_power_raw"), raw_power_tol),
        compare_numeric("peak_power_raw", int(reference["peak_power_raw"]), normalized.get("peak_power_raw"), raw_power_tol),
        compare_numeric("peak_index", int(reference["peak_index"]), normalized.get("peak_index"), 0),
        compare_numeric("rssi_dbfs", float(reference["rssi_dbfs"]), normalized.get("rssi_dbfs"), db_tol),
    ]


def checks_to_payload(checks: list[CheckResult]) -> dict:
    return {
        "passed": all(item.passed for item in checks),
        "checks": [
            {
                "name": item.name,
                "reference": item.reference,
                "fpga": item.fpga,
                "tolerance": item.tolerance,
                "passed": item.passed,
                "detail": item.detail,
            }
            for item in checks
        ],
    }
