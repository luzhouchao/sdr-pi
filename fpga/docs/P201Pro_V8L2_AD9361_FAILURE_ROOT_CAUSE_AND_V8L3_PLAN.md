# P201Pro V8L2 AD9361 Failure Root-Cause Plan

Last updated: 2026-06-08 23:40 Asia/Shanghai

## Current Decision

Do not roll back as the main engineering direction. V8L1 remains the highest
hardware-validated baseline, but the next work is offline root-cause isolation
and V8-derived FPGA changes that preserve AD9361/IIO stability.

NX and SDR are powered off. Do not run hardware, ROS, SDR streaming runtime,
mapping, RTAB-Map, robot_controller, cmd_vel, or motion-related commands.

## Facts

- V8L1 is hardware-validated after physical SDR power-cycle.
- V9A, V9B0, and V8L2 all reached PC build / Bootgen / SD payload status.
- V9A, V9B0, and V8L2 all passed their FPGA identity-register checks after
  power-cycle, but failed AD9361/IIO health.
- The repeated failure signature is:

```text
cf-ad9361-lpc missing
ad9361_dig_tune_delay: Tuning TX FAILED!
cf_axi_adc: probe of 79020000.cf-ad9361-lpc failed with error -5
```

- V8L2 differs from V8L1 only by build IDs and the `pending_adc` stop condition
  for continuous auto-roll, but its implemented image still triggered the same
  AD9361 tuning failure.
- V8L1 rollback staging to SDR `/sd` was done as a safety action after V8L2
  failed. That is a historical fact, not the current forward strategy.

## Working Hypothesis

The most likely problem is implementation-side AD9361 interface sensitivity,
not an AXI register map, Bootgen, SD companion-file, or identity-register issue.

Reasoning:

- The failing images boot far enough for the custom AXI-Lite tap identity
  registers to read correctly.
- The same failure appears across different small-to-medium derived designs.
- V8L2's RTL change is too small to directly explain TX tuning failure in the
  AD9361 core, but place/route perturbation can affect marginal interface timing,
  clock/reset fanout, or routing near the AD9361 logic.
- Vivado runs are slow now because full synth/implementation is being reset for
  each candidate. That throws away placement knowledge and forces Vivado to
  rediscover a route through a thin-margin Zynq-7020 design. Incremental or
  checkpoint-preserving builds should be preferred for diagnosis.

## Isolation Plan

### Branch A: V8D0 Layout Probe

Goal: test whether a fresh rebuild of V8L1-like logic is enough to reproduce
the AD9361/IIO failure.

Design:

- Start from the V8L1 HDL snapshot.
- Change identity build IDs only.
- Do not change AGG behavior.
- Do not add SPEC, FFT, BRAM, DMA, or new hot-path logic.

Interpretation:

- If V8D0 fails AD9361/IIO, rebuild/layout perturbation is the likely root.
- If V8D0 passes AD9361/IIO, the V8L2 RTL condition or its induced optimization
  is still suspicious.

### Branch B: V8D1 Incremental Auto-Roll Fix

Goal: keep the V8L2 continuous auto-roll fix while preserving as much V8L1
implementation state as possible.

Design:

- Use the V8L2 pending-condition fix.
- Build with Vivado incremental implementation referenced to the V8L1
  post-route physopt checkpoint when possible.
- Keep the same SUM8/QUA8/AGG8 register ABI.
- No FFT/SPEC/DMA expansion.

Interpretation:

- If V8D1 passes where V8L2 failed, the fix is viable when implementation churn
  is constrained.
- If V8D1 fails, the AD9361 sensitivity may need physical constraints or a more
  conservative tap partition.

### Branch C: Physical Isolation Constraints

Goal: reduce interaction between the `p201_tap0` logic and AD9361-critical
placement/routing.

Work only after A/B results or if incremental implementation is blocked:

- Add a versioned XDC that constrains `p201_tap0` into a noncritical area.
- Avoid constraining vendor AD9361 IP unless the exact cell hierarchy is verified.
- Preserve AD9361 clocks/resets and CDC constraints.

## FFT And Further Offload

FFT remains a valid goal, but it should wait until the AD9361 health regression
is isolated. The next useful offload order is:

```text
1. Restore a stable V8-derived low-NX-load build path.
2. Validate continuous AGG auto-roll or an equivalent low-polling primitive.
3. Add an isolated spectral kernel, not a large monolithic expansion of the tap.
4. Keep normal runtime output as summary registers; reserve vectors/BRAM/DMA for debug.
```

Candidate FPGA primitives worth moving before or alongside FFT:

- frame power and corrected I/Q/cross accumulators, already present in V8/V8L1
- continuous multi-frame aggregation, V8L2 intent
- clip/zero-cross/quality counters, already present through QUA8
- coarse band-power or Goertzel-style bins after AD9361 stability is solved
- peak/noise/prominence summaries after a real spectral kernel exists

NX should still keep divide, sqrt, atan2, calibration, fallback policy, logging,
and any robot-facing publication logic.

## Gates

A new candidate can become burnable only after:

```text
unique artifact directory
IP packaging PASS
BD validation PASS
WNS >= 0
WHS >= 0
route fully routed
routing errors 0
Bootgen PASS
artifact README current
VERSION_ROUTE.md current
sd_payload complete
```

It is not hardware-validated until the user physically power-cycles the SDR and
post-boot checks pass:

```text
/sd BOOT hash PASS
cf-ad9361-lpc registered
AD9361/IIO health PASS
expected SUM/QUA/AGG identity registers PASS
matching no-motion validation script PASS
```
