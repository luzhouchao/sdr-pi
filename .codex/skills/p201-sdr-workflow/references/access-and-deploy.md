# P201 access, cross-build and deployment

## Fixed endpoint and credential handling

- Host: `192.168.1.10`
- SSH user: `root`
- IIOD: `30431`
- controlled `sdrd`: `43110`
- password file: `/home/jetson/.config/sdrharness/p201-root.password`

Verify the password file is a regular mode-0600 file. Never read its contents.
For non-interactive access use:

```bash
sshpass -f /home/jetson/.config/sdrharness/p201-root.password \
  ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 \
  root@192.168.1.10 '<bounded command>'
```

P201 BusyBox does not provide `ss` or GNU `stat`. Use `pidof`,
`netstat -lnt`, `ls -l`, `readlink`, `sha256sum` and explicit file tests.

## Read-only preflight

Before starting, stopping or replacing the daemon:

1. Probe AGX TCP connectivity with a 3-second timeout.
2. On P201, record `pidof sdrd` and `netstat -lnt | grep 43110`.
3. Require exactly one PID when updating a running deployment, or no PID and no
   listener when recovering after reboot. Never infer safety from the port alone.
4. Verify these persistent files:
   `/sd/sdr-agent/current/sdrd`, `sdrd.conf`, and `S60sdrd`.
5. Hash the current daemon and preserve it in a distinct rollback release before
   replacement.

If 43110 is already listening, do not run the recovery start command. If PID and
listener disagree, diagnose and normalize them before proceeding.

## Compatible controlled-mode cross-build

The P201 is ARMv7 hard-float with glibc 2.28. Controlled mode dynamically loads
the target libiio, so the artifact must be dynamically linked against an older
compatible glibc. Static glibc controlled-mode binaries are rejected.

The first verified build path uses the Windows/Xilinx SDK 2019.1 toolchain:

```powershell
powershell -ExecutionPolicy Bypass -File `
  sdr-system/sdrd/scripts/build-armhf-xilinx.ps1
```

Default toolchain directory in that script:

```text
E:\Xilinx\SDK\2019.1\gnu\aarch32\nt\gcc-arm-linux-gnueabi\bin
```

An equivalent Linux invocation is allowed when `P201_ARMHF_TOOLCHAIN_BIN`
points to the same Xilinx 2019.1 hard-float toolchain family:

```bash
p201_cc="$P201_ARMHF_TOOLCHAIN_BIN/arm-linux-gnueabihf-gcc"
p201_strip="$P201_ARMHF_TOOLCHAIN_BIN/arm-linux-gnueabihf-strip"
p201_readelf="$P201_ARMHF_TOOLCHAIN_BIN/arm-linux-gnueabihf-readelf"
test -x "$p201_cc" -a -x "$p201_strip" -a -x "$p201_readelf"
make -C sdr-system/sdrd clean all \
  CC="$p201_cc" BUILD_DIR=<AGX-feature-directory>/sdrd-build
"$p201_strip" <AGX-feature-directory>/sdrd-build/sdrd
file <AGX-feature-directory>/sdrd-build/sdrd
"$p201_readelf" --version-info <AGX-feature-directory>/sdrd-build/sdrd
sha256sum <AGX-feature-directory>/sdrd-build/sdrd
```

The verified AGX-native fallback uses the official Arm GNU 8.2-2018.08
x86-64-hosted hard-float toolchain inside an amd64 container. Its archive is:

```text
https://armkeil.blob.core.windows.net/developer/Files/downloads/gnu-a/8.2-2018.08/gcc-arm-8.2-2018.08-x86_64-arm-linux-gnueabihf.tar.xz
SHA-256 5b3f20e1327edc3073e545a5bd3d15f33e7f94181ff4e37a76e95924c1b439b9
```

Keep the archive, extracted toolchain and output below the AGX feature
directory. On aarch64 AGX, require working amd64 binfmt support (for example,
`qemu-user-static`) and run the compiler in an amd64 Docker container with the
repository mounted read-only. Compile only `main.c`, `sdrd.c`, and
`sdrd_iio.c`, then strip with the same toolchain. The retired FPGA/MMIO sources
are no longer present. The 2026-09-01 live deployment produced ELF32 ARM EABI5
hard-float and required only `GLIBC_2.4`, `GLIBC_2.7` and `GLIBC_2.17`.

Deployment gate:

- ELF 32-bit ARM, EABI5, dynamically linked, hard-float interpreter.
- `nm`/symbol inspection shows no linked FPGA/MMIO code in the Linux/IIO-only
  daemon.
- Required GLIBC versions are listed and none exceed the target. For both
  verified builds, only `GLIBC_2.4`, `GLIBC_2.7` and `GLIBC_2.17` appear.
- `--check-config`, `--probe`, and read-only `--probe-radio` pass on P201 before
  serving.

The AGX Ubuntu compiler at `/usr/bin/arm-linux-gnueabihf-gcc` is not a verified
compiler/sysroot combination and currently emits GLIBC 2.33/2.34 requirements.
Do not deploy its default output. Do not use the repository's static Docker
artifact for controlled mode.

## Staging and replacement

Use one feature ID and these roots:

- AGX: `/var/tmp/sdrharness-dev/<feature-id>/`
- P201: `/tmp/sdr-agent-dev/<feature-id>/`
- persistent release: `/sd/sdr-agent/releases/<release-id>/`

Stage the new binary in the P201 transient directory, verify its hash, and run
the three non-serving probes. Preserve the currently deployed binary/config/
init script in a rollback release.

Stop the old daemon while its on-disk executable is still unchanged. Do not
trust the init script's printed `OK`: poll until `pidof sdrd` returns nothing
and 43110 has no listener. Abort replacement if either remains. Only then copy
the new release into `/sd/sdr-agent/current/`, using a same-directory temporary
name followed by `mv`.

Start with `/etc/init.d/S60sdrd start`, then require:

- exactly one `sdrd` PID;
- exactly one `192.168.1.10:43110` listener;
- expected deployed hash;
- AGX TCP probe success;
- read-only Controller `HELLO`, `CAPABILITIES`, `HEALTH`, `QUIT` success.

If startup or a probe fails, leave capture disabled, restore the rollback binary
with the same stop/clear/replace/start sequence, and verify the previous hash and
single listener.

## Reboot recovery

`sdrd` does not survive a P201 reboot. Recovery is allowed only after confirming
both no PID and no 43110 listener. Then copy the persistent init script to the
RAM root and start it:

```bash
test "$(pidof sdrd 2>/dev/null | wc -w)" -eq 0
! netstat -lnt 2>/dev/null | grep -q ':43110 '
cp /sd/sdr-agent/current/S60sdrd /etc/init.d/S60sdrd
chmod 0755 /etc/init.d/S60sdrd
/etc/init.d/S60sdrd start
```

Never run recovery when a daemon is already present.

## Receive-only validation record

Before a live sweep, record frequency range/centers, sample rate, RF bandwidth,
fixed gain, dwell, point count, samples per point, exact maximum bytes,
estimated duration, AGX available bytes, AGX result directory and P201 transient
directory. The plan must expose `/stop` and restore saved LO, sample rate,
bandwidth, gain mode/gain and scan mask on success, error and cancel.

After the feature, stop feature processes, validate exact resolved transient
paths, delete only those development directories, and verify absence. Do not
delete user-visible AGX results unless the operator chooses the Web delete
action.
