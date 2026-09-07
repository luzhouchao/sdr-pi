# P201 → AGX receive-profile validation (2026-09-02)

## Scope and safety

This validation characterized the current receive-only P201 Linux/IIO and
SDRD/1 path. It did not transmit, write FPGA registers, change `BOOT.bin`,
replace persistent files, alter boot behavior, or start a second `sdrd`.

- Route: direct AGX wired route, `192.168.1.20` → `192.168.1.10`.
- Target: `pzp201pro`, ARMv7 Linux 5.10; the existing controlled `sdrd` PID was
  reused on private port 43110.
- Center: 2.45 GHz; RX0 only; fixed manual gain 20 dB.
- Development cap: 64 MiB; actual processed IQ was 36,323,328 bytes.
- AGX staging: `/var/tmp/sdrharness-dev/p201-link-profile-20260902/`.
- No raw IQ was retained or printed. Inline payloads were decoded only to
  validate exact length and immediately discarded.

Before execution, AGX had 849,429,065,728 bytes free and P201 `/tmp` had
514,608 KiB free. `HELLO`, `CAPABILITIES` and `HEALTH` reported controlled
receive operation, IIO visibility, a healthy radio and a 64 MiB capture cap.

## Advertised versus useful limits

The live IIO attributes reported:

- tuning: 70 MHz–6 GHz;
- sampling: 2.083333–30.72 MS/s;
- RX RF bandwidth: up to 56 MHz (the same attribute query also exposed the
  separate 40 MHz direction range);
- deployed `sdrd`: sample-rate cap 30.72 MS/s and RF-bandwidth cap 56 MHz.

An RF filter bandwidth above the delivered complex sample rate does not create
additional usable digital spectrum. The controlled interface therefore keeps
`rf_bandwidth_hz <= sample_rate_hz`. On this image the maximum useful settable
short-window profile is consequently 30.72 MHz, not the AD9361 analog-filter
headline of 56 MHz.

The exact advertised lower sample rate, 2.083333 MS/s, failed profile apply and
the service confirmed restoration. A 2.1 MS/s sample rate with 2.0 MHz RF
bandwidth applied, captured 4,096 samples with zero clipping/status flags and
restored successfully. Production planning therefore uses 2.1 MS/s as the
measured lower boundary.

## Bounded profile ladder

Each successful rung processed 1,048,576 complex-int16 samples through legacy
`CAPTURE_POWER`; every result reported zero clipping/status flags and confirmed
radio restoration.

| Set sample/RF bandwidth | Apply/readback | P201 elapsed | Client effective processing |
|---:|:---:|---:|---:|
| 2.083333 MHz | failed, restored | — | — |
| 5 MHz | exact | 210.231 ms | 4.884 MS/s |
| 10 MHz | exact | 145.867 ms | 6.972 MS/s |
| 20 MHz | exact | 146.200 ms | 6.958 MS/s |
| 25 MHz | exact | 144.828 ms | 7.028 MS/s |
| 30 MHz | exact | 147.567 ms | 6.895 MS/s |
| 30.72 MHz | exact | 145.077 ms | 7.022 MS/s |

This scalar path processes only about 7 MS/s regardless of the configured
radio rate. It must not be represented as proof of sustained lossless
30.72-MS/s capture and should not be used for production AGX aggregation.

## Inline P201 → AGX behavior

At a set/read-back profile of 30.72 MS/s and 30.72 MHz, 32 sequential maximum
inline windows transferred 8 MiB in 36.045 seconds:

- raw IQ payload throughput: 0.222 MiB/s (1.862 Mb/s);
- per-256-KiB window: 1.111–1.139 seconds;
- sequences: continuous 209–240;
- every window passed SDRD's exact byte, zero-drop and zero-overflow contract;
- final stop reported restoration.

Window latency scaled linearly with payload size:

| Complex samples | Payload | Median latency | Raw payload rate |
|---:|---:|---:|---:|
| 4,096 | 16 KiB | 71.541 ms | 1.830 Mb/s |
| 16,384 | 64 KiB | 280.788 ms | 1.865 Mb/s |
| 65,536 | 256 KiB | 1,118.139 ms | 1.873 Mb/s |

The bottleneck is therefore not the nominal 1-GbE link. The current SDR-side
per-request path creates/captures a bounded IIO buffer, writes a transient file,
base64-encodes it into JSON, transfers it, then deletes it. This is suitable for
small 4,096-sample survey windows but not sustained raw-IQ streaming.

## Resulting planning boundary

- The Planner may select center, step, sample rate, RF bandwidth and dwell, but
  Rust must keep 2.1–30.72 MS/s, `200 kHz <= RF bandwidth <= sample rate`, the
  dynamic Web limits, 768 points and 300 seconds.
- The existing Web `max_bandwidth_hz=10 MHz` remains the stricter production
  limit until sustained 5/10-MS/s tests include inter-window loss, CPU, thermal,
  overload and cancellation evidence.
- 30.72 MHz is documented only as a successfully applied bounded short-window
  ceiling. It is not advertised as sustained throughput.
- Fixed gain remains Controller/Web-owned so sweeps stay numerically comparable.

After the tests, `HEALTH` remained healthy, every session confirmed
restoration, and no feature directory remained under the P201
`/tmp/sdr-agent-dev` root.

## Deployed Planner/model closure

The revised Controller, Web console and Planner Worker were deployed on AGX
with these SHA-256 hashes:

```text
a786bc2e666d8edfa1e53d010280a86c2e72cb320f71de110c43161cb44f2f9b  sdr-agent
f47d6af7572dd0d6ad04691b6dfc7e6bdb9c245b66f320f80ad17247250a87e3  sdr-agent-controller
e2a1882003c16f20d9ac3e7190a866fe7fcbb5e146c82bf605e328389bf0822a  sdr-agent-web-console
```

The previous binaries remain in
`/home/jetson/.local/lib/sdrharness/releases/20260902-pre-model-radio-profile-v1/`.
Both systemd services restarted healthy.

Using the configured real OpenCode Go provider, the operator requested a
2.40–2.42 GHz survey without prescribing the radio profile. The model supplied:

```text
start=2.400 GHz
stop=2.420 GHz
step=5 MHz
sample_rate=10 MS/s
rf_bandwidth=10 MHz
dwell=250 ms
```

Rust validated five points, 81,920 maximum received bytes, the 20-MHz span,
80%-coverage rule and current dynamic limits before approval. The P201/AGX path
completed in 2,355 ms with fixed 20-dB gain, zero clipping, a -53.2 dBFS noise
baseline, no candidates and confirmed restoration.

The next PlanningContext exposed the complete measured sweep to the upstream
model as:

```json
{
  "sweep_id": "request-1",
  "sample_rate_hz": 10000000,
  "rf_bandwidth_hz": 10000000,
  "fixed_gain_db": 20,
  "noise_floor_dbfs": -53.241394,
  "points": [
    [2400000000, -53.825336],
    [2405000000, -47.939945],
    [2410000000, -53.241394],
    [2415000000, -53.55511],
    [2420000000, -53.049984]
  ]
}
```

The model used that context to propose a second complete 2.42–2.44 GHz plan
with the same explicit step/sample-rate/bandwidth/dwell fields. Rust validated
it, and the operator rejected it before execution. The final target check found
one `sdrd` PID/listener, healthy IIO state and no matching temporary directory.
