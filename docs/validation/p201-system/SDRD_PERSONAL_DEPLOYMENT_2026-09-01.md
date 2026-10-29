# SDRD personal receive-only deployment

Date: 2026-09-01

## Outcome

The controlled `sdrd` Adapter is running for the current SDR boot on the
isolated Pi-to-SDR Ethernet address `192.168.1.10:43110`. The deployed
configuration keeps the existing allowlist, RX0-only ownership, 64 MiB hard
capture cap, direct cancellation, state restoration and `fpga_backend=disabled`.
It binds only the SDR's private Ethernet address rather than every interface.

The persistent FAT partition contains the versioned release and current copy:

```text
/sd/sdr-agent/releases/20260901-personal-v1/
/sd/sdr-agent/current/
```

The current-boot BusyBox init script is `/etc/init.d/S60sdrd`. It verifies the
protected original `BOOT.bin` hash, IIOD presence, configuration, health and a
read-only radio snapshot before starting the daemon. Stop/rollback is:

```text
/etc/init.d/S60sdrd stop
rm /etc/init.d/S60sdrd
```

Removing the versioned `/sd/sdr-agent` files is not required to stop or roll
back the current boot.

## Artifact identity

```text
sdrd       ffa78ef33c2222adec81eed4c08caf03888a1bc458328bcc681590aba2e3eac9
sdrd.conf  94a82321f0d5d6f23a3bdc8d7b4f7d942a52a9000af33eecf276c80643c33c80
S60sdrd    c95a9c92a0a24f723f5b05844355bc9757ce9397bbd788e040ab70ecc5e3a4e7
```

The ARMv7 hard-float binary requires only GLIBC 2.17/2.4/2.7. Native C tests,
configuration validation, health probing and the local-IIO radio probe passed
before service start. The protected `/sd/BOOT.bin` remained
`02c7f8f84f003879fda27021bb243517ccf8e9b85e7404a37db2e4dda1d8b951`.

## Live controlled regression

The Pi production Adapter observed `can_retune=true`, `can_capture_iq=true`,
and `fpga_available=false`. One operator-approved bounded action used 2442 MHz,
2.1 MS/s, 2 MHz RF bandwidth, 4096 complex-int16 samples and a 16 KiB maximum.
It returned sequence 1, zero dropped samples and no overflow. The transient IQ
file hash was
`4f2e1b71219a376cbf1686b941c52294afbc30008dfec34c5f78b5399a8b01dc`.

After stop/restore, the radio read back 2452 MHz, 2.1 MS/s, 2 MHz bandwidth,
`slow_attack` and scan mask zero. IIOD and the controlled listener remained
healthy. No FPGA register, boot image, transmission path or firewall setting
changed.

## Cleanup and restart limitation

The raw IQ and exact development directories were deleted and verified absent:

```text
SDR: /tmp/sdr-agent-dev/agent-11-101/
SDR: /tmp/sdr-agent-dev/sdrd-personal-v1/
Pi:  /var/tmp/sdr-agent-dev/sdrd-personal-v1/
```

The P201 root filesystem is a writable RAM root loaded from
`/sd/uramdisk.image.gz`. Consequently `/etc/init.d/S60sdrd` does not survive an
SDR reboot even though the release under `/sd` does. Cross-reboot enablement
would require modifying and validating the ramdisk or boot chain, which is a
separate authorization and rollback gate. Until then, copy the retained
`/sd/sdr-agent/current/S60sdrd` into `/etc/init.d/S60sdrd` and start it after a
reboot, or leave the daemon stopped.
