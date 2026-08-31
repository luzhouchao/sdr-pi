# `sdrd` local IIO Adapter validation

Date: 2026-08-31

## Outcome

The controlled `sdrd` path now has a production-shaped C11 Adapter for the
SDR-local libiio 0.21 runtime. It owns one local context for the daemon lifetime,
maps the AD9361 RX LO and RX0 PHY channels, snapshots the four receive scan
channels, creates one reusable session buffer, and writes only bounded
complex-int16 captures below the configured development root.

This feature was validated manually from a temporary directory. It was not
installed, enabled at boot, or allowed to replace IIOD. No FPGA register,
`BOOT.bin`, transmit channel, or persistent radio configuration was changed.

## Target and build compatibility

- Target: ARMv7 hard-float Linux, libiio 0.21, maximum exported GLIBC 2.28.
- The SDR provides `libiio.so.0.21` but no compiler or libiio headers.
- The first static Docker artifact correctly failed the read-only Adapter probe
  at the static/dynamic glibc boundary. It never opened or wrote the radio.
- The Xilinx SDK 2019.1 hard-float dynamic artifact required GLIBC 2.17 and
  loaded the target libiio successfully.
- Final stripped development artifact SHA-256:
  `93af109d311bae4d65c55b8fe320c5005e6a5a8a0e020819c021776419236012`.
- That exact final artifact passed a second SDR-local read-only radio probe after
  the bounded-path hardening change.

The reproducible build entry point is
[`../sdrd/scripts/build-armhf-xilinx.ps1`](../sdrd/scripts/build-armhf-xilinx.ps1).
The Docker static build remains shadow-only.

## Read-only snapshot

Before mutation, `--probe-radio` reported:

```text
center_hz=2452000000
sample_rate_hz=2100000
rf_bandwidth_hz=2000000
gain_mode=slow_attack
scan_channel_mask=0
```

The four `cf-ad9361-lpc` scan enables independently read back as zero.

## Bounded execution

The approved development plan used RX0 only, 2442 MHz center frequency,
2.1 MS/s sample rate, 2 MHz RF bandwidth, `slow_attack`, a 5 ms settle delay,
4096 complex-int16 samples, and a 16,384-byte hard request cap. Free space under
the SDR tmpfs exceeded 500 MiB, while the configured global cap remained 64 MiB.

The first apply attempt read back 2,441,999,998 Hz, a -2 Hz AD9361 synthesizer
quantization difference. Strict per-Hz comparison rejected the profile and the
session restored every original field. The implementation now permits at most
10 Hz of LO readback quantization while retaining the original range checks.

The complete retry returned `status=ok` for session ownership, atomic profile
apply, bounded capture, execution status, stop/restore, and quit. One retained
summary from the first successful 16 KiB capture was:

```text
complex_samples=4096
sha256=de144cb8139448255d8c95ffb43a77dc7d13d94fbb29fadc67a74f44a30e3927
mean_i=-0.3876953125
mean_q=0.740234375
rms=495.9884755426216
peak_abs=953
zero_pairs=0
clipped_components=0
```

The raw file itself was deleted and was never added to Git.

## Restore and known warning

After both the intentional readback rejection and successful captures, the
original LO, sample rate, bandwidth, gain mode, and zero scan mask read back
exactly. The temporary server was stopped and no service was installed.

libiio 0.21 prints `Error during buffer disable: Success (0)` while destroying
this local buffer. The same target previously showed a buffer-disable cleanup
warning in the high-resolution helper. It did not change the successful return,
state readback, IIOD availability, or scan mask, but it remains a documented
compatibility item for repeated-session and in-flight-cancel testing.

## Data and artifact cleanup

- SDR raw IQ files were deleted immediately after their bounded summaries.
- `/tmp/sdr-agent-dev/sdrd-iio-adapter-v1/` was resolved, deleted, and verified
  absent on the SDR.
- `/var/tmp/sdr-agent-dev/sdrd-iio-adapter-v1/` was resolved, deleted, and
  verified absent on the Pi relay.
- Workstation native and cross-build directories were deleted after final tests
  and artifact metadata collection.
