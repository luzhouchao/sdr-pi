# AD9361 LVDS Tune Experiment

Date: 2026-06-07

This is the next diagnostic SD boot package after the skip-tune experiment.

## Why This Exists

The skip-tune DTB proved that `cf-ad9361-lpc` probe failure was caused by AD9361 digital tune returning `-EIO`. After bypassing tune, the RX IIO device registered, but all four RX channels still reported PN errors.

Runtime DT was using CMOS/full-port style properties:

```text
adi,full-port-enable present
adi,swap-ports-enable present
adi,lvds-mode-enable missing
```

The Vivado block design exposes differential AD9361 pins:

```text
axi_ad9361/rx_clk_in_p
axi_ad9361/rx_clk_in_n
axi_ad9361/rx_frame_in_p
axi_ad9361/rx_frame_in_n
axi_ad9361/rx_data_in_p
axi_ad9361/rx_data_in_n
```

The vendor no-OS defaults also use LVDS mode. Therefore this package switches the Linux DTB to LVDS mode and restores automatic digital tune.

## DTB Changes

Only `boot\devicetree.dtb` changed.

In `/axi/spi@e0006000/ad9361-phy@0`:

```text
adi,full-port-enable                 removed/replaced
adi,lvds-mode-enable                 added
adi,swap-ports-enable                removed
adi,digital-interface-tune-skip-mode <0>
adi,tx-fb-clock-delay                <7>
adi,rx-data-clock-delay              <4>
adi,rx-data-delay                    <4>
```

Expected DTB SHA256:

```text
e8e438ccbbc3513d961aca00e4271db5c37a3460003ab5d4a72ea0ed57244008  boot\devicetree.dtb
```

## Copy To SD

Copy these five files to the FAT boot partition of a copied SD card or a new SD card:

```text
boot\BOOT.bin
boot\devicetree.dtb
boot\uEnv.txt
boot\uImage
boot\uramdisk.image.gz
```

Do not modify the original vendor SD backup directory.

## Validation After SDR Power Cycle

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
sha256sum /sd/BOOT.bin /sd/devicetree.dtb /sd/uEnv.txt /sd/uImage /sd/uramdisk.image.gz
dmesg | grep -E 'ad9361|cf_axi_adc|79020000|SAMPL CLK|Tuning'
for d in /sys/bus/iio/devices/iio:device*; do [ -e "$d/name" ] && echo "$d $(cat $d/name)"; done
cat /sys/kernel/debug/iio/iio:device3/pseudorandom_err_check
devmem 0x43C00030 32
devmem 0x43C00034 32
devmem 0x43C00038 32
devmem 0x43C0003c 32
```

Pass criteria:

- `cf-ad9361-lpc` appears.
- dmesg does not contain `Tuning RX FAILED`.
- `pseudorandom_err_check` reports `OK` for all active RX channels.
- tap `DEBUG_VALID` becomes non-zero after clear/wait.
