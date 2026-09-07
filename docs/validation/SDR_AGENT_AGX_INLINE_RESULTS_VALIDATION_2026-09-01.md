# SDR Agent AGX inline-IQ results validation

Date: 2026-09-01

AGX Web: `http://127.0.0.1:8787`

SDR endpoint: `192.168.1.10:43110`

Model: OpenCode Go / `deepseek-v4-flash`

## Production architecture and deployment

The deployed production path is receive-only and does not use custom FPGA
aggregation:

```text
P201 AD9361 -> Linux IIO -> sdrd inline IQ -> AGX aggregation -> SQLite/Web/SigMF -> model
```

The default `sdrd` build excluded `sdrd_fpga.c` and
`p201_native_mmio.c`, linked the fail-closed FPGA stub, and served with
`fpga_backend=disabled`. Read-only `HELLO`, `CAPABILITIES`, `HEALTH` and `QUIT`
reported radio control and raw-IQ capture available while every FPGA identity,
mapping and aggregation capability remained false.

The compatible ARMv7 build used the official Arm GNU 8.2-2018.08 hard-float
sysroot in an amd64 container on AGX. The toolchain archive SHA-256 was
`5b3f20e1327edc3073e545a5bd3d15f33e7f94181ff4e37a76e95924c1b439b9`.
The deployment gate proved ELF32 ARM EABI5 hard-float with
`/lib/ld-linux-armhf.so.3`; the only required symbol versions were
`GLIBC_2.4`, `GLIBC_2.7` and `GLIBC_2.17` against the P201 glibc 2.28 target.
No `p201_*`, MMIO or FPGA-aggregate symbol was linked.

Deployed artifacts:

```text
9a83a57f8e8eaff9399014dd7c68f32b17fbb8471719e2d1e0be0a02775a810a  P201 sdrd
670a5e382660396b595560e07a4539d2512efcd04d3c8478b2170adafedc1253  AGX sdr-agent
73effbcb5692ccfde304754d3a876bafa30aae15e81e3627664fc7bd3dc6f05d  AGX sdr-agent-web-console
```

P201 replacement followed the single-instance stop/poll/atomic-replace/start
gate. The final daemon had one PID (`19666`) and one private-link listener on
`192.168.1.10:43110`. The previous compatible deployment was retained as a
rollback release.

## Bounded live plan

Before capture, AGX had 849,547,386,880 bytes available. Both completed scans
were fixed at:

```text
range=90–106 MHz
centers=90, 98, 106 MHz
points=3
sample_rate=10 MS/s
rf_bandwidth=10 MHz
gain=20 dB manual, with numeric readback
dwell=5 ms/point
samples=4096 complex-int16/point
maximum_received_bytes=3 * 4096 * 4 = 49,152
```

The AGX result root was `/var/lib/sdrharness/web-console/`. P201 used one
transient `/tmp/sdr-agent-dev/agx-sweep-*` directory per point and removed it
after successful transfer. `/stop` remained directly available throughout.

## Real SDR, AGX, Web and model results

Python Playwright drove the deployed page in headless Chromium. The page's
intentional long-lived SSE connection precludes `networkidle`, so validation
waited for DOM and `/api/state` readiness. No page or browser-console errors
were observed.

With raw-IQ persistence disabled, the P201 transferred exactly 49,152 bytes,
AGX produced three power points and zero candidates, SQLite/Web showed the real
SVG trace and “本次未保存原始 IQ”, and the real model replied from the latest
candidate observation. The result was then deleted with the Web “删除这次采集”
button; the database row disappeared and no dataset files existed to delete.

With raw-IQ persistence enabled, the same bounded scan completed in 1,063 ms
with a -43.646 dBFS noise baseline and zero candidates. AGX retained exactly
one SigMF pair:

```text
datatype=ci16_le
data_bytes=49,152
captures=3
sample_starts=0, 4096, 8192
center_frequencies=90, 98, 106 MHz
file_mode=0600
```

The aggregate-results page survived a Web restart and showed one history row,
three real points, the SVG power path, candidate table, fixed gain, elapsed
time, noise line and “已保存 48 KiB 原始 IQ · ci16_le”. This user-visible result
and its indexed SigMF pair remain available for manual deletion.

The model transparency panel displayed the actual 740-byte PlanningContext,
the 65-byte Rust validation basis and 165 bytes of reasoning genuinely supplied
by the upstream. Reasoning was collapsed by default. The fixed system prompt
was not present in the UI payload. A provider turn with no reasoning continues
to omit the reasoning control rather than invent text.

## Cancellation and restoration

The browser started the configured 743-point 70 MHz–6 GHz survey and immediately
used the Web “立即停止” button. The Controller reported:

```text
首次扫频已取消并完成恢复：remote_error: capture_failed_restored
```

The first cancellation exposed an empty per-point directory after the partial
file had already been removed. The IIO Adapter failure path was corrected to
remove that empty directory as well, the no-FPGA daemon was rebuilt and
redeployed, and the same browser cancellation was repeated. The final check
found no `/tmp/sdr-agent-dev/agx-sweep-*` directories. A read-only radio probe
proved restoration to the pre-test state:

```text
center_hz=2400000000
sample_rate_hz=30720000
rf_bandwidth_hz=18000000
gain_mode=slow_attack
scan_channel_mask=0
```

The original two Web conversations and the mode-`0600` provider configuration
were restored byte-for-byte from pre-test hashes. API credentials were never
printed, copied into logs or committed.

## Tests

```text
sdrd native tests: pass
default ENABLE_FPGA=0 native build and symbol gate: pass
controller tests: 44 library + 4 CLI passed
controller clippy -D warnings: pass
web-console tests: 15 passed
web-console clippy -D warnings: pass
planner-worker tests: 37 passed
project Skill quick_validate: pass
browser completed scans, model reply, SVG, settings, delete, trace and cancel: pass
```

## Cleanup gate

The user-visible SQLite result and its managed SigMF pair are application data,
not development staging, and were intentionally retained behind the Web manual
delete action. All AGX/P201 feature staging, the incompatible first P201
release, browser scripts/screenshots and downloaded cross-toolchain artifacts
were removed after final verification. The current and rollback P201 releases,
deployed AGX binaries, SQLite result and managed SigMF files were not removed.
