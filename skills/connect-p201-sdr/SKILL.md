---
name: connect-p201-sdr
description: Connect to, inspect, transfer files to or from, and run authorized commands on the user's P201 Pro SDR by selecting a currently reachable direct or SSH-relay path. Use when the user asks to access the SDR Linux host, IIOD, sdrd, temporary SDR deployment, or SDR-side validation; do not assume the Raspberry Pi is always the relay.
---

# Connect P201 SDR

The target SDR Linux host is `root@192.168.1.10`. Its ordinary SSH service is
on port 22, IIOD is normally on port 30431, and `sdrd` uses port 43110 when it is
explicitly started. Treat service availability as observed state, not a promise.

## Select the route dynamically

Do not bind the workflow to one intermediate device.

1. Try a read-only direct route check from the current host.
2. If direct access is unavailable, identify already configured SSH-capable
   relay candidates from the current workspace, installed connection skills,
   or user-provided host context. Typical candidates can include the Raspberry
   Pi, AGX, NX, or another host physically routed to `192.168.1.0/24`.
3. Use the relay's own connection skill when one exists. Probe it
   non-interactively first, then check from that relay with `ip route get
   192.168.1.10` and a bounded TCP or SSH reachability test.
4. Choose the shortest healthy route. Prefer a local wired/LAN relay for
   artifacts or repeated commands; use Tailscale or a reverse tunnel when that
   is the only healthy management route.
5. State which route was selected for commands and for each transfer. A route
   may change between operations if health changes.

Do not scan arbitrary networks, modify relay routing, or install forwarding
software merely to find a path. If no configured route works, report the failed
bounded checks and ask for a reachable relay.

## Authentication

Use key-only, non-interactive SSH for the selected relay. Prefer a dedicated
SDR key already present on the relay. If the SDR currently accepts only its
locally managed password, use an interactive hidden password prompt; never put
the password in a command line, skill, repository file, environment dump, log,
or response. Do not install a persistent SDR key or change authentication unless
the user explicitly requests that change.

Some minimal relay systems do not provide an SFTP server. When ordinary `scp`
fails with a missing `sftp-server`, retry that transfer with legacy SCP mode
(`scp -O`) instead of changing packages on the relay.

## Safety boundaries

Start with read-only identity, architecture, free-space, process, IIO visibility,
port, hash, and configuration checks. Access authorization does not authorize
transmission, arbitrary IIO writes, FPGA register writes, `/sd/BOOT.bin` or boot
configuration replacement, service enablement, reboot, or power-cycle.

For development artifacts or receive-only data, use a unique feature directory:

- relay staging: `/var/tmp/sdr-agent-dev/<feature-id>/` when available;
- SDR staging/data: `/tmp/sdr-agent-dev/<feature-id>/`.

Validate feature IDs and byte budgets before transfer or capture. Keep raw IQ,
logs, binaries, and build intermediates out of Git. Preserve source interfaces,
tests, configuration examples, design documents, bounded metrics, hashes, and
validation evidence.

Before removing temporary material, resolve and verify the exact feature path,
stop its processes, remove only that directory, and confirm it is absent on the
SDR and every relay. Never use a broad cleanup target such as `/tmp`, `/var/tmp`,
`/sd`, a home directory, or a wildcard.

## Completion report

Report the selected route, target identity, commands or transfers performed,
whether radio/FPGA/service state changed, retained evidence, and exact temporary
paths removed. Do not print credentials.
