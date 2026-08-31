# P201Pro SDR FPGA Agent Rules

Last updated: 2026-06-09 12:53 Asia/Shanghai

This file is the working rulebook for agents continuing the P201Pro 2T2R Zynq-7020 SDR FPGA offload project.

## Project

Workspace:

```text
E:\vivado\fpga_p201pro_accel
```

Worktree note:

```text
Some active mainline work may be checked out under
E:\vivado\fpga_p201pro_accel_mainline. Run commands from the current git
top-level and confirm with `git status --short --branch` before editing.
Do not mix the V10S5 side-path worktree into mainline documentation or claims.
```

Target:

```text
P201Pro 2T2R SDR
Zynq-7020 / xc7z020clg400-2
Vivado 2019.1
AXI-Lite tap base: 0x43C00000
```

Main HDL:

```text
E:\vivado\fpga_p201pro_accel\hdl\p201pro_ad9361_power_tap_axi_regs.v
```

Current goal:

```text
Move SDR computation from NX CPU/GPU toward validated FPGA kernels, but keep the active NX SDR/robot runtime untouched until hardware primitives and shadow validation prove the split.
```

Design strategy:

```text
Bypass first.
FPGA computes reusable fixed-shape SDR primitives.
NX composes algorithms, calibration, policy, fallback, logs, and later frontend/ROS publication.
Do not directly replace the current NX CPU/GPU SDR chain until explicitly instructed.
```

Current route snapshot:

```text
V8L1 remains the highest hardware-validated forward baseline.
V10S0 is hardware-validated only as an isolated self-test page on a V8D0 base.
The current-loaded V10S0/V8D0 image passed independent passive shadow and
feature-flag primitive-assist stress100 board probes from the NX experiment
directory. This is primitive-level offload evidence, not active robot_control
runtime integration.
V10S4 failed AD9361/IIO despite self-test register pass.
V10S5 remains a side-path/source candidate unless VERSION_ROUTE.md says it has
completed the full artifact gate.
```

## Required First Reads

Before acting, read these files:

```text
E:\vivado\fpga_p201pro_accel\AGENTS.md
E:\vivado\fpga_p201pro_accel\VERSION_ROUTE.md
E:\vivado\fpga_p201pro_accel\HANDOFF.md
E:\vivado\fpga_p201pro_accel\README.md
```

For version-specific work, read the current route and the applicable plan/log named there. Current planning documents may include:

```text
E:\vivado\fpga_p201pro_accel\PROJECT_MAP.md
E:\vivado\fpga_p201pro_accel\docs\P201PRO_REUSABLE_SUBMODULE_MATRIX_20260610.md
E:\vivado\fpga_p201pro_accel\docs\P201Pro_V8L2_AD9361_FAILURE_ROOT_CAUSE_AND_V8L3_PLAN.md
```

The old 20260610 day-plan document was retired and deleted after second-day
work began. Do not recreate or use it as a current route; use
`VERSION_ROUTE.md`, `HANDOFF.md`, and current reports.

Superseded plans and long logs live under `docs\archive`. Do not assume archived
documents are current. `VERSION_ROUTE.md` is the version source of truth.

## Hard Safety Boundaries

Never modify the original SD backup:

```text
C:\Users\20642\Desktop\开发\SDR\2r2t
```

Never overwrite any original `BOOT.bin`.

Treat the vendor package as read-only:

```text
G:\ROS开发\SDR P201P
```

Do not start or trigger:

```text
ROS
SDR streaming runtime
mapping
RTAB-Map
robot_controller
cmd_vel
navigation
robot motion
```

Do not modify the active NX `robot_control` runtime chain unless the user explicitly asks for active integration.

NX experiment files must stay under:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
```

Windows mirror for NX experiment files:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test
```

Only copy from read-only sources into clearly named experiment or artifact folders.

## Version Route

Do not hard-code the active version from this file. Always read:

```text
E:\vivado\fpga_p201pro_accel\VERSION_ROUTE.md
```

`VERSION_ROUTE.md` must define:

```text
current highest hardware-validated candidate
recommended active test order
rollback order
artifact directories
BOOT paths
expected version registers
hardware validation status
known reasons to choose or skip each version
```

Agents must treat this file as the stable rulebook and `VERSION_ROUTE.md` as the moving version map.

Do not skip directly to active NX replacement.

Do not describe any versioned artifact as hardware-validated until the user has copied/burned it, physically power-cycled the SDR, and the expected registers have been read back from hardware.

Do not describe a spectral proxy as FFT unless the applicable version plan and validated hardware actually implement FFT, Goertzel, or another real spectral kernel.

## Git Baseline and Commit Rule

From 2026-06-08 onward, agents must use the local Git repository in this workspace to preserve project history.

Use a named branch for each hardware-changing or route-changing effort, and make small commits for meaningful milestones such as:

```text
HDL/register ABI changes
Vivado build script changes
Bootgen/SD payload metadata
VERSION_ROUTE.md/HANDOFF.md/README.md updates
hardware validation reports
rollback or failure diagnostics
```

Before major edits or SD staging, check:

```text
git status --short --branch
```

Do not revert, reset, delete, or overwrite user/agent changes unless the user explicitly asks for that rollback. Generated Vivado binaries, BOOT images, and vendor outputs may remain untracked or ignored, but text manifests, hashes, reports, scripts, and route documents should be committed when they define project state.

Git history is useful evidence, but it does not replace hardware validation. `VERSION_ROUTE.md` remains the source of truth for which version is highest hardware-validated.

## FPGA/NX Split

FPGA should implement high-throughput fixed-shape primitives:

```text
I/Q ingestion
power/RSSI
I/Q sums
cross real/imag
corrected numerator registers
quality counters
multi-frame aggregate registers
coarse spectral summaries
later FFT/window/PSD/noise/peak summaries
```

NX should keep:

```text
configuration
register reads
division
sqrt
atan2
calibration
multi-frame policy
algorithm composition
fallback
logging
JSON/ROS/frontend publication
```

Prefer reusable FPGA kernels over one rigid end-to-end FPGA algorithm.

Prefer summary registers for runtime. Full vectors, BRAM windows, or DMA captures are debug and validation features unless explicitly approved for runtime.

## Python, C, and Runtime Rules

Python is allowed for:

```text
development
bring-up
validation
reference comparison
shadow logging
batch SSH/devmem tests
artifact verification
numeric reference models
```

Python is not allowed for:

```text
runtime hot path
active NX assist backend
high-frequency register polling
anything that can block robot_control
anything that can influence active SDR/AoA decisions in real time
```

C/C++ is required for any NX backend that can influence SDR/AoA decisions.

Runtime-influencing C/C++ must provide:

```text
mmap/UIO register access
frame alignment
snapshot or ring-buffer handling
latency measurement
stale-frame detection
invalid-flag detection
overflow detection
low-confidence detection
immediate CPU/GPU fallback
```

Runtime hot path rules:

```text
No SSH polling.
No devmem subprocess loop.
No fork in the hot loop.
No malloc in the hot loop.
No blocking network dependency.
No log spam.
```

## Timing and Performance Rules

V8 timing margin is thin. Preserve timing aggressively.

Before substantial FPGA HDL, NX validation code, register-route, or SD artifact changes, run a bounded performance review:

```text
Is this the right FPGA/NX split?
Can this be a reusable kernel instead of a rigid algorithm?
Can arithmetic be narrower, cheaper, shared, or pipelined?
Can work move out of the ADC hot path?
Are debug paths isolated from production timing paths?
Does the change preserve rollback and testability?
Does the register page define a stable ABI?
```

HDL rules:

```text
Keep ADC-domain logic simple.
Use post-frame FSM/pipeline for wide or comparative work.
Latch stable snapshots before AXI readback.
Preserve SUM/QUA/AGG behavior unless a compatibility change is documented.
Treat WNS < 0 or WHS < 0 as failure.
Treat route errors as failure.
Do not ignore critical clock/reset/CDC warnings.
```

Do not add full FFT IP, BRAM vector readback, DMA, or wide full-spectrum readback to a version unless the current plan explicitly calls for it and the performance review accepts the risk.

Spectral work should be isolated as a kernel or separate IP-style block where feasible, rather than another large monolithic expansion of the existing AXI-Lite tap.

## Versioned Artifact Rules

Every meaningful FPGA build must have a unique artifact directory under:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments
```

Do not reuse a version directory for a different hardware behavior.

Every completed, packaged, rejected, or partially failed version must update:

```text
E:\vivado\fpga_p201pro_accel\VERSION_ROUTE.md
```

Every artifact README must include:

```text
version name
purpose
artifact path
BOOT path
SD payload path
register map additions
expected version registers
Vivado package/integration/bitstream status
WNS/WHS/route status/routing errors
Bootgen status and BIF content
SHA256 hashes
NX validation scripts
safe copy instructions
do-not-copy warnings
rollback version
known risks
hardware validation state
```

If not burnable, the README must say:

```text
NOT BURNABLE
```

If not tested after physical SDR power-cycle, the README must say:

```text
NOT HARDWARE VALIDATED
```

## Local Artifact Gate and SDR `/sd` Staging

The user has granted standing approval for agents to write a version's `sd_payload` to the SDR `/sd` experiment target without asking for separate per-copy approval, but only after the local artifact gate passes.

The local artifact gate for SDR `/sd` staging is:

```text
unique artifact directory exists
Bootgen PASS
WNS >= 0
WHS >= 0
route fully routed
routing errors 0
artifact README is current
VERSION_ROUTE.md is current
sd_payload is complete
```

Before writing to SDR `/sd`, re-check the artifact README, `VERSION_ROUTE.md`, Bootgen status, timing/route evidence, `sd_payload` contents, and hashes. If any gate item is missing, stale, ambiguous, or failed, stop and ask the user before copying.

The standing approval is limited to the SDR `/sd` experiment target and the gated version's `sd_payload`. It does not permit modifying the original SD backup:

```text
C:\Users\20642\Desktop\开发\SDR\2r2t
```

It does not permit overwriting any original `BOOT.bin`, modifying the vendor package, or touching:

```text
G:\ROS开发\SDR P201P
```

It does not permit starting or triggering:

```text
ROS
SDR streaming runtime
mapping
RTAB-Map
robot_controller
cmd_vel
navigation
robot motion
```

After writing the `sd_payload` to SDR `/sd`, run `sync` on the SDR before reporting the copy complete. The staged image is still not hardware-validated until the user physically power-cycles the SDR and the expected post-boot validation passes.

## NX User-Directory Codex Delegation

The user has granted standing approval for the main agent to start an NX-side Codex process from the NX user directory without asking for separate per-run approval, as long as it helps advance this P201Pro SDR FPGA offload project and stays within the staged bypass/offload workflow.

The allowed NX-side Codex scope is:

```text
/home/wheeltec
/home/wheeltec/.codex
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
```

NX-side Codex work must stay focused on independent experiment code, validation scripts, artifact checks, logs, and documentation for the FPGA SDR offload project. It may prepare or run safe readback/validation commands only after the matching FPGA artifact has passed the local gate and, when needed, after the user has physically power-cycled the SDR.

NX-side Codex must not modify the active NX `robot_control` runtime chain unless the user explicitly approves active integration. It must not start or trigger:

```text
ROS
SDR streaming runtime
mapping
RTAB-Map
robot_controller
cmd_vel
navigation
robot motion
```

NX-side Codex must not treat a software reboot as final SDR hardware validation. Final hardware validation requires the user to physically power-cycle the SDR and then run the expected post-boot checks. If final validation requires SDR power removal/reapply, stop and wait for the user.

## Local Subagent Delegation

The user has granted standing approval for the main agent to start local subagents without asking for separate per-run approval when they are used to advance this P201Pro SDR FPGA offload project.

Each local subagent task must have a clear, bounded scope before it starts. Use local subagents for focused work such as reading logs, inspecting artifacts, checking documentation consistency, reviewing HDL/NX experiment code, or preparing bounded implementation patches.

Local subagents must be closed promptly after their scoped task is complete. Do not leave subagents running after they are no longer needed.

Local subagents must not revert, overwrite, or roll back changes made by the user, the main agent, or other agents unless the user explicitly requests that rollback.

## Build Tools

Vivado:

```text
E:\Xilinx\Vivado\2019.1\bin\vivado.bat
```

Bootgen:

```text
E:\Xilinx\SDK\2019.1\bin\bootgen.bat
```

Core scripts:

```text
E:\vivado\fpga_p201pro_accel\scripts\vivado_package_ad9361_power_tap_ip.tcl
E:\vivado\fpga_p201pro_accel\scripts\vivado_integrate_ad9361_power_tap.tcl
E:\vivado\fpga_p201pro_accel\scripts\vivado_impl_bitstream_integrated_ad9361_tap_project.tcl
```

Do not assume success from a zero exit code alone. Read logs, timing, route status, and generated artifact contents.

## Hardware Access

NX SSH:

```text
ssh -i %USERPROFILE%\.ssh\codex_nx_ed25519 -p 22 wheeltec@192.168.2.193
```

SDR SSH from NX:

```text
ssh root@192.168.1.10
password: managed locally; never commit credentials
```

Hardware validation requires a physical SDR power-cycle by the user.

If a step requires the user to power-cycle the SDR, stop and wait.

## Acceptance Gate

A candidate is not accepted unless:

```text
IP packaging PASS
BD validation PASS
bitstream PASS
WNS >= 0
WHS >= 0
route fully routed
routing errors 0
Bootgen PASS
unique artifact directory exists
artifact README is current
VERSION_ROUTE.md is current
sd_payload exists when SD testing is intended
expected version registers match after physical power-cycle
validation scripts PASS
rollback artifact remains available
```

Stop and document failure on:

```text
negative setup or hold slack
route error
Bootgen failure
missing BOOT
unexpected version register
unstable registers
SUM/QUA/AGG regression
critical clock/reset/CDC warning
unsafe command
anything that would touch active robot_control without approval
anything that would start ROS, SDR streaming, mapping, RTAB-Map, robot_controller, cmd_vel, or robot motion
anything that would overwrite original BOOT.bin
anything that would modify vendor files or original SD backup
```

## NX Integration Rules

Until explicitly approved, active NX remains:

```text
cpu_gpu_existing
```

Allowed staged modes only after hardware validation:

```text
fpga_sum8_shadow
fpga_sum8_assist
fpga_fft_shadow
fpga_fft_assist
```

Shadow mode:

```text
CPU/GPU remains source of truth.
FPGA output is logged and compared only.
FPGA output must not affect control, publication, or motion.
```

Assist mode:

```text
FPGA may reduce candidate work or provide gates.
NX CPU/GPU remains final authority.
Any stale frame, invalid flag, overflow, mismatch, or low confidence must fallback.
```

Any active NX patch must be off-by-default and include rollback instructions.

## Register ABI Rules

Every new register page must document:

```text
offset
name
bit layout
validity semantics
stale semantics
overflow semantics
frame_id behavior
sample_count behavior
capability bits
build ID
ABI version
```

Never silently change an existing register meaning.

If compatibility changes, increment the ABI or build identifier and document it in the artifact README and `VERSION_ROUTE.md`.

## Handoff Requirements

Every handoff must include:

```text
what changed
what was not changed
artifact directory
BOOT path if generated
whether burnable
whether hardware-validated
Vivado timing summary
Bootgen status
expected version registers
NX validation script
rollback version
known risks
next safe step
```

Do not claim any of the following without evidence:

```text
hardware validated
runtime integrated
FFT complete
PSD complete
safe for active robot_control
```
