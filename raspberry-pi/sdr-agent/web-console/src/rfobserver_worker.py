"""Bounded, one-window CPU adapter for the vendored RFObserver PSD implementation."""
import json
import os
import sys
import types

import numpy as np

samples = int(sys.argv[1])
rate = int(sys.argv[2])
center = int(sys.argv[3])
if not (256 <= samples <= 65536 and 1 <= rate <= 100_000_000 and center > 0):
    raise ValueError("invalid bounded analysis input")
raw = sys.stdin.buffer.read(samples * 4 + 1)
if len(raw) != samples * 4:
    raise ValueError("IQ length mismatch")

# Only compute_psd_grid is used. Its sibling PSDData model is imported by the
# unmodified upstream module but is not needed by this calculation.
models = types.ModuleType("rfobserver.models")
models.PSDData = object
package = types.ModuleType("rfobserver")
package.__path__ = []
sys.modules["rfobserver"] = package
sys.modules["rfobserver.models"] = models
spectral = types.ModuleType("rfobserver_spectral")
sys.modules[spectral.__name__] = spectral
exec(os.environ["SDR_RFOBS_SPECTRAL"], spectral.__dict__)

iq = np.frombuffer(raw, dtype="<i2").reshape(-1, 2).astype(np.float32)
iq = (iq[:, 0] + 1j * iq[:, 1]) / np.float32(32768.0)
# At most 64 time slices; each slice is an independent portion of this one
# capture. No timestamp or continuity is inferred across tuning operations.
slice_samples = max(256, ((samples + 63) // 64 + 127) // 128 * 128)
resolution_ms = (slice_samples + 1) / rate * 1000.0
config = spectral.PSDGridConfig(num_bins=256, time_resolution_ms=resolution_ms,
                                overlap=0.5, num_workers=1, backend="cpu")
result = spectral.compute_psd_grid(iq, rate, config)
if result.grid.shape[0] > 64 or result.grid.shape[1] != 256 or not np.isfinite(result.grid).all():
    raise ValueError("unexpected PSD shape or nonfinite values")
output = {"schema_version": 1, "algorithm": "RFObserver PSD CPU / Hann / 256 bins",
          "center_hz": center, "sample_rate_hz": rate, "samples": samples,
          "units": "dBFS/Hz, uncalibrated", "time_axis_ms": (result.time_axis * 1000).tolist(),
          "frequency_offsets_hz": result.freq_axis.tolist(), "grid_db": result.grid.tolist(),
          "note": "one capture only; no DC removal; times are relative to capture start"}
sys.stdout.write(json.dumps(output, allow_nan=False, separators=(",", ":")))
