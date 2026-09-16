# Runtime, finite TX and stopping

## Identity and runtime

- AGX USB B210: serial `2508504`, USB VID/PID `2500:0020`, expected USB3 speed
  at least5000Mbps. Enumerate the current USB node; do not hardcode bus/devnum.
- `devices/b210/runtime-manifest.json` is the file/size/SHA authority.
  Runtime is `local-assets/devices/b210/uhd-4.1.0.5-3-a7-100t/`.
- Use `devices/b210/b210.py::environment()` / `Transport.env()` to set the
  private `UHD_IMAGES_DIR` and select the known TX executable. System libuhd
 4.1.0 is manifest-checked; do not overwrite global libraries/image folders.
- The board needs its verified **A7-100T** image. `usrp_b210_fpga.bin` SHA is
  `ee03a9e38c83a1f6f327e7b560522c2a96629e7de574196092c1b830d05fcf9b`.
  Never substitute the A7-200T or ordinary B210 image. FX3 and FPGA loading here
  are volatile USB runtime operations, unrelated to retired P201 FPGA/BOOT work.
  Do not write EEPROM/flash or run the old NX global activation script on AGX.

`b210.py probe --output /var/tmp/sdrharness-dev/b210-agx-<unique-id>` performs
bounded discovery/runtime initialization and loopback checks without RF streams.
It can re-enumerate USB. Use it when initialization is needed, not before every
already healthy transmission. Verify `idle()` afterward. For an explicitly
selected NX run use the existing `connect-nx` skill and host transport; do not
move hardware or silently switch hosts when AGX fails.

## Plan and execute

### LO calibration and API boundaries

- Distinguish the dedicated A7-100T/FX3 images from the host library. The audited
  AGX `libuhd` is Ubuntu package4.1.0.5-3 with the manifest SHA; do not describe it
  as a custom host driver solely because the runtime directory says A7-100T.
- In the audited UHD4.1.0.5 path, B200 `get_tx_stream()` calls `update_enables()`
  → AD9361 `set_active_chains()` → TX quadrature calibration when TX is enabled.
  The existing helper creates the stream after setting rate/frequency/gain/BW;
  absence of an explicit application calibration call does not mean calibration
  was skipped. Same-frequency tuning returns early; a retune more than100MHz
  from the last calibration point can trigger calibration. Do not use a frequency
  excursion as an unplanned refresh operation.
- Generic `set_tx_dc_offset` / `set_tx_iq_balance` API existence does not establish
  B200 support: the audited frontend does not expose their correction properties.
  Generic calibration utilities and ADI no-OS functions are not interchangeable
  with this UHD path. Do not manually poke registers or inject host-IQ DC as a
  substitute; with LO offset, host DC may alter the wanted AM carrier.
- Calibration completion is not a measured residual-LO specification. Keep
  RF LO, DSP shift and wanted RF frequency distinct; save `tune_result_t` and
  applicable filter state in a future authorized experiment. Existing historical
  configuration logs report combined frequency/BW, not the full RF/DSP split.
- Preserve original RML modulation and distinguish coherent TX LO from background
  transients. Before moving the LO further, assess occupied bandwidth and filter
  headroom; offset tuning relocates leakage rather than reducing its emission.

Version-specific source evidence, USB reload verification and remaining limits:
[2026-09-16 driver audit](../../../../docs/validation/RML2018A_OFFLINE_BASELINE_2026-09-16.md#uhd校准路径只读审计与获准镜像重载2026-09-16).

### Finite transmission

1. Resolve the actual helper binary and verify its SHA, supported mode and
   source/runtime identity. Source tests, isolated executable and installed
   executable are different states. Keep B210 artifacts outside P201 paths.
2. Register source row IDs/Y/Z, dataset/waveform SHA, peak, exact TX sample/byte
   limit, sample rate/frequency/bandwidth/LO offset, TX/RX gain, channel/subdevice,
   connection, exact RX/store/RAM budgets, deadlines, disk space and stop path.
   Source Z is a dataset grouping, not an RF gain or calibrated received SINR.
3. Use the last confirmed connection from AGENTS. The known B210 connector is
   **RF A TX/RX**, `A:A`, channel0, antenna selector `TX/RX`; P201 is RX1.
   Stop before changing attenuation. Do not connect TX directly to RX without
   attenuation. Gain in dB is not absolute transmitted dBm; use the registered
   measured profile, not `TX gain − attenuation + RX gain` as an SINR estimate.
4. Verify the USB device has no other owner before launching exactly one TX
   helper. Keep devices initialized across blocks within the finite session.
   For synchronized capture, send exact `GO\n` only after the Controller has
   delivered the first actual RX IQ; a sleep or buffer creation alone is not
   evidence of received samples.
5. Preserve UHD configuration/readback, start/end/accepted-sample counts and
   async events. Partial sends must resume at the accepted offset, with only
   the initial packet marked start-of-burst. A source-SNR boundary is not an
   end-of-burst when the requested experiment is continuous across two SNRs.

The repository's `devices/b210/tx-events.cpp` has finite experiment modes, and
`rml2018a-continuous-pilot.py` is a bounded pilot. Inspect the current interface
and plan limits before use; do not merely increase a loop count or repeat old
4-second frames and call it a full continuous dataset experiment.

## Stop, verify and retain

Use the active campaign STOP/SIGINT path first: stop the identified TX child,
cancel the Controller's exact RX generation through its dedicated cancel path,
reap children and drain/preserve received buffers. If a child fails to exit,
terminate/kill that verified PID after a bounded wait; avoid broad `pkill`.
Never open an ordinary P201 status session while RX is owned.

After children exit, require no B210 USB holder and verify P201's saved radio
state through the existing workflow. USB idle/child exit establishes ownership
state, not a measured zero RF output. Async ACK means end-of-burst acknowledged;
absence of reported underflow/sequence errors does not independently prove
ADC sample continuity. Sync failures, clipping, estimator-invalid rows and
model errors remain separate outcomes; don't turn “valid SINR” into “recognized”.

Keep raw SigMF IQ, HDF5 processing results and failures as requested, with
source/capture/session/algorithm identities and exact sizes/hashes. Background
power comes from TX-off measurements before/after the session, not concurrent
“background SINR”. Clean only this unit's non-retained build/cache/staging after
all consumers stop; record retained paths and exact manual removal methods.
