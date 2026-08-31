# AD9361 RX Digital Tune Probe

Date: 2026-06-07

## Runtime Symptom

SDR boots with the diagnostic `BOOT.bin`, but RX IIO buffer registration fails:

```text
SAMPL CLK: 30720000 tuning: RX
  0:1:2:3:4:5:6:7:8:9:a:b:c:d:e:f:
0:# # # # # # # # # # # # # # # #
1:# # # # # # # # # # # # # # # #
ad9361 spi1.0: ad9361_dig_tune_delay: Tuning RX FAILED!
cf_axi_adc: probe of 79020000.cf-ad9361-lpc failed with error -5
```

Current IIO devices:

```text
ad9361-phy
xadc
cf-ad9361-dds-core-lpc
```

Missing:

```text
cf-ad9361-lpc
```

## Runtime Device Tree

Runtime AD9361 node:

```text
/axi/spi@e0006000/ad9361-phy@0
```

Key properties:

```text
compatible = "adi,ad9361"
adi,digital-interface-tune-skip-mode = <0>
adi,digital-interface-tune-fir-disable present
adi,rx-data-clock-delay = <4>
adi,rx-data-delay = <4>
adi,tx-fb-clock-delay = <4>
adi,tx-data-delay missing
adi,2rx-2tx-mode-enable present
```

The AD9361 AXI core and DDS core respond:

```text
devmem 0x79020000 32 = 0x000A0162
devmem 0x79024000 32 = 0x00090162
```

Tap diagnostic registers after retry:

```text
0x43C00030 DEBUG_FLAGS  = 0x00000011
0x43C00034 DEBUG_CLK    = growing
0x43C00038 DEBUG_VALID  = 0x00000000
0x43C0003c DEBUG_ACCEPT = 0x00000000
```

## Source Findings

ADI Linux `2019_R1` source:

- `drivers/iio/adc/ad9361_conv.c`
- `drivers/iio/adc/cf_axi_adc_core.c`
- `drivers/iio/adc/ad9361.c`
- `drivers/iio/adc/ad9361.h`

`ad9361_post_setup()` calls:

```c
ret = ad9361_dig_tune(phy, (axiadc_read(st, ADI_AXI_REG_ID)) ?
    0 : 61440000, flags);
if (ret < 0)
    goto error;
```

`ad9361_dig_tune_delay()` sweeps two 16-step delay rows:

```c
ad9361_set_intf_delay(phy, tx, i ? 15 : 0, i ? 15 - j : j, j == 0);
field[i][j] |= ad9361_check_pn(conv, tx, 4);
```

If both rows have no valid PN window:

```c
dev_err(&phy->spi->dev, "%s: Tuning %s FAILED!", __func__,
    tx ? "TX" : "RX");
return -EIO;
```

`cf_axi_adc_core.c` calls the converter `post_setup()` during probe. The returned `-EIO` propagates as:

```text
cf_axi_adc: probe of 79020000.cf-ad9361-lpc failed with error -5
```

Debugfs write semantics from `ad9361.c`:

```text
digital_tune expects two integers: max_freq flags
```

Flag values from `ad9361.h`:

```text
BE_VERBOSE       = 1
BE_MOREVERBOSE   = 2
DO_IDELAY        = 4
DO_ODELAY        = 8
SKIP_STORE_RESULT= 16
RESTORE_DEFAULT  = 32
```

Skip mode values:

```text
0 = TUNE_RX_TX
1 = SKIP_TX
2 = SKIP_ALL
```

## Online/Runtime Test

On SDR, debugfs has:

```text
/sys/kernel/debug/iio/iio:device0/digital_tune
/sys/kernel/debug/iio/iio:device0/bist_timing_analysis
/sys/kernel/debug/iio/iio:device0/bist_prbs
```

Controlled retry:

```bash
printf "61440000 3\n" > /sys/kernel/debug/iio/iio:device0/digital_tune
```

Result:

```text
digital_tune_rc=1
cf-ad9361-lpc still missing
DEBUG_VALID remains 0
```

## Conclusion

`79020000.cf-ad9361-lpc` probe failure is not an SD copy problem and not a tap AXI-Lite problem. It is the direct consequence of AD9361 RX digital-interface tuning failing with `-EIO`.

The all-`#` delay matrix means the PN monitor reports failure at every tested RX delay point. That is stronger than "wrong single delay value"; it points to one of:

- RX data/frame/PN path not reaching `axi_ad9361` correctly.
- AD9361 digital interface mode mismatch between device tree and bitstream.
- FPGA/DT delay defaults no longer valid for this board/bitstream.
- A reset/status condition in the RX AXI core prevents PN validation.

## Prepared Experiment

A non-main diagnostic boot package was prepared:

```text
E:\vivado\fpga_p201pro_accel\experiments\ad9361_skip_digital_tune_20260607
```

Only this DTB property was changed:

```text
adi,digital-interface-tune-skip-mode: <0> -> <2>
```

Patched DTB:

```text
db676ce0bdb9ef3765f4b0869ba2cb7c59d856711633fa797f79d0c3788bd340  boot\devicetree.dtb
```

Purpose:

- Test whether skipping AD9361 digital tuning allows `cf-ad9361-lpc` to probe.
- Test whether tap `DEBUG_VALID` recovers.

This is a diagnostic bypass, not the final root-cause fix.
