# AD9361 LVDS Bias Final Validation

Date: 2026-06-07

## Final SD Boot Hashes On SDR

```text
bf8d4cb84f258967b05193cf3f37cc5b6cadb9a395fbf13ccdd67b252b13e918  /sd/BOOT.bin
960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a  /sd/devicetree.dtb
2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f  /sd/uEnv.txt
e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5  /sd/uImage
0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55  /sd/uramdisk.image.gz
```

## Runtime DT

```text
adi,digital-interface-tune-skip-mode = <0>
adi,lvds-mode-enable present
adi,lvds-bias-mV = <150>
adi,lvds-rx-onchip-termination-enable present
adi,full-port-enable missing
adi,swap-ports-enable missing
adi,rx-data-clock-delay = <4>
adi,rx-data-delay = <4>
adi,tx-fb-clock-delay = <7>
```

## Probe Result

```text
ad9361 spi1.0: ad9361_probe : AD936x Rev 0 successfully initialized
cf_axi_dds 79024000.cf-ad9361-dds-core-lpc: probed DDS AD9361
cf_axi_adc 79020000.cf-ad9361-lpc: probed ADC AD9361 as MASTER
```

IIO devices:

```text
ad9361-phy
xadc
cf-ad9361-dds-core-lpc
cf-ad9361-lpc
```

## Key Registers

```text
REG_LVDS_BIAS_CTRL 0x03c = 0x21
REG_LVDS_INVERT_CTRL1 0x03d = 0xff
REG_LVDS_INVERT_CTRL2 0x03e = 0x0f
REG_RX_CLOCK_DATA_DELAY 0x006 = 0x01
REG_TX_CLOCK_DATA_DELAY 0x007 = 0x30
```

## Tap Validation

After tap clear/enable/wait:

```text
0x79020000 = 0x000A0162
0x79024000 = 0x00090162
0x43C00030 DEBUG_FLAGS  = 0x00000017
0x43C00034 DEBUG_CLK    = 0x000000FA
0x43C00038 DEBUG_VALID  = 0x03EBCB24
0x43C0003c DEBUG_ACCEPT = 0x00000040
```

## PN BIST Validation

Normal `pseudorandom_err_check` reports Out of Sync when PN is not enabled, which is expected.

With `bist_prbs=2`, RX delay sweep showed many delay values where all four channels report:

```text
CH0 : PN9 : In Sync : OK
CH1 : PN9 : In Sync : OK
CH2 : PN9 : In Sync : OK
CH3 : PN9 : In Sync : OK
```

The key root fix was enabling LVDS bias and on-chip termination:

```text
adi,lvds-bias-mV = <150>
adi,lvds-rx-onchip-termination-enable
```

## Final Deliverable Update

Promoted fixed DTB into:

```text
E:\vivado\fpga_p201pro_accel\deliverables\p201pro_2t2r_sd_ready\boot\devicetree.dtb
```

Final deliverable hash:

```text
960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a  boot\devicetree.dtb
```
