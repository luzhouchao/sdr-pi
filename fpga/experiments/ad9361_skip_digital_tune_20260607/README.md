# AD9361 Skip Digital Tune Experiment

Date: 2026-06-07

This is a narrow diagnostic boot-file experiment for the P201Pro SDR. It is not a replacement for the main SD-ready deliverable.

## Purpose

Current SDR boot fails the AD9361 RX digital-interface tuning step:

```text
SAMPL CLK: 30720000 tuning: RX
0:# # # # # # # # # # # # # # # #
1:# # # # # # # # # # # # # # # #
ad9361 spi1.0: ad9361_dig_tune_delay: Tuning RX FAILED!
cf_axi_adc: probe of 79020000.cf-ad9361-lpc failed with error -5
```

ADI driver behavior shows this error is returned from `ad9361_dig_tune_delay()` as `-EIO`. The `cf_axi_adc` probe then fails from its AD9361 `post_setup()` callback, so the RX IIO buffer device `cf-ad9361-lpc` is not registered.

This experiment changes only:

```text
/axi/spi@e0006000/ad9361-phy@0/adi,digital-interface-tune-skip-mode
```

from:

```text
<0>  TUNE RX and TX
```

to:

```text
<2>  SKIP ALL, use device-tree/default clock-data delays
```

## Files

Copy these five files to the FAT boot partition of a copied SD card or a new SD card:

```text
boot\BOOT.bin
boot\devicetree.dtb
boot\uEnv.txt
boot\uImage
boot\uramdisk.image.gz
```

Do not copy files from this experiment into the original vendor SD backup directory.

## Hashes

See:

```text
HASHES.sha256
```

The only changed boot file relative to the main deliverable is:

```text
boot\devicetree.dtb
```

Expected SHA256:

```text
db676ce0bdb9ef3765f4b0869ba2cb7c59d856711633fa797f79d0c3788bd340  boot\devicetree.dtb
```

## Validation After SDR Reboot

From NX:

```bash
ssh root@192.168.1.10
```

password:

```text
analog
```

Check:

```bash
dmesg | grep -E 'ad9361|cf_axi_adc|79020000|SAMPL CLK|Tuning'
for d in /sys/bus/iio/devices/iio:device*; do [ -e "$d/name" ] && echo "$d $(cat $d/name)"; done
devmem 0x43C00030 32
devmem 0x43C00034 32
devmem 0x43C00038 32
devmem 0x43C0003c 32
```

Pass criteria for this experiment:

- `cf-ad9361-lpc` appears as an IIO device.
- dmesg no longer contains `ad9361_dig_tune_delay: Tuning RX FAILED!`.
- `DEBUG_VALID` at `0x43C00038` becomes non-zero after clear/wait.

If `cf-ad9361-lpc` appears but data quality is bad, the next step is a real AD9361 delay/window fix rather than keeping tune skipped as the final solution.
