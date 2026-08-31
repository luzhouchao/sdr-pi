# P201Pro Vivado Runtime Slowdown Note

Date: 2026-06-08 Asia/Shanghai

## Why It Feels Slower Now

The current flow is slower mostly because the project has moved from small HDL or
OOC checks into full vendor-project implementation:

```text
IP package
BD integration
integrated synthesis
implementation
route
post-route phys_opt
bitstream
HWDEF/export
large timing/utilization/DRC reports
```

That is a much heavier flow than the earlier single-module checks.

V8 and later also touch a tightly packed Zynq-7020 design with thin timing margin.
Even small RTL changes can force Vivado to rerun placement/routing around the
AD9361, Ethernet/RGMII, PS interconnect, and tap logic. V8 passed with only thin
positive margin, so implementation effort is naturally higher.

At the time this note was written, no Vivado process was running in the background.

## Practical Rules Going Forward

Use staged build depth:

```text
1. Syntax/OOC synth first.
2. IP package only after OOC passes.
3. BD integration only after IP package passes.
4. Full implementation only after the candidate is worth a hardware attempt.
5. Post-route phys_opt only for candidates that are close and strategically useful.
```

Keep new candidates lean:

```text
start from the pre-V9A SUM8 snapshot
avoid SPEC/FFT/BRAM/DMA until the AD9361 sensitivity is understood
prefer low-cost auto-aggregate/event-summary registers
avoid wide hot-path compare trees
avoid changing AD9361-facing clocks/resets/tap points
```

Keep handoff short:

```text
HANDOFF.md should stay as a current-state index.
Long history goes under docs/ or reports/.
```
