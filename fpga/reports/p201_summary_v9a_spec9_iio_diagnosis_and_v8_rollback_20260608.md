# P201Pro V9A SPEC9 IIO Diagnosis And V8 Rollback Staging

Date: 2026-06-08 18:04 Asia/Shanghai

Status: V9A remains NOT HARDWARE VALIDATED. V8 rollback payload is staged on SDR `/sd` and synced.

## Summary

I performed a read-only live check while V9A was still the active staged BOOT on SDR `/sd`.

The result reproduced the earlier V9A failure:

```text
/sd/BOOT.bin = 58de598eea686e857a5cbb82135fea6fca2c0c79904b65af5f1b4b5f5f259447
SUMMARY_VERSION = 0x53554D39
QUALITY_VERSION = 0x51554139
AGG_VERSION = 0x41474739
SPEC_VERSION = 0x53504339
SPEC_FRAME_ID = 0x00000006
SPEC_SAMPLES = 0x00000040
cf-ad9361-lpc missing
dmesg: SAMPL CLK: 61440000 tuning: TX
dmesg: ad9361_dig_tune_delay: Tuning TX FAILED!
dmesg: cf_axi_adc probe failed with error -5
```

Runtime device tree properties confirmed that the validated LVDS-bias DTB was still in use:

```text
adi,digital-interface-tune-skip-mode = <0>
adi,lvds-mode-enable present
adi,lvds-bias-mV = <150>
adi,lvds-rx-onchip-termination-enable present
adi,rx-data-clock-delay = <4>
adi,rx-data-delay = <4>
adi,tx-fb-clock-delay = <7>
```

This rules out a companion boot-file or DTB rollback issue. V8 and V9A use identical `devicetree.dtb`, `uEnv.txt`, `uImage`, `uramdisk.image.gz`, FSBL, and U-Boot hashes. The only boot payload difference is the V9A bitstream inside `BOOT.bin`.

## V8 Rollback Staging

The V8 local artifact gate was rechecked before writing SDR `/sd`:

```text
V8 Bootgen: PASS
V8 WNS +0.011 ns
V8 WHS +0.053 ns
V8 route fully routed
V8 routing errors 0
V8 sd_payload complete
V8 README and VERSION_ROUTE current
```

Then the five V8 `sd_payload` files were copied to SDR `/sd` and `sync` was run.

Before rollback staging:

```text
BOOT.bin          58de598eea686e857a5cbb82135fea6fca2c0c79904b65af5f1b4b5f5f259447
devicetree.dtb    960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a
uEnv.txt          2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f
uImage            e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5
uramdisk.image.gz 0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55
```

After rollback staging:

```text
BOOT.bin          6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb
devicetree.dtb    960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a
uEnv.txt          2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f
uImage            e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5
uramdisk.image.gz 0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55
```

Copy result: PASS. Remote hash check: PASS. `sync`: PASS.

Important: this only stages V8 for the next boot. The currently running Linux and PL state remain V9A until the SDR is physically power-cycled.

## Decision

Do not promote V9A.

V8 remains the current highest hardware-validated bypass candidate.

Next safe step:

```text
Physically power-cycle SDR.
Then verify /sd/BOOT.bin hash is V8.
Then verify AD9361/IIO health includes cf-ad9361-lpc.
Then read SUM8/QUA8/AGG8 identity registers and run the V8 validation script if needed.
```

Safety boundary observed: no ROS, SDR streaming runtime, mapping, RTAB-Map, `robot_controller`, `cmd_vel`, robot motion path, active `robot_control` modification, vendor package modification, or original SD backup modification.
