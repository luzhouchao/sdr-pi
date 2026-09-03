# P201 persistent Dropbear host-key investigation — 2026-09-03

## Scope and safety boundary

This was a read-only investigation of the real P201 startup chain and
persistent storage.  It did not stop a service, capture IQ, change a radio
attribute, update `known_hosts`, mount or format `mtd2`, write QSPI, or modify
`BOOT.bin`, uramdisk or any other boot component.  Strict SSH host-key checking
remained enabled throughout.

The repository was clean at `02601b71dfa4da438bdbf1e3edca7c132669503e`,
which matched both the local and remote `origin/main`.  Strict SSH selected the
currently pinned P201 ECDSA key
`SHA256:i1Lnt/81XecFwnrhkIMSzo20C6+4bRVWvqmANS8L5Cs`.  The direct-link MAC was
`00:0a:35:00:01:22`, and the platform was `pzp201pro`, ARMv7, Linux 5.10.

## Actual boot and Dropbear order

BusyBox init uses `/etc/inittab`.  Its relevant order is:

1. `mount -a` runs before `/etc/init.d/rcS`.
2. `/etc/fstab` asks for `mtd2 /mnt/jffs2 jffs2 rw,noatime`.
3. `rcS` runs `/etc/init.d/S??*` lexically.
4. `S21misc` checks `/mnt/jffs2/etc/dropbear/keys.md5` and, only when the
   complete manifest verifies, copies `dropbear*` into the RAM-backed
   `/etc/dropbear/` directory.
5. `S21netipset` mounts `/dev/mmcblk0p1` as VFAT at `/sd` and then attempts to
   execute `/sd/netipsetsd.sh`.  That optional file is currently absent.
6. `S40network` configures the direct Ethernet link.
7. `S50dropbear` starts `/usr/sbin/dropbear` with `-R`; there is no
   `/etc/default/dropbear`.  With no restored key, `-R` generates fresh default
   keys under `/etc/dropbear/` in the volatile RAM root.

The live keys were therefore generated at
`/etc/dropbear/dropbear_ecdsa_host_key` and
`/etc/dropbear/dropbear_rsa_host_key`.  Their timestamps were from the current
boot, both were mode `0600`, and the ECDSA private-file SHA-256 was
`94f17b9d3a5f01546ac7d89880d1de6a9cc2cfab0ecd68222bd857cda11c370b`.
No private key contents were read or copied into the repository.

## Persistent storage findings

`/sd` is a persistent 30,615,920-KiB VFAT filesystem mounted before Dropbear,
but after the vendor `S21misc` key-restore hook.  Its mount options force
directory/file permissions that cannot protect a server private key as
mode `0600`; the live `/sd/sdr-agent` files appear as `0755`.  Creating the
optional `/sd/netipsetsd.sh` hook could copy a key into RAM before Dropbear, but
the source private key would remain physically removable and world-readable
under VFAT semantics.  This is not an acceptable host-identity store.

The vendor-reserved persistent key mechanism is QSPI partition `mtd2`, named
`qspi-nvmfs`.  Read-only inspection reported:

```text
type                    MTD_NORFLASH
size                    917504 bytes (896 KiB)
erase size              65536 bytes (14 erase blocks)
bad blocks              0
current SHA-256          a2fd1c02d41519e207b25375bf2953212dd882282ead25d5bc7666df692ebf96
non-0xff bytes           14, all in the first erase block
valid JFFS2 nodes        0
mounted at /mnt/jffs2    no
```

`jffs2dump -v` found no node.  The kernel boot log independently reported no
JFFS2 magic at offsets 0, 4, 8 and 12, 13 empty blocks, zero bad blocks, and:

```text
Cowardly refusing to erase blocks on filesystem with no valid JFFS2 nodes
```

Thus “blank” means no valid filesystem, not a byte-for-byte erased device.  A
14-byte residual header would be destroyed by initialization.

The vendor setup helper `/usr/sbin/device_format_jffs2` does exactly this after
an interactive `yes`: unmount `/mnt/jffs2`, run
`flash_erase -j /dev/mtd2 0 0`, then run `mount -a`.  There is no non-formatting
repair or initialization path.  The companion `device_persistent_keys` script
targets the same mounted filesystem and the exact early `S21misc` restore
contract.  On this image it copies only the ECDSA key but generates its
checksum manifest from every live `dropbear*` key, so invoking it unmodified
while the volatile RSA key also exists would create a manifest that cannot
verify after reboot.  An approved deployment must create a one-key ECDSA
manifest explicitly instead of relying on that buggy helper invocation.

## Candidate assessment

| Candidate | Startup feasibility | Security and rollback | Decision |
|---|---|---|---|
| Keep repinning `known_hosts` | Works only after an operator re-verifies the device | Strict recovery correctly fails before the repin; not unattended | Current fail-closed fallback only |
| `StrictHostKeyChecking=no`, `accept-new`, or automatic replacement | Technically connects | Removes the required identity gate and can accept an impostor | Rejected |
| Store/copy a private key from `/sd` via `netipsetsd.sh` | `/sd` is mounted before `S50dropbear` | VFAT cannot protect the source key; removable-media compromise persists until every client is repinned | Rejected |
| Modify `/etc/default/dropbear`, `S21misc`, `S50dropbear`, rootfs or uramdisk | Could select another key path | RAM changes vanish; persistent changes modify the retired/prohibited boot image | Rejected |
| Derive a deterministic key from MAC/serial or fetch it unauthenticated from AGX | Could run from the optional `/sd` hook | Public inputs or unauthenticated bootstrap disclose the host identity key and do not establish trust | Rejected |
| Store key material in U-Boot environment or another QSPI partition | Early and persistent | Not a vendor secret store; risks boot-critical `mtd1`, `mtd0` or `mtd3` | Rejected |
| Initialize `mtd2` as vendor JFFS2 and persist the ECDSA key | Native boot order and restore hook already exist | Correct permissions and narrow rollback are possible, but initialization irreversibly erases all 14 blocks | Only acceptable design; approval required |

## Proposed approved operation

The following is a reviewable procedure, not authorization.  None of these
write commands was run.  Use a fresh feature/release ID at execution time.

1. Recheck strict SSH, direct-link MAC/platform/protected BOOT hash, `/proc/mtd`,
   current `mtd2` hash, zero active/faulted SDRD session, buffer 0, scan mask 0,
   exactly one daemon/listener, and all retained release hashes.
2. Create a mode-`0700` AGX feature directory and a root-owned mode-`0700`
   retained rollback release.  Before any erase, stream all 917,504 bytes from
   `/dev/mtd2` over the already strictly verified SSH connection into
   `p201-mtd2-before.bin`, require exactly 917,504 bytes, set mode `0600`, and
   record its SHA-256.  Keep this image outside feature cleanup until the
   rollback window closes.
3. On P201, execute the vendor formatter interactively and supply `yes` only
   after the preceding gates:

   ```sh
   /usr/sbin/device_format_jffs2
   ```

   Its consequential command is exactly:

   ```sh
   flash_erase -j /dev/mtd2 0 0
   ```

4. Require `/dev/mtdblock2` to be mounted as JFFS2 at `/mnt/jffs2`.  Create
   `/mnt/jffs2/etc/dropbear` as mode `0700`, copy only the currently verified
   ECDSA host key as mode `0600`, and generate `keys.md5` from that one basename
   inside the persistent directory.  Do not persist passwords, `shadow`,
   `authorized_keys` or the volatile RSA key.  `sync`, re-read the files and
   retain hashes.
5. Exercise a real reboot.  Require the same ECDSA public fingerprint under
   `StrictHostKeyChecking=yes`, a successful JFFS2 mount before `S21misc`, one
   recovered `sdrd`, one 43110 listener, a healthy/idle SDRD/1 status, and exact
   radio/buffer/channel restoration.  Then exercise the existing recovery
   rollback without altering the host key.

The persistent impact is limited to erasing and initializing all 917,504 bytes
of QSPI `mtd2`; it does not address `mtd0`, `mtd1`, `mtd3`, `BOOT.bin`, uramdisk
or FPGA state.  Risks are loss of the current 14 residual bytes, NOR wear, and
an unmountable or incomplete filesystem if power fails during erase/write.

If rollback is required, first unmount `/mnt/jffs2`, erase only `/dev/mtd2`
without adding JFFS2 cleanmarkers, stage the verified pre-image under the
feature-scoped P201 temporary root, and restore exactly 917,504 bytes with:

```sh
flash_erase /dev/mtd2 0 0
mtd_debug write /dev/mtd2 0 917504 /tmp/sdr-agent-dev/<feature-id>/p201-mtd2-before.bin
sync
```

Then re-read and require the original SHA-256
`a2fd1c02d41519e207b25375bf2953212dd882282ead25d5bc7666df692ebf96`.
That rollback intentionally returns to the current unmountable/no-valid-node
state, so cross-reboot recovery again requires a manual verified host-key
repin.  Failure to reproduce the hash is a hard stop and must not be followed
by writes to another MTD partition.

## Conclusion

There is no safe non-formatting path in the current vendor image.  The existing
AGX recovery remains safe for the current P201 boot and after AGX reboot, while
strict SSH continues to fail closed after a P201 reboot.  Removing the manual
repin requires explicit operator authorization to initialize `mtd2`; until
then the parent checklist item must remain open.
