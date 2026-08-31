# AD9361 Skip Tune After-Reboot Validation

Date: 2026-06-07

## Boot Files On SDR

The SDR boot partition contains the prepared skip-tune experiment DTB:

```text
bf8d4cb84f258967b05193cf3f37cc5b6cadb9a395fbf13ccdd67b252b13e918  /sd/BOOT.bin
db676ce0bdb9ef3765f4b0869ba2cb7c59d856711633fa797f79d0c3788bd340  /sd/devicetree.dtb
2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f  /sd/uEnv.txt
e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5  /sd/uImage
0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55  /sd/uramdisk.image.gz
```

## Runtime Device Tree

The patched property is active:

```text
compatible = adi,ad9361
adi,digital-interface-tune-skip-mode = <2>
adi,digital-interface-tune-fir-disable present
adi,rx-data-delay = <4>
adi,rx-data-clock-delay = <4>
adi,tx-fb-clock-delay = <4>
adi,tx-data-delay missing
adi,2rx-2tx-mode-enable present
```

## IIO Probe Result

The previous blocker is bypassed:

```text
/sys/bus/iio/devices/iio:device0 ad9361-phy
/sys/bus/iio/devices/iio:device1 xadc
/sys/bus/iio/devices/iio:device2 cf-ad9361-dds-core-lpc
/sys/bus/iio/devices/iio:device3 cf-ad9361-lpc
```

dmesg now reports:

```text
cf_axi_adc 79020000.cf-ad9361-lpc: ADI AIM (10.01.b) at 0x79020000 mapped to 0x(ptrval), probed ADC AD9361 as MASTER
```

No `ad9361_dig_tune_delay: Tuning RX FAILED!` line appears in the post-reboot relevant dmesg output.

## FPGA Tap Result

Core identity:

```text
0x79020000 = 0x000A0162
0x79024000 = 0x00090162
```

Tap before clear:

```text
0x43C00030 DEBUG_FLAGS  = 0x00000060
0x43C00034 DEBUG_CLK    = 0x000007A2
0x43C00038 DEBUG_VALID  = 0x00000003
0x43C0003c DEBUG_ACCEPT = 0x00000000
```

After clear/enable/wait:

```text
0x43C00000 CONTROL      = 0x00000001
0x43C00004 WINDOW       = 0x00000040
0x43C00008 STATUS       = 0x00000001
0x43C00030 DEBUG_FLAGS  = 0x00000051 / 0x00000071
0x43C00034 DEBUG_CLK    = growing
0x43C00038 DEBUG_VALID  = 0x00000000
0x43C0003c DEBUG_ACCEPT = 0x00000000
```

Interpretation:

- AD9361 `l_clk` is still reaching the tap.
- `cf-ad9361-lpc` now probes successfully.
- No sustained tap `adc_valid_i0` is seen while the IIO buffer/scan channels remain disabled.

## AXI-ADC / PN Status

Static IIO state:

```text
in_voltage_sampling_frequency = 30720000
buffer/enable = 0
scan_elements/in_voltage0_en = 0
scan_elements/in_voltage1_en = 0
scan_elements/in_voltage2_en = 0
scan_elements/in_voltage3_en = 0
```

AXI-ADC registers:

```text
0x79020040 RSTN    = 0x00000003
0x7902005C STATUS  = 0x00000009
0x79020404 CH0_STATUS = 0x00000004
0x79020444 CH1_STATUS = 0x00000004
0x79020484 CH2_STATUS = 0x00000004
0x790204C4 CH3_STATUS = 0x00000004
```

Debugfs PN check:

```text
CH0 : PN9 : In Sync : PN Error
CH1 : PN9 : In Sync : PN Error
CH2 : PN9 : In Sync : PN Error
CH3 : PN9 : In Sync : PN Error
```

## Conclusion

The skip-tune DTB experiment successfully proves that the previous `cf-ad9361-lpc` probe failure was caused by AD9361 digital tune returning `-EIO`.

This is not yet the final SDR/FPGA data-path fix:

- RX IIO device is now present.
- AD9361/AXI-ADC timing is still not clean because PN error remains on all four channels.
- Tap `DEBUG_VALID` does not persist after counter clear while no IIO buffer is enabled.

Next minimum engineering step:

1. Create a controlled DTB/uEnv delay sweep experiment for `adi,rx-data-delay`, `adi,rx-data-clock-delay`, and possibly `adi,tx-fb-clock-delay`.
2. Use `cf-ad9361-lpc` presence and `pseudorandom_err_check` as pass/fail.
3. Only after PN error clears should any real SDR sample path be considered.

## Live RX Delay Sweep

AD9361 register:

```text
REG_RX_CLOCK_DATA_DELAY = 0x006
high nibble = DATA_CLK_DELAY
low nibble  = RX_DATA_DELAY
```

The original runtime register value was:

```text
0x44
```

Two safe debugfs-only sweeps were run without enabling IIO buffer streaming:

1. Sweep `0x00..0xff` while BIST PRBS was off.
2. Sweep `0x00..0xff` after temporarily setting `bist_prbs=2` to inject RX PN, then restore `bist_prbs=0`.

Result:

```text
HIT_COUNT=0
RESTORED_RX_DELAY_REG=0x44
RESTORED_BIST_PRBS=0
```

Every combination still reported:

```text
CH0 : PN9 : In Sync : PN Error
CH1 : PN9 : In Sync : PN Error
CH2 : PN9 : In Sync : PN Error
CH3 : PN9 : In Sync : PN Error
```

This makes a simple RX delay value error unlikely. The stronger suspect is an AD9361 digital interface mode mismatch.

## Interface Mode Mismatch Finding

Runtime DT was CMOS/full-port style:

```text
adi,full-port-enable present
adi,swap-ports-enable present
adi,lvds-mode-enable missing
```

Vivado block design exposes differential AD9361 pins:

```text
axi_ad9361/rx_clk_in_p
axi_ad9361/rx_clk_in_n
axi_ad9361/rx_frame_in_p
axi_ad9361/rx_frame_in_n
axi_ad9361/rx_data_in_p
axi_ad9361/rx_data_in_n
```

The vendor no-OS defaults also set `lvds_mode_enable = 1` and `full_port_enable = 0`.

Prepared next experiment:

```text
E:\vivado\fpga_p201pro_accel\experiments\ad9361_lvds_tune_20260607
```

Patched DTB:

```text
e8e438ccbbc3513d961aca00e4271db5c37a3460003ab5d4a72ea0ed57244008  boot\devicetree.dtb
```

DTB changes:

```text
adi,full-port-enable                 removed/replaced
adi,lvds-mode-enable                 added
adi,swap-ports-enable                removed
adi,digital-interface-tune-skip-mode <0>
adi,tx-fb-clock-delay                <7>
adi,rx-data-clock-delay              <4>
adi,rx-data-delay                    <4>
```
