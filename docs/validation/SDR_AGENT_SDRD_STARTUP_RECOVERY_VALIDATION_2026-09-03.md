# P201 SDRD startup and recovery validation — 2026-09-03

## Scope and design

This delivery makes current-boot and AGX-reboot recovery persistent without
modifying P201 `BOOT.bin`, uramdisk, U-Boot configuration or any FPGA path. It
does not start a collector and performed no IQ capture; the maximum capture
byte count for every test in this record was zero.

The P201 root filesystem is RAM. Its BusyBox `rcS` executes only `/etc/init.d`
and has no existing hook that runs a script from `/sd`, so an init file copied
into `/etc` cannot itself survive a P201 reboot. The persistent source of truth
remains:

```text
/sd/sdr-agent/current/sdrd
/sd/sdr-agent/current/sdrd.conf
/sd/sdr-agent/current/S60sdrd
```

An AGX systemd oneshot now performs the already-authorized recovery operation,
and an enabled timer retries it every 30 seconds. `sdrharness-web.service`
wants and orders itself after the oneshot, while Planner and Web remain the
existing implementations.

The recovery script requires the existing regular mode-`0600` password file,
strict host-key checking, the fixed direct-link endpoint, a nonblocking global
flock and bounded TCP/SSH timeouts. On P201 it accepts only these two states:

- exactly one expected `/sd/sdr-agent/current/sdrd` PID and one 43110 listener:
  report `already_running` and use SDRD/1 for health;
- zero PID and zero listener: atomically copy the persistent `S60sdrd` into the
  RAM init directory and invoke its guarded start.

Any PID/listener mismatch, unexpected executable, missing release, lock
contention, host-key change, timeout or failed SDRD/1 observation fails closed.
The running-state path never launches a second `--probe-radio`/IIO context.

The P201 `S60sdrd` now independently rejects any existing `sdrd` PID or 43110
listener, removes a stale pidfile only after the zero/zero gate, retains its
config/BOOT/IIO/read-only-radio probes, and requires exactly one expected PID
and listener after start. Stop waits for both process and listener teardown.

## Static and deployment gates

`sh -n`, `bash -n`, `git diff --check` and `systemd-analyze verify` passed for
the project files; the latter reported only unrelated host-unit warnings. The
deployed release is:

```text
P201 /sd/sdr-agent/releases/20260903-startup-recovery-v1/S60sdrd
e3c10951d8a8b1bffae9433ec68f3c74f0a4074f842f4b94db07ec25b62ee32d

P201 /sd/sdr-agent/releases/20260903-startup-recovery-v1/sdrd
0b1b6ac63323d4dd81401e3656855428786588aafcca001411a9f21b7f51ada0

AGX /home/jetson/.local/lib/sdrharness/releases/20260903-sdrd-recovery-v1/recover-p201-sdrd.sh
91a2b31e04339fdcd9b15a7475d70b4277a2c75d7f6c24487052988573d8641d

AGX recovery service
0f515f6ed146b64465edb656e7f231c47afaccf59acd9ec0845cc67c816fe7a4

AGX recovery timer
21b32c10b050bf7ba313bc88bd631ee4eb215175b7507965ad1e2ad1a4eff059

AGX Web unit
d25e8805c5580e9edbc63f907b42109cbc3fae0a775a005d48311eb8891d00a9
```

The P201 rollback release is
`/sd/sdr-agent/releases/20260903-pre-startup-recovery-v1`; its prior init hash
is `c95a9c92a0a24f723f5b05844355bc9757ce9397bbd788e040ab70ecc5e3a4e7`.
The prior AGX Web unit remains under
`/home/jetson/.local/lib/sdrharness/releases/20260903-pre-sdrd-recovery-v1/`.

## Live validation

All process mutations were preceded by SDRD/1 `EXECUTION_STATUS` showing no
active, armed or faulted session and sysfs buffer enable 0.

1. Running the oneshot against the existing service returned
   `p201_recovery_action=already_running`, one PID/listener and the expected
   daemon hash.
2. Directly repeating `/etc/init.d/S60sdrd start` returned exit 1 with
   `FAIL (already running or listener occupied)` and left exactly one process.
3. A normal init stop reached zero PID/zero listener. The oneshot then copied
   the persistent entry, started exactly one daemon and passed the deployed
   Controller's SDRD/1 `HELLO/CAPABILITIES/HEALTH/QUIT` observation.
4. The unique expected idle daemon was sent `SIGKILL`. The stale pidfile was
   deliberately retained; recovery removed it only after the zero/zero gate
   and restored the listener successfully.
5. With the timer enabled, the same bounded idle abnormal-exit test recovered
   automatically on its next trigger. A deliberately held recovery flock made
   a simultaneous oneshot exit with status 75 and
   `p201_recovery_error=already_running`.
6. Rollback was exercised, not merely documented: the timer was disabled, the
   prior P201 init and AGX Web unit were restored and hashed, the recovery unit
   files were withdrawn and systemd reloaded. The new files were then
   atomically redeployed and the timer re-enabled. The running daemon remained
   single throughout.
7. Restarting Web invoked the ordered recovery check; Web became ready on port
   8787, `/api/state` returned HTTP 200, and Planner/Spark/Web remained active
   and enabled. The legacy Spectrum units remained inactive and disabled.

Final P201 readback was 2.4 GHz, 30.72 MS/s, 18 MHz, `slow_attack`, scan mask 0
and buffer 0. SDRD/1 was healthy and idle with one daemon/listener.

## Real P201 reboot and remaining blocker

A real P201 reboot was also run after recording the zero-session radio state
and persistent hashes. SSH returned in two seconds, `/sd` retained every
release, and 43110 correctly remained closed because the RAM init file had
disappeared. The recovery service then rejected the connection under strict
checking: Dropbear had regenerated its ECDSA identity from
`SHA256:eXntSviT1uu5JxsNFSfujE1VnBQpjdZPukdUgMxR57k` to
`SHA256:i1Lnt/81XecFwnrhkIMSzo20C6+4bRVWvqmANS8L5Cs`.

After the direct-link MAC, ARMv7 platform/hostname, protected BOOT hash, empty
PID/listener/buffer state and all three `/sd/current` hashes were independently
rechecked with a feature-local key file, the user-authorized global host-key
entry was updated. The oneshot then recovered the daemon from `/sd` and the
timer resumed.

The vendor has a persistent-host-key mechanism in QSPI `mtd2`, but that
partition currently contains no valid JFFS2 nodes. Its only setup helper runs
`flash_erase -j /dev/mtd2 0 0`, an irreversible NVM-format operation that was
not authorized and was not executed. During read-only discovery, invoking the
helper with an unsupported `--help` argument entered its confirmation loop;
no `yes` was supplied, no JFFS filesystem was mounted and the MTD header was
unchanged. The helper process was stopped, and private password/key copies its
companion scripts had placed only in the unmounted RAM directory
`/mnt/jffs2/etc` were deleted without being read.

Consequently current-boot, AGX-reboot, normal, duplicate, abnormal, timer and
rollback recovery are complete, but unattended recovery across a P201 reboot
is not. It still requires a verified host-key repin. Initializing the dedicated
vendor NVM filesystem would materially change persistent device state and
requires an explicit operator decision; until then the parent checklist item
remains open.

## Cleanup

The exact P201 staging directory
`/tmp/sdr-agent-dev/sdrd-startup-recovery-20260903/` and AGX feature directory
`/var/tmp/sdrharness-dev/sdrd-startup-recovery-20260903/` were removed after
hashes and evidence were retained. The post-reboot key scan and temporary
rollback-unit holding directory were inside that AGX feature root. No capture,
raw IQ, Web result, credential, model, database or retained release was
deleted.
