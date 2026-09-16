---
name: n210-sdr-workflow
description: Operate the user's domestic N210, a USB B210-compatible SDR enumerated as serial 2508504 on Jetson AGX. Use for B210 identity/UHD runtime checks, finite external TX plans, simultaneous B210 TX and P201 RX, stop verification, and reproducible RF evidence; route P201 access/deployment to p201-sdr-workflow.
---

# N210 external signal source

The repository is `/home/jetson/sdrharness`. The user's device is a **domestic N210, compatible with USB B210, serial2508504,
A7-100T**. N210 is its intended device name, not a mistaken reference to B210.
UHD enumerates it through the B200/B210 driver. Verify the actual identity; do
not apply NI Ethernet N210 addressing or a generic B210 FPGA image.
AGX is the current TX host; NX is a historical alternative, not an automatic
fallback. P201 remains the separate Ethernet RX device.

Use the existing [device entry](../../../devices/b210/README.md),
[runtime manifest](../../../devices/b210/runtime-manifest.json) and
`devices/b210/b210.py`; do not create another driver/runtime or copy the dataset.
Start with `python3 -B devices/b210/b210.py status` from the repository.
This verifies runtime hashes and reports USB identity, but **does not establish
USB ownership or perform an RF test**. Use `device.idle()` / the existing
`Transport('agx', ...).preflight()` for ownership before hardware initialization.

After power-up, this board may enumerate at **480 Mbps with boot serial
`0000000004BE`** before its volatile FX3/FPGA images are loaded. That observation
alone is not a USB3/cable failure. When runtime loading is authorized, use the
existing bounded `b210.py probe --output /var/tmp/sdrharness-dev/b210-agx-<unique-id>`
workflow; verify serial `2508504`, speed at least5000Mbps, both register loopback
passes and no USB holder afterward. Do not repeatedly initialize a healthy board.
Image loading/probing initializes hardware and can run internal calibrations;
it is not a read-only status query, and does not authorize TX/RX streams.

Before initializing or transmitting, read
[references/finite-tx.md](references/finite-tx.md). It covers the known image,
plan/GO protocol, stop paths and event interpretation. For coordinated P201 RX,
also use [p201-sdr-workflow](../p201-sdr-workflow/SKILL.md); only the Controller
owns the P201 session. This skill does not add P201 TX capability.

Read current authorization, connection and work selection in repository
`AGENTS.md` and `docs/SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md`.
Existing user authorization persists within its scope; do not repeatedly ask
for the same cable/frequency confirmation. A finite plan is still required for
each run. A conditional instruction such as “one SNR first, then two if it
passes” requires the first result to pass its registered checks before stage2.

Keep acquisition and model work separate as currently requested: Spark stopped,
CPU/GPU consume RAM during RX, raw IQ and processing results persist before
buffer release, and the model loads only after the authorized acquisition phase
is fully completed. Follow the current campaign contract rather than assuming
an older 24-row or 2048-row helper can already run a whole SNR.

Use the [campaign reference](../../../docs/reference/RML2018A_FULL_RF_CAMPAIGN.md)
for parameters/interfaces and its linked validation only when needed. Store
new status/evidence in the existing checklist and validation/evidence indexes;
do not turn this skill into another experiment log or permanent next-step list.
