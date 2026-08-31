# AD9361 LVDS Skip-Tune Experiment

Date: 2026-06-07

This package follows the LVDS auto-tune experiment.

## Current Finding

The LVDS auto-tune DTB was loaded correctly:

```text
adi,lvds-mode-enable present
adi,full-port-enable missing
adi,swap-ports-enable missing
adi,digital-interface-tune-skip-mode = <0>
adi,tx-fb-clock-delay = <7>
```

But AD9361 RX tuning still failed:

```text
SAMPL CLK: 61440000 tuning: RX
ad9361 spi1.0: ad9361_dig_tune_delay: Tuning RX FAILED!
cf_axi_adc: probe of 79020000.cf-ad9361-lpc failed with error -5
```

The tap saw `DEBUG_VALID` before clear, but not after clear/wait. This package keeps LVDS mode and skips AD9361 digital tuning to test whether RX IIO can register and whether the RX valid path is stable enough for further PN checks.

## DTB Changes

Only `boot\devicetree.dtb` differs from the LVDS auto-tune package:

```text
adi,digital-interface-tune-skip-mode <2>
adi,lvds-mode-enable                 present
adi,full-port-enable                 missing
adi,swap-ports-enable                missing
adi,rx-data-clock-delay              <4>
adi,rx-data-delay                    <4>
adi,tx-fb-clock-delay                <7>
```

Expected DTB SHA256:

```text
382cfe8d37ae33baabe7aad45782aeefacffeafd96fb2fefa359d9d71c4c852e  boot\devicetree.dtb
```

## Copy To SD

Copy these five files to the FAT boot partition of the copied/new SD card:

```text
boot\BOOT.bin
boot\devicetree.dtb
boot\uEnv.txt
boot\uImage
boot\uramdisk.image.gz
```

Do not modify the original vendor SD backup directory.

## Validation

After power-cycle:

```bash
sha256sum /sd/BOOT.bin /sd/devicetree.dtb /sd/uEnv.txt /sd/uImage /sd/uramdisk.image.gz
dmesg | grep -E 'ad9361|cf_axi_adc|79020000|SAMPL CLK|Tuning'
for d in /sys/bus/iio/devices/iio:device*; do [ -e "$d/name" ] && echo "$d $(cat $d/name)"; done
cat /sys/kernel/debug/iio/iio:device3/pseudorandom_err_check
devmem 0x43C00030 32
devmem 0x43C00034 32
devmem 0x43C00038 32
devmem 0x43C0003c 32
```
