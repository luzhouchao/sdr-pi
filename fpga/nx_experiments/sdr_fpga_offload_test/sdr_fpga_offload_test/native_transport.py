from __future__ import annotations

import ctypes
import errno
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .sdr_kernel_contract import TAP_BASE


TAP_SPAN_BYTES = 0x00010000

MMIO_OPEN_PLAIN = 0
MMIO_OPEN_DEVMEM = 1 << 0
MMIO_OPEN_READ_ONLY = 1 << 1
MMIO_OPEN_SYNC = 1 << 2

SUM8_STATUS_INVALID_IDENTITY = 1 << 0
SUM8_STATUS_AGG_NOT_DONE = 1 << 1
SUM8_STATUS_AGG_OVERFLOW = 1 << 2
SUM8_STATUS_STALE_FRAME = 1 << 3
SUM8_STATUS_SAMPLE_MISMATCH = 1 << 4
SUM8_STATUS_TARGET_MISMATCH = 1 << 5


class _U96Words(ctypes.Structure):
    _fields_ = [
        ("lo", ctypes.c_uint32),
        ("mid", ctypes.c_uint32),
        ("hi", ctypes.c_uint32),
    ]


class _NativeSum8Snapshot(ctypes.Structure):
    _fields_ = [
        ("summary_version", ctypes.c_uint32),
        ("abi_version", ctypes.c_uint32),
        ("capability_bitmap", ctypes.c_uint32),
        ("build_id", ctypes.c_uint32),
        ("quality_version", ctypes.c_uint32),
        ("quality_capability", ctypes.c_uint32),
        ("quality_build_id", ctypes.c_uint32),
        ("agg_sequence", ctypes.c_uint32),
        ("agg_version", ctypes.c_uint32),
        ("agg_control", ctypes.c_uint32),
        ("agg_target", ctypes.c_uint32),
        ("agg_frames", ctypes.c_uint32),
        ("agg_samples", ctypes.c_uint32),
        ("rx0_corr_power_num", _U96Words),
        ("rx1_corr_power_num", _U96Words),
        ("corr_cross_re_num", _U96Words),
        ("corr_cross_im_num", _U96Words),
        ("rx0_raw_power", _U96Words),
        ("rx1_raw_power", _U96Words),
        ("rx0_clip_count", ctypes.c_uint32),
        ("rx1_clip_count", ctypes.c_uint32),
        ("rx0_zero_cross_count", ctypes.c_uint32),
        ("rx1_zero_cross_count", ctypes.c_uint32),
        ("same_sign_count", ctypes.c_uint32),
        ("agg_last_frame", ctypes.c_uint32),
        ("agg_capability", ctypes.c_uint32),
        ("agg_build_id", ctypes.c_uint32),
        ("agg_limit", ctypes.c_uint32),
        ("status_flags", ctypes.c_uint32),
        ("elapsed_ns", ctypes.c_uint64),
    ]


@dataclass(frozen=True)
class U96Words:
    lo: int
    mid: int
    hi: int

    @property
    def unsigned(self) -> int:
        return ((self.hi & 0xFFFFFFFF) << 64) | ((self.mid & 0xFFFFFFFF) << 32) | (self.lo & 0xFFFFFFFF)

    @property
    def signed(self) -> int:
        value = self.unsigned
        return value - (1 << 96) if value & (1 << 95) else value


@dataclass(frozen=True)
class NativeSum8Snapshot:
    summary_version: int
    abi_version: int
    capability_bitmap: int
    build_id: int
    quality_version: int
    quality_capability: int
    quality_build_id: int
    agg_sequence: int
    agg_version: int
    agg_control: int
    agg_target: int
    agg_frames: int
    agg_samples: int
    rx0_corr_power_num: U96Words
    rx1_corr_power_num: U96Words
    corr_cross_re_num: U96Words
    corr_cross_im_num: U96Words
    rx0_raw_power: U96Words
    rx1_raw_power: U96Words
    rx0_clip_count: int
    rx1_clip_count: int
    rx0_zero_cross_count: int
    rx1_zero_cross_count: int
    same_sign_count: int
    agg_last_frame: int
    agg_capability: int
    agg_build_id: int
    agg_limit: int
    status_flags: int
    elapsed_ns: int

    @property
    def done(self) -> bool:
        return bool(self.agg_control & (1 << 4))

    @property
    def overflow(self) -> bool:
        return bool(self.status_flags & SUM8_STATUS_AGG_OVERFLOW)

    @property
    def stale(self) -> bool:
        return bool(self.status_flags & SUM8_STATUS_STALE_FRAME)

    @property
    def invalid(self) -> bool:
        return bool(self.status_flags & SUM8_STATUS_INVALID_IDENTITY)

    @property
    def passed(self) -> bool:
        return self.status_flags == 0

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["done"] = self.done
        payload["overflow"] = self.overflow
        payload["stale"] = self.stale
        payload["invalid"] = self.invalid
        payload["passed"] = self.passed
        payload["status_hex"] = f"0x{self.status_flags:08X}"
        payload["elapsed_sec"] = self.elapsed_ns / 1_000_000_000.0
        return payload


def default_library_candidates() -> list[Path]:
    env_path = os.environ.get("P201_SDR_NATIVE_LIB")
    package_root = Path(__file__).resolve().parents[1]
    candidates = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(
        [
            package_root / "native" / "build" / "libp201_native_mmio.so",
            package_root / "native" / "libp201_native_mmio.so",
        ]
    )
    return candidates


def _load_library(library_path: str | Path | None) -> ctypes.CDLL:
    if library_path is not None:
        return ctypes.CDLL(str(library_path))
    for candidate in default_library_candidates():
        if candidate.exists():
            return ctypes.CDLL(str(candidate))
    searched = ", ".join(str(item) for item in default_library_candidates())
    raise FileNotFoundError(f"Cannot find libp201_native_mmio.so; searched: {searched}")


def _word(words: _U96Words) -> U96Words:
    return U96Words(lo=int(words.lo), mid=int(words.mid), hi=int(words.hi))


def _snapshot(raw: _NativeSum8Snapshot) -> NativeSum8Snapshot:
    return NativeSum8Snapshot(
        summary_version=int(raw.summary_version),
        abi_version=int(raw.abi_version),
        capability_bitmap=int(raw.capability_bitmap),
        build_id=int(raw.build_id),
        quality_version=int(raw.quality_version),
        quality_capability=int(raw.quality_capability),
        quality_build_id=int(raw.quality_build_id),
        agg_sequence=int(raw.agg_sequence),
        agg_version=int(raw.agg_version),
        agg_control=int(raw.agg_control),
        agg_target=int(raw.agg_target),
        agg_frames=int(raw.agg_frames),
        agg_samples=int(raw.agg_samples),
        rx0_corr_power_num=_word(raw.rx0_corr_power_num),
        rx1_corr_power_num=_word(raw.rx1_corr_power_num),
        corr_cross_re_num=_word(raw.corr_cross_re_num),
        corr_cross_im_num=_word(raw.corr_cross_im_num),
        rx0_raw_power=_word(raw.rx0_raw_power),
        rx1_raw_power=_word(raw.rx1_raw_power),
        rx0_clip_count=int(raw.rx0_clip_count),
        rx1_clip_count=int(raw.rx1_clip_count),
        rx0_zero_cross_count=int(raw.rx0_zero_cross_count),
        rx1_zero_cross_count=int(raw.rx1_zero_cross_count),
        same_sign_count=int(raw.same_sign_count),
        agg_last_frame=int(raw.agg_last_frame),
        agg_capability=int(raw.agg_capability),
        agg_build_id=int(raw.agg_build_id),
        agg_limit=int(raw.agg_limit),
        status_flags=int(raw.status_flags),
        elapsed_ns=int(raw.elapsed_ns),
    )


class NativeMmioTransport:
    """ctypes RegisterTransport for the P201 SUM8/AGG8 mmap backend."""

    def __init__(
        self,
        *,
        mode: str = "devmem",
        device: str | Path = "/dev/mem",
        library_path: str | Path | None = None,
        base: int = TAP_BASE,
        span: int = TAP_SPAN_BYTES,
        read_only: bool = False,
        sync: bool = True,
    ) -> None:
        self._lib = _load_library(library_path)
        self._configure_abi()
        self._ctx = self._lib.p201_mmio_create()
        if not self._ctx:
            raise MemoryError("p201_mmio_create returned NULL")

        flags = MMIO_OPEN_READ_ONLY if read_only else 0
        if sync:
            flags |= MMIO_OPEN_SYNC
        if mode == "devmem":
            flags |= MMIO_OPEN_DEVMEM
            target_offset = int(base)
        elif mode in {"uio", "file"}:
            target_offset = 0
        else:
            self.close()
            raise ValueError("mode must be one of: devmem, uio, file")

        rc = self._lib.p201_mmio_open(
            self._ctx,
            os.fsencode(device),
            ctypes.c_uint64(target_offset),
            ctypes.c_size_t(int(span)),
            ctypes.c_uint32(flags),
        )
        self._check_rc(rc, "p201_mmio_open")

    def _configure_abi(self) -> None:
        self._lib.p201_mmio_create.argtypes = []
        self._lib.p201_mmio_create.restype = ctypes.c_void_p
        self._lib.p201_mmio_destroy.argtypes = [ctypes.c_void_p]
        self._lib.p201_mmio_destroy.restype = None
        self._lib.p201_mmio_close.argtypes = [ctypes.c_void_p]
        self._lib.p201_mmio_close.restype = None
        self._lib.p201_mmio_open.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_uint64,
            ctypes.c_size_t,
            ctypes.c_uint32,
        ]
        self._lib.p201_mmio_open.restype = ctypes.c_int
        self._lib.p201_mmio_read32.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
        self._lib.p201_mmio_read32.restype = ctypes.c_int
        self._lib.p201_mmio_write32.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
        self._lib.p201_mmio_write32.restype = ctypes.c_int
        self._lib.p201_mmio_reset_stale_state.argtypes = [ctypes.c_void_p]
        self._lib.p201_mmio_reset_stale_state.restype = None
        self._lib.p201_sum8_arm_aggregate.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
        self._lib.p201_sum8_arm_aggregate.restype = ctypes.c_int
        self._lib.p201_sum8_poll_done.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint64),
        ]
        self._lib.p201_sum8_poll_done.restype = ctypes.c_int
        self._lib.p201_sum8_read_snapshot.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(_NativeSum8Snapshot),
        ]
        self._lib.p201_sum8_read_snapshot.restype = ctypes.c_int

    @staticmethod
    def _check_rc(rc: int, operation: str) -> None:
        if rc == 0:
            return
        err = -int(rc)
        name = errno.errorcode.get(err, "ERR")
        raise OSError(err, f"{operation} failed with {name}")

    def close(self) -> None:
        ctx = getattr(self, "_ctx", None)
        if ctx:
            self._lib.p201_mmio_destroy(ctx)
            self._ctx = None

    def __enter__(self) -> "NativeMmioTransport":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def read32(self, offset: int) -> int:
        value = ctypes.c_uint32()
        rc = self._lib.p201_mmio_read32(self._ctx, ctypes.c_uint32(offset), ctypes.byref(value))
        self._check_rc(rc, "p201_mmio_read32")
        return int(value.value)

    def write32(self, offset: int, value: int) -> None:
        rc = self._lib.p201_mmio_write32(self._ctx, ctypes.c_uint32(offset), ctypes.c_uint32(value & 0xFFFFFFFF))
        self._check_rc(rc, "p201_mmio_write32")

    def reset_stale_state(self) -> None:
        self._lib.p201_mmio_reset_stale_state(self._ctx)

    def arm_aggregate(self, frame_len: int, agg_frames: int) -> None:
        rc = self._lib.p201_sum8_arm_aggregate(self._ctx, ctypes.c_uint32(frame_len), ctypes.c_uint32(agg_frames))
        self._check_rc(rc, "p201_sum8_arm_aggregate")

    def poll_done(self, *, timeout_us: int = 500_000, poll_sleep_us: int = 1_000) -> int:
        elapsed = ctypes.c_uint64()
        rc = self._lib.p201_sum8_poll_done(
            self._ctx,
            ctypes.c_uint32(timeout_us),
            ctypes.c_uint32(poll_sleep_us),
            ctypes.byref(elapsed),
        )
        self._check_rc(rc, "p201_sum8_poll_done")
        return int(elapsed.value)

    def read_sum8_snapshot(self, *, expected_frame_len: int = 0, expected_agg_frames: int = 0) -> NativeSum8Snapshot:
        raw = _NativeSum8Snapshot()
        rc = self._lib.p201_sum8_read_snapshot(
            self._ctx,
            ctypes.c_uint32(expected_frame_len),
            ctypes.c_uint32(expected_agg_frames),
            ctypes.byref(raw),
        )
        self._check_rc(rc, "p201_sum8_read_snapshot")
        return _snapshot(raw)
