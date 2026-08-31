#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sdr_fpga_offload_test.reference_compute import dataclass_to_dict, power_frame_reference


def _set_attr(obj, name: str, value: int) -> bool:
    try:
        if name in obj.attrs:
            obj.attrs[name].value = str(int(value))
            return True
    except Exception:
        return False
    return False


def _find_rx_device(ctx, preferred: str = ""):
    if preferred:
        dev = ctx.find_device(preferred)
        if dev is not None:
            return dev
    for name in ("cf-ad9361-lpc", "axi-ad9361-rx-hpc", "axi-ad9361-rx-lpc", "cf-ad9361-A"):
        dev = ctx.find_device(name)
        if dev is not None:
            return dev
    for dev in ctx.devices:
        try:
            if dev.find_channel("voltage0", False) is not None:
                return dev
        except Exception:
            continue
    return None


def _input_channels(rx_dev):
    out = []
    for ch in rx_dev.channels:
        if getattr(ch, "output", False):
            continue
        ch_id = getattr(ch, "id", "") or ""
        if str(ch_id).startswith("voltage"):
            out.append(ch)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-shot raw I16 capture for independent FPGA offload reference checks."
    )
    parser.add_argument("--uri", default="ip:192.168.1.10")
    parser.add_argument("--phy-device", default="ad9361-phy")
    parser.add_argument("--rx-device", default="")
    parser.add_argument("--center-freq-hz", type=int, default=2_452_000_000)
    parser.add_argument("--sample-rate-hz", type=int, default=2_000_000)
    parser.add_argument("--buffer-size", type=int, default=64)
    parser.add_argument("--channels", default="voltage0,voltage1")
    parser.add_argument("--out-npz", default="samples/raw_i16_once.npz")
    parser.add_argument("--out-json", default="logs/raw_i16_once_reference.json")
    args = parser.parse_args()

    try:
        import iio
    except Exception as exc:
        raise RuntimeError("python3-libiio/iio is not available on this NX environment") from exc

    ctx = iio.Context(args.uri)
    phy = ctx.find_device(args.phy_device)
    rx_dev = _find_rx_device(ctx, args.rx_device)
    if phy is None or rx_dev is None:
        raise RuntimeError(f"Cannot find IIO devices: phy={args.phy_device}, rx={args.rx_device or 'auto'}")

    for lo_name in ("altvoltage1", "altvoltage0"):
        lo = phy.find_channel(lo_name, True)
        if lo is not None and _set_attr(lo, "frequency", args.center_freq_hz):
            break

    _set_attr(phy, "sampling_frequency", args.sample_rate_hz)
    ch0 = phy.find_channel("voltage0", False)
    if ch0 is not None:
        _set_attr(ch0, "sampling_frequency", args.sample_rate_hz)

    for ch in _input_channels(rx_dev):
        ch.enabled = False
    available = {str(getattr(ch, "id", "") or getattr(ch, "name", "")): ch for ch in _input_channels(rx_dev)}
    requested = [token.strip() for token in args.channels.split(",") if token.strip()]
    missing = [name for name in requested if name not in available]
    if missing:
        raise RuntimeError(f"Requested channels not available: {missing}; available={sorted(available)}")
    for name in requested:
        available[name].enabled = True

    rxbuf = iio.Buffer(rx_dev, int(args.buffer_size), False)
    try:
        rxbuf.refill()
        raw = np.frombuffer(rxbuf.read(), dtype=np.int16).copy()
    finally:
        try:
            rxbuf.cancel()
        except Exception:
            pass
        del rxbuf
        for ch in _input_channels(rx_dev):
            try:
                ch.enabled = False
            except Exception:
                pass

    out_npz = Path(args.out_npz)
    out_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_npz,
        raw_i16=raw,
        uri=args.uri,
        center_freq_hz=int(args.center_freq_hz),
        sample_rate_hz=int(args.sample_rate_hz),
        buffer_size=int(args.buffer_size),
        channels=np.asarray(requested),
    )

    reference = dataclass_to_dict(power_frame_reference(raw, use_iq=(len(requested) >= 2)))
    payload = {
        "timestamp_sec": time.time(),
        "operation": "raw_i16_one_shot_reference_capture",
        "npz": str(out_npz),
        "raw_i16_length": int(raw.size),
        "channels": requested,
        "uri": args.uri,
        "center_freq_hz": int(args.center_freq_hz),
        "sample_rate_hz": int(args.sample_rate_hz),
        "buffer_size": int(args.buffer_size),
        "reference": reference,
        "note": (
            "This raw IIO capture is not hardware-synchronized to the FPGA register frame. "
            "Use it for scale/statistical sanity checks until a same-window capture path exists."
        ),
    }
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
