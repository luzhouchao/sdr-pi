# SDR Agent Raspberry Pi deployment

Date: 2026-08-31

## Result

The plan-only SDR Agent is deployed and enabled on the Raspberry Pi 4. The
Planner Worker starts at boot and successfully calls the existing 4090
llama.cpp/Qwen endpoint. The Rust Controller accepted a conservative `hold`
proposal in a live end-to-end smoke test.

No SDRD command, AD9361 retune, IQ capture, FPGA access, `BOOT.bin` change or
SDR service modification was performed.

## Connection

Deployment commands and all file transfers used the preferred LAN route:

```text
root@192.168.50.194
hostname: pi4
architecture: aarch64
```

The Tailscale fallback `root@100.102.130.52` was also verified. A dedicated
key at `C:\Users\20642\.ssh\pi4_agent_ed25519` was installed for future
non-interactive access. The login password is not stored in the repository or
the connection skill.

The reusable Codex skill is installed at:

```text
C:\Users\20642\.codex\skills\connect-raspberry-pi
```

Its read-only route checker reports both routes healthy and selects LAN.

## Node.js upgrade

The Pi's effective default Node.js was upgraded directly to the official
Node.js `v22.23.2` Linux ARM64 release:

```text
/usr/local/lib/node-v22.23.2-linux-arm64
/usr/local/bin/node -> ../lib/node-v22.23.2-linux-arm64/bin/node
/usr/local/bin/npm  -> ../lib/node-v22.23.2-linux-arm64/bin/npm
```

The official archive SHA-256 was verified before extraction:

```text
013b59cfd2819703a6f4a14ab891fc46fc2a4e3f5bcd92de3fb4929b43e35b30
```

The Debian package remains intact at `/usr/bin/node` with version `v20.19.2`,
so removing the `/usr/local/bin` links restores the previous default without a
package reinstall.

## Installed layout

```text
/opt/sdr-agent/current -> releases/20260831-plan-v2-sdrd-observe
/opt/sdr-agent/releases/20260831-plan-v2-sdrd-observe/bin/sdr-agent-controller
/opt/sdr-agent/releases/20260831-plan-v2-sdrd-observe/planner-worker
/etc/sdr-agent/planner.env
/etc/sdr-agent/request.example.json
/etc/sdr-agent/qwen-api-token
/etc/systemd/system/sdr-agent-planner.service
```

The release and Node runtime are root-owned. The Worker runs as the dedicated
`sdr-agent` system user. `npm ci --omit=dev --ignore-scripts` installed 93
packages and reported zero vulnerabilities.

The current deployed Controller includes the read-only SDRD observation slice
and matches the locally built ARM64 artifact:

```text
sha256 ed492c4d7a2f5dadec86a4e099d8b25dd21be0bb7d04527c31d681fd1bc89534
```

The original `20260831-plan-v1` release remains installed for rollback. Live
SDRD observation validation is recorded in
[`SDR_AGENT_SDRD_OBSERVE_VALIDATION_2026-08-31.md`](SDR_AGENT_SDRD_OBSERVE_VALIDATION_2026-08-31.md).

## Credential handling

The Qwen token source is root-owned mode `0600`. The service obtains a private
runtime copy through systemd `LoadCredential`:

```text
/run/credentials/sdr-agent-planner.service/qwen-api-token
```

The runtime credential is exposed to the service as a file path, not as a
token value in the environment or command line. The first start exposed a
duplicate environment-file path that tried to read the root-only source
directly. The service was stopped, the duplicate setting was removed, and the
final start uses only `LoadCredential`.

## Service state

```text
service: sdr-agent-planner.service
enabled: yes
active: yes
socket: /run/sdr-agent/planner.sock
socket mode: 0660 sdr-agent:sdr-agent
V8 old-space cap: 96 MiB
MemoryHigh: 144 MiB
MemoryMax: 192 MiB
CPUQuota: 25%
TasksMax: 32
```

The service has no shell, SSH, file-editing, SDR, IIO or FPGA tool. Its only
model tool is `submit_plan`.

## Live smoke test

The deployed Rust Controller sent a bounded context containing no candidates
and no retune, capture, FPGA or recognizer capability. The operator instruction
requested a safe hold. Qwen proposed:

```json
{
  "kind": "hold",
  "reason": "No retune, capture, FPGA, or recognition capabilities are available; maintain safe idle state."
}
```

The Controller matched request/session IDs and accepted the plan with
`approval_required=false`. The Worker remained active afterward.

## Raspberry Pi resource result

After startup and one real planning request:

```text
process RSS: 87744 KiB (about 85.7 MiB)
process RSS high-water mark: 105236 KiB (about 102.8 MiB)
cgroup charged memory current: about 37.9 MiB
cgroup charged memory peak: about 55.7 MiB
tasks: 7
```

`CPUUsageNSec` did not increase over a five-second idle sample. Model inference
and KV cache remained on the 4090. The Pi retained about 3.4 GiB available
memory during validation.

## Rollback

Planner rollback does not require touching the SDR:

1. disable and stop `sdr-agent-planner.service`;
2. point `/opt/sdr-agent/current` to a previous release, or remove the current
   link when no previous release exists;
3. restore the prior unit/config if they were backed up;
4. restart only after `systemd-analyze verify` passes.

Node rollback removes only the four `/usr/local/bin` links. The original
Debian `/usr/bin/node` remains version `v20.19.2`.

The remote deployment staging directory was removed after validation. No
reboot was performed; boot persistence is established by the enabled systemd
unit and still needs a future reboot observation for physical verification.
