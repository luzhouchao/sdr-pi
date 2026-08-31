# AD9361 LVDS Tune After-Reboot Validation

Date: 2026-06-07

## Boot Files On SDR

The SDR boot partition contains the LVDS auto-tune experiment DTB:

```text
bf8d4cb84f258967b05193cf3f37cc5b6cadb9a395fbf13ccdd67b252b13e918  /sd/BOOT.bin
e8e438ccbbc3513d961aca00e4271db5c37a3460003ab5d4a72ea0ed57244008  /sd/devicetree.dtb
2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f  /sd/uEnv.txt
e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5  /sd/uImage
0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55  /sd/uramdisk.image.gz
```

## Runtime Device Tree

The LVDS DTB patch is active:

```text
compatible = adi,ad9361
adi,digital-interface-tune-skip-mode = <0>
adi,digital-interface-tune-fir-disable present
adi,lvds-mode-enable present
adi,full-port-enable missing
adi,swap-ports-enable missing
adi,rx-data-delay = <4>
adi,rx-data-clock-delay = <4>
adi,tx-fb-clock-delay = <7>
adi,tx-data-delay missing
adi,2rx-2tx-mode-enable present
```

## Probe Result

RX auto tune still fails:

```text
SAMPL CLK: 61440000 tuning: RX
ad9361 spi1.0: ad9361_dig_tune_delay: Tuning RX FAILED!
cf_axi_adc: probe of 79020000.cf-ad9361-lpc failed with error -5
```

IIO devices:

```text
ad9361-phy
xadc
cf-ad9361-dds-core-lpc
```

`cf-ad9361-lpc` is still absent under LVDS auto-tune.

## Tap Result

Before clear:

```text
DEBUG_CLK   = 0x000021FF
DEBUG_VALID = 0x000004BC
```

After clear/enable/wait:

```text
DEBUG_CLK grows
DEBUG_VALID = 0
DEBUG_ACCEPT = 0
```

Interpretation:

- LVDS mode changes the AD9361 sample clock to 61.44 MHz during tune.
- Some RX valid activity was seen before clear, but it does not persist after the failed probe path settles.
- LVDS mode alone is not sufficient while auto tune is required at boot.

## Prepared Next Experiment

Prepared package:

```text
E:\vivado\fpga_p201pro_accel\experiments\ad9361_lvds_skip_tune_20260607
```

Only DTB tune-skip differs from LVDS auto-tune:

```text
adi,digital-interface-tune-skip-mode <2>
adi,lvds-mode-enable                 present
adi,full-port-enable                 missing
adi,swap-ports-enable                missing
adi,rx-data-clock-delay              <4>
adi,rx-data-delay                    <4>
adi,tx-fb-clock-delay                <7>
```

Patched DTB:

```text
382cfe8d37ae33baabe7aad45782aeefacffeafd96fb2fefa359d9d71c4c852e  boot\devicetree.dtb
```
