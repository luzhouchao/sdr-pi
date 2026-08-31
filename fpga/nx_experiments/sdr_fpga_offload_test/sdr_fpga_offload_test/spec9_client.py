from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol


SPEC9_VERSION = 0x53504339
SPEC9_CAPABILITY = 0x0000000F
SPEC9_BUILD_ID = 0x53390001
SPEC9_ABI_VERSION = 0x00010003
SPEC9_BIN_COUNT = 4

SUM9_VERSION = 0x53554D39
SUM9_ABI_VERSION = 0x00010003
SUM9_CAPABILITY = 0x000007FF
SUM9_BUILD_ID = 0x56390001
QUA9_VERSION = 0x51554139
QUA9_CAPABILITY = 0x0000000F
QUA9_BUILD_ID = 0x51390001
AGG9_VERSION = 0x41474739
AGG9_CAPABILITY = 0x0000001F
AGG9_BUILD_ID = 0x41390001

SPEC9_OFFSETS = {
    "spec_version": 0x200,
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
    "spec_reserved0": 0x23C,
    "spec_bin_count": 0x2F0,
    "spec_capability": 0x2F4,
    "spec_build_id": 0x2F8,
    "spec_abi_version": 0x2FC,
}

V9_ID_OFFSETS = {
    "summary_version": 0x040,
    "abi_version": 0x0EC,
    "capability": 0x0F0,
    "build_id": 0x0FC,
    "quality_version": 0x100,
    "quality_capability": 0x138,
    "quality_build_id": 0x13C,
    "agg_version": 0x180,
    "agg_capability": 0x1F4,
    "agg_build_id": 0x1F8,
}


class RegisterTransport(Protocol):
    def read32(self, offset: int) -> int:
        ...

    def write32(self, offset: int, value: int) -> None:
        ...


@dataclass(frozen=True)
class Spec9Snapshot:
    version: int
    flags: int
    frame_id: int
    samples: int
    peak_bin: int
    peak_power: int
    total_power: int
    noise_floor: int
    prominence: int
    bins: tuple[int, int, int, int]
    limit_flags: int
    rx_mask: int
    bin_count: int
    cap: int
    build_id: int
    abi_version: int

    @property
    def valid(self) -> bool:
        return bool(self.flags & (1 << 0))

    @property
    def busy(self) -> bool:
        return bool(self.flags & (1 << 1))

    @property
    def overflow_or_saturate(self) -> bool:
        return bool(self.flags & (1 << 2))

    @property
    def sample_count_mismatch(self) -> bool:
        return bool(self.flags & (1 << 3))

    @property
    def low_quality(self) -> bool:
        return bool(self.flags & (1 << 4))

    @property
    def broadband_like(self) -> bool:
        return bool(self.flags & (1 << 5))

    @property
    def dominant_tone_like(self) -> bool:
        return bool(self.flags & (1 << 6))

    @property
    def stale(self) -> bool:
        return bool(self.flags & (1 << 7))

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload.update(
            {
                "version_hex": f"0x{self.version:08X}",
                "flags_hex": f"0x{self.flags:08X}",
                "limit_flags_hex": f"0x{self.limit_flags:08X}",
                "cap_hex": f"0x{self.cap:08X}",
                "build_id_hex": f"0x{self.build_id:08X}",
                "abi_version_hex": f"0x{self.abi_version:08X}",
                "valid": self.valid,
                "busy": self.busy,
                "overflow_or_saturate": self.overflow_or_saturate,
                "sample_count_mismatch": self.sample_count_mismatch,
                "low_quality": self.low_quality,
                "broadband_like": self.broadband_like,
                "dominant_tone_like": self.dominant_tone_like,
                "stale": self.stale,
            }
        )
        return payload


class Spec9Client:
    def __init__(self, transport: RegisterTransport) -> None:
        self.transport = transport

    def _read(self, name: str) -> int:
        return self.transport.read32(SPEC9_OFFSETS[name])

    def _write_offset(self, offset: int, value: int) -> None:
        self.transport.write32(offset, value)

    def read_id_registers(self) -> dict[str, int]:
        return {name: self.transport.read32(offset) for name, offset in V9_ID_OFFSETS.items()}

    def assert_v9a_ids(self) -> None:
        expected = {
            "summary_version": SUM9_VERSION,
            "abi_version": SUM9_ABI_VERSION,
            "capability": SUM9_CAPABILITY,
            "build_id": SUM9_BUILD_ID,
            "quality_version": QUA9_VERSION,
            "quality_capability": QUA9_CAPABILITY,
            "quality_build_id": QUA9_BUILD_ID,
            "agg_version": AGG9_VERSION,
            "agg_capability": AGG9_CAPABILITY,
            "agg_build_id": AGG9_BUILD_ID,
        }
        actual = self.read_id_registers()
        for name, value in expected.items():
            if actual[name] != value:
                raise RuntimeError(f"Expected {name}=0x{value:08X}, got 0x{actual[name]:08X}")

    def trigger_frame(self, frame_len: int) -> None:
        if frame_len < 1 or frame_len > 65535:
            raise ValueError("SPEC9 frame_len must be 1..65535")
        self._write_offset(0x004, frame_len)
        self._write_offset(0x000, 0x00000002)
        self._write_offset(0x000, 0x00000001)

    def read_snapshot(self) -> Spec9Snapshot:
        values = {name: self._read(name) for name in SPEC9_OFFSETS}
        return Spec9Snapshot(
            version=values["spec_version"],
            flags=values["spec_flags"],
            frame_id=values["spec_frame_id"],
            samples=values["spec_samples"],
            peak_bin=values["spec_peak_bin"],
            peak_power=values["spec_peak_power"],
            total_power=values["spec_total_power"],
            noise_floor=values["spec_noise_floor"],
            prominence=values["spec_prominence"],
            bins=(
                values["spec_bin0_power"],
                values["spec_bin1_power"],
                values["spec_bin2_power"],
                values["spec_bin3_power"],
            ),
            limit_flags=values["spec_limit_flags"],
            rx_mask=values["spec_rx_mask"],
            bin_count=values["spec_bin_count"],
            cap=values["spec_capability"],
            build_id=values["spec_build_id"],
            abi_version=values["spec_abi_version"],
        )

    def assert_spec9(self, snapshot: Spec9Snapshot | None = None) -> Spec9Snapshot:
        snap = snapshot if snapshot is not None else self.read_snapshot()
        expected = {
            "version": SPEC9_VERSION,
            "bin_count": SPEC9_BIN_COUNT,
            "cap": SPEC9_CAPABILITY,
            "build_id": SPEC9_BUILD_ID,
            "abi_version": SPEC9_ABI_VERSION,
        }
        actual = {
            "version": snap.version,
            "bin_count": snap.bin_count,
            "cap": snap.cap,
            "build_id": snap.build_id,
            "abi_version": snap.abi_version,
        }
        for name, value in expected.items():
            if actual[name] != value:
                raise RuntimeError(f"Expected SPEC9 {name}=0x{value:08X}, got 0x{actual[name]:08X}")
        return snap
