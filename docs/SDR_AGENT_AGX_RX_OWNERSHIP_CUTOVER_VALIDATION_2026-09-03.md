# AGX RX ownership cutover validation — 2026-09-03

## Scope

This record closes the legacy Spectrum collector ownership gate before any new
Harness acquisition.  No capture, retune, transmit operation, FPGA access or
boot-image change was performed during the cutover.

## Baseline

The repository was clean at `a367034aacaa07429f600e3b7d0980ff07e19c38`, with
`main` and `origin/main` equal.  The AGX direct route was
`192.168.1.20 -> 192.168.1.10` on `eno1`; the neighbour MAC was
`00:0a:35:00:01:22`.

The P201 had rebooted.  TCP 30431 and SSH were reachable, while TCP 43110 was
closed and no `sdrd` PID existed.  Read-only inspection identified the expected
P201 platform (`pzp201pro`, ARMv7, Buildroot 2020.02.8), the expected Ethernet
MAC, one factory `iiod` PID, no IIOD client connection, no RX-owner process,
all four `cf-ad9361-lpc` scan channels disabled, and RX buffer enable equal to
zero.  The P201 presented a new ECDSA host key fingerprint
`SHA256:eXntSviT1uu5JxsNFSfujE1VnBQpjdZPukdUgMxR57k`; the old AGX entry was not
overwritten.  A feature-local known-hosts file was used after the direct-link,
MAC, platform and IIOD identity checks.

The legacy collector itself was paused and absent:

- `/home/jetson/agent/.runtime/web/collector.pid` was absent;
- `/home/jetson/agent/.runtime/web/resume-after-reboot.dataset` was absent;
- no `run_wifi5g_24h_channel_collection.sh`,
  `run_p201pro_persistent_collection.py`, direct-IIO capture or sweep process
  existed;
- the legacy overview reported `process_running=false`, `phase=paused`, and its
  last collection event was a SIGTERM pause on 2026-08-27.

However, three user units could still launch or re-enable that collector:

| Unit | Baseline state | Exact start path |
| --- | --- | --- |
| `spectrum-agent-web.service` | active, enabled | `/home/jetson/agent/scripts/run_web_console.sh` |
| `spectrum-agent-predictor.service` | active, enabled | `/home/jetson/agent/.venv/bin/python /home/jetson/agent/scripts/run_realtime_prediction_service.py` |
| `spectrum-agent-resume-once.service` | inactive, enabled | `/home/jetson/agent/scripts/resume_collection_once.sh` |

The Web service exposed `/api/collection/start`, and the resume unit could call
that endpoint after reboot.  Merely observing an idle collector therefore did
not satisfy exclusive ownership.

## Cutover action and rollback

The exact cutover command was:

```text
systemctl --user disable --now spectrum-agent-resume-once.service spectrum-agent-web.service spectrum-agent-predictor.service
```

It removed only the three `default.target.wants` links and stopped the two
running legacy processes.  Existing Spectrum datasets and saved user results
were not modified or deleted.

The exact rollback is:

```text
systemctl --user enable spectrum-agent-resume-once.service spectrum-agent-web.service spectrum-agent-predictor.service
systemctl --user start spectrum-agent-predictor.service spectrum-agent-web.service
```

The resume unit was inactive before cutover and should remain enabled but not
manually started during rollback; its original condition marker controls the
next boot action.

## Harness recovery and validation

After the legacy launch paths were disabled, the project P201 workflow gate
again proved zero `sdrd` PIDs, no 43110 listener and the presence of the three
persistent files under `/sd/sdr-agent/current`.  It copied the retained init
entry to the volatile root and started the existing receive-only release.

```text
PRESTART_GATE_OK
Starting receive-only sdrd: OK
POSTSTART_PID_COUNT=1
192.168.1.10:43110 LISTEN
sdrd SHA-256 9a83a57f8e8eaff9399014dd7c68f32b17fbb8471719e2d1e0be0a02775a810a
```

The deployed AGX Controller then completed the read-only
`HELLO/CAPABILITIES/HEALTH/QUIT` observation and reported online, healthy,
IIO-visible, receive capabilities true, and all retired FPGA compatibility
fields false/zero.  Final checks showed:

- all three Spectrum units `inactive` and `disabled`;
- no legacy collector/direct-IIOD capture process and no AGX connection to
  IIOD port 30431;
- exactly one P201 `sdrd` PID and one private-link 43110 listener;
- P201 RX buffer disabled and every scan channel disabled while idle;
- `sdrharness-planner`, `sdrharness-web` and `spark-x25` active and enabled;
- the deployed Harness Web state API remained reachable on port 8787.

The AGX Harness is therefore the only enabled control path that can acquire
from the P201.  The legacy Spectrum UI, predictor and reboot-resume path cannot
relaunch their direct-IIOD collector unless an operator deliberately executes
the documented rollback.
