# P201 persistent Dropbear host-key validation — 2026-09-03

## Scope and authorization

The operator explicitly authorized initialization of only the P201 vendor NVM
partition `/dev/mtd2` after reviewing its whole-device impact. This delivery
used that authorization to persist the existing verified Dropbear ECDSA host
key and then live-validate strict unattended `sdrd` recovery across a real P201
reboot. It closes the last Chapter 3 startup item.

No capture was performed, so the finite capture maximum was zero bytes. No
password, `passwd`, `shadow`, group database, client `authorized_keys`, RSA key,
raw IQ or user result was copied. No operation addressed `mtd0`, `mtd1`,
`mtd3`, `/sd/BOOT.bin`, uramdisk, FPGA/MMIO/UIO, transmit or radio attributes.
`StrictHostKeyChecking=yes` remained in force, and the global `known_hosts`
file was never modified.

## Destructive-operation gate and rollback

The repository and remote began clean and synchronized at
`d63986ffa0c1cb69f5592fe6f88e665af109d494`. AGX Web, Planner, Spark and the
recovery timer were active; legacy Spectrum services were inactive and
disabled. SDRD/1 was healthy and idle with one PID/listener, no active,
profile-applied, armed or faulted session, buffer 0 and scan mask `0,0,0,0`.

Strict SSH selected the existing ECDSA fingerprint:

```text
SHA256:i1Lnt/81XecFwnrhkIMSzo20C6+4bRVWvqmANS8L5Cs
```

The mode-`0600` global `known_hosts` SHA-256 was
`c5d9b3e8521578f0f8b9ecde5426280b696b004f7e72ed1b675e39a5e474cd66`.
The direct-link MAC was `00:0a:35:00:01:22`, and the protected BOOT hash was
`02c7f8f84f003879fda27021bb243517ccf8e9b85e7404a37db2e4dda1d8b951`.

The exact target gate passed:

```text
mtd2 name                 qspi-nvmfs
type                      MTD_NORFLASH
size                      917504 bytes
erase size                65536 bytes
erase blocks              14
bad blocks                0
valid JFFS2 nodes         0
non-0xff bytes            14
pre-image SHA-256         a2fd1c02d41519e207b25375bf2953212dd882282ead25d5bc7666df692ebf96
```

Before erase, all 917,504 bytes were streamed through the already strictly
verified SSH connection into a mode-`0600` feature copy. An independently
hashed root-owned mode-`0600` retained rollback copy is at:

```text
/home/jetson/.local/lib/sdrharness/releases/20260903-p201-host-key-persistence-v1/p201-mtd2-before.bin
SHA-256 a2fd1c02d41519e207b25375bf2953212dd882282ead25d5bc7666df692ebf96
```

The release directory is root-owned/mode `0700` and also retains:

```text
ROLLBACK.txt
SHA-256 52f4560e6f1e27eab39d90f2079a461ef305e60a3f31549b9c33cb88f8c84794

VALIDATION.txt
SHA-256 fd6caa608bfeb7b7e86338e7a46ad3e3d3848424883e6726b0a96ef35e2775af
```

Rollback was not exercised because it would require a second full NOR erase,
return to the deliberately unmountable pre-feature state, and then another
erase to redeploy the key. The byte-exact backup, target/size gates and restore
commands were instead staged and hashed before the approved erase. Rollback
uses only `flash_erase /dev/mtd2 0 0` followed by
`mtd_debug write /dev/mtd2 0 917504 <verified-pre-image>` and must reproduce the
pre-image hash above.

## Initialization and minimal key store

The unchanged vendor helper hash was verified before it executed its confirmed
consequential command:

```text
flash_erase -j /dev/mtd2 0 0
```

All 14 blocks were erased and received a valid JFFS2 cleanmarker. The initial
post-command checker returned nonzero only because it incorrectly expected the
BusyBox `mount` display source to be `/dev/mtdblock2`; `/proc/mounts` correctly
reported the fstab source as `mtd2`. Read-only diagnosis proved that the
filesystem was already mounted `rw,noatime`, every block began with the JFFS2
`0x1985` cleanmarker, and `sdrd` was unchanged. No second erase was run.

The first key-install invocation also stopped before writing because it used
the same display-column predicate. The persistent file count remained zero.
The corrected gate used `/proc/mounts`, then wrote only:

```text
/mnt/jffs2/etc/dropbear/dropbear_ecdsa_host_key  mode 0600, 141 bytes
/mnt/jffs2/etc/dropbear/keys.md5                 mode 0600, one ECDSA entry
```

Both `/mnt/jffs2/etc` and its `dropbear` child are mode `0700`. The ECDSA
private-file SHA-256 is
`94f17b9d3a5f01546ac7d89880d1de6a9cc2cfab0ecd68222bd857cda11c370b`,
identical to the verified current-boot key. `md5sum -c` passed before and after
an explicit unmount plus `mount -a`. A full-file search proved that the two
listed files were the entire persistent store. The stable post-deployment raw
partition SHA-256 was
`613c51f0c7fdd6d9568b043f7218957979e9981b319c4a71a5fe9d94ae0a6294`.

The vendor `device_persistent_keys` helper was deliberately not used because
its broad companion behavior can persist password/client material and its
current manifest logic includes the volatile RSA key. The minimal store
matches the early `S21misc` restore contract without those side effects.

## Real reboot and strict recovery

The real reboot was initiated at
`2026-09-03T17:15:56.862485591+08:00`. After boot, without changing or copying
any host pin:

- the original global `known_hosts` file retained exactly the same SHA-256;
- `StrictHostKeyChecking=yes` authenticated the same ECDSA host;
- `/proc/uptime` proved a new P201 boot;
- `mtd2` was mounted as JFFS2 at `/mnt/jffs2` before `S21misc`;
- the restored RAM ECDSA key and persistent key both retained SHA-256
  `94f17b9d3a5f01546ac7d89880d1de6a9cc2cfab0ecd68222bd857cda11c370b`;
- `keys.md5` passed, permissions remained `0700/0600`, and the store still
  contained exactly two files.

The enabled AGX timer entered recovery at 17:16:12, copied the persistent init
entry only after the zero-PID/zero-listener gate, and completed at 17:16:14:

```text
p201_recovery_action=started pid_count=1 listener_count=1
daemon_sha256=458365bcd2231b622b8175ca618726ed9d7e16efb0e5c5c36f4ea22e30ae44dd
p201_recovery_result=healthy
```

A subsequent timer run returned `already_running`, preserving the same single
instance. To prove strict recovery remained functional after the reboot, the
unique healthy idle PID 1085 was then sent `SIGKILL` after the same execution,
buffer, executable and listener gates. Port 43110 was observed closed. The
timer recovered exactly one new PID 1738 in 25.793 seconds and again returned
healthy. Strict SSH still used the unchanged global pin.

## Final state and cleanup

Independent SDRD/1 and sysfs readback ended with:

```text
SDRD active/profile/armed/faulted  false / false / false / false
SDRD healthy/session_faulted       true / false
sdrd PID / 43110 listener count    1738 / 1
deployed executable                /sd/sdr-agent/current/sdrd
LO / sample rate / bandwidth       2400000000 / 30720000 / 18000000 Hz
gain mode                          slow_attack
RX buffer / scan mask              0 / 0,0,0,0
JFFS2 persistent file count        2
```

The deployed daemon was not rebuilt or replaced. It remains:

```text
/sd/sdr-agent/releases/20260903-sigpipe-nosignal-v1/sdrd
/sd/sdr-agent/current/sdrd
SHA-256 458365bcd2231b622b8175ca618726ed9d7e16efb0e5c5c36f4ea22e30ae44dd

/sd/sdr-agent/releases/20260903-pre-sigpipe-v1/sdrd
SHA-256 0b1b6ac63323d4dd81401e3656855428786588aafcca001411a9f21b7f51ada0
```

The exact transient AGX directory
`/var/tmp/sdrharness-dev/p201-host-key-persistence-20260903/` (924,022 bytes)
was removed after its byte size and retained hashes were recorded, and its
absence was verified. No P201 transient capture directory was created. The
root-only rollback release, Web results, databases, models, credentials,
persistent toolchain and all SDR releases were retained.
