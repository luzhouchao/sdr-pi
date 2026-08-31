# `sdrd` shadow validation

Date: 2026-08-31

## Scope

This validation covers the read-only C control plane only. It does not retune
the AD9361, create an IIO buffer, write FPGA registers, start a persistent
service, replace IIOD, change `BOOT.bin`, or claim FPGA acceleration.

## Original BOOT confirmation

The SDR baseline hash and protected original backup match exactly:

```text
SHA-256 02c7f8f84f003879fda27021bb243517ccf8e9b85e7404a37db2e4dda1d8b951
```

The deployed shadow configuration therefore keeps `fpga_backend=disabled`.

## Native validation

- C11 build with `-Wall -Wextra -Wpedantic -Werror`: PASS.
- Configuration parser and safety gates: PASS.
- Fake IIO sysfs health discovery: PASS.
- Fake UIO SUM8 identity/capability read: PASS.
- `/dev/mem` without `allow_devmem=true`: rejected as designed.
- Mutating SDRD/1 commands in shadow mode: rejected as designed.
- AddressSanitizer and UndefinedBehaviorSanitizer test run: PASS.
- Loopback TCP HELLO/CAPABILITIES/QUIT exchange: PASS.

## ARMv7 artifact

```text
ELF 32-bit LSB ARM EABI5
hard-float ABI
statically linked
stripped
size: approximately 415 KiB
SHA-256 99961bb4e0a430e8c21a9e5a58ebbd316f19070f53587612848a12b32c2bba12
```

The artifact executed successfully from `/tmp` on the Raspberry Pi's aarch64
kernel and passed `--check-config`. This proves executable/ABI viability but is
not an SDR-local health validation. Temporary Pi files were removed.

## SDR-local result

The static binary and shadow configuration were copied through the Raspberry Pi
to the SDR `/tmp` directory. The target ran only:

```text
sdrd --config sdrd-shadow.conf --check-config
sdrd --config sdrd-shadow.conf --probe
```

Observed result:

- architecture `armv7l`;
- artifact SHA-256 matched `99961bb4...ba12`;
- `/sd/BOOT.bin` matched the protected original hash `02c7f8f8...951`;
- `0x43c00000` remained absent from `/proc/iomem`;
- `ad9361-phy` and `cf-ad9361-lpc` were visible;
- `healthy=true` and `health_flags=0`;
- FPGA backend, mapping, identity and aggregation remained disabled/false.

## Pi-to-SDR protocol result

The daemon was then started manually from `/tmp` for a bounded network smoke
test on `192.168.1.10:43110`. The Pi successfully completed:

```text
SDRD/1 HELLO 101
SDRD/1 HEALTH 102
SDRD/1 QUIT 103
```

The response preserved request IDs, reported `mode=shadow`, rejected mutating
capability, and returned healthy IIO state. The daemon was stopped immediately.
The binary, configuration, PID and log were removed from the SDR; the relay
copies were also removed from the Pi.

No init entry, persistent service, firewall rule, IIO setting, FPGA register or
boot file was changed. Enabling radio-control messages or an FPGA backend still
requires a separate reviewed implementation and validation gate.
