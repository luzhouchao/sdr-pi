# P201Pro Reset Automation Hardware Review

Date: 2026-06-07 Asia/Shanghai

## Question

Can the P201Pro SDR `nRST`/`nGRST` hardware in the vendor schematic be used for fully automated reset after SD boot file updates?

Vendor hardware source inspected:

```text
G:\ROS开发\SDR P201P\04.硬件相关--Hardware\01.原理图--Schematic\PZSDR P201Pro P203Pro schematic.pdf
```

Rendered review images:

```text
E:\vivado\fpga_p201pro_accel\reports\schematic_page-03.png
E:\vivado\fpga_p201pro_accel\reports\schematic_page-04.png
E:\vivado\fpga_p201pro_accel\reports\schematic_page-05.png
E:\vivado\fpga_p201pro_accel\reports\schematic_page-15.png
```

## Findings

### Board-Level Reset

The schematic page `ZYNQ_CONFIG` shows:

- `K2` is a two-pin reset switch.
- Pressing `K2` pulls the reset net to ground.
- The reset net fans out as:
  - `nGRST`
  - `PL_nGRST`, through diode/cap/pull network
- `nGRST` connects to Zynq `PS_POR_B_500` on the `FPGA_PS` sheet.

Conclusion:

`nGRST` is a board-level hardware reset / power-on reset input. It can be driven externally by shorting the K2/nGRST node to ground, but it cannot be reliably driven by SDR Linux itself because asserting it resets the CPU that would be running the script.

### AD9361 Reset

The schematic page `FPGA_PL` shows:

```text
AD9631_nRST -> W19 -> IO_L22P_T3_34
AD9631_ENABLE -> N17 -> IO_L22N_T3_34
AD9631_EN_AGC -> P18 -> IO_L23P_T3_34
AD9631_SYNC_IN -> P15 -> IO_L23N_T3_34
```

The Vivado top/XDC confirms the same mapping:

```text
gpio_resetb -> W19
enable      -> N17
gpio_en_agc -> P18
gpio_sync   -> P15
```

The current promoted DTB contains the AD9361 reset GPIO:

```text
/axi/spi@e0006000/ad9361-phy@0
  reset-gpios = <&gpio0 67 0>;
  en_agc-gpios = <&gpio0 66 0>;
```

Conclusion:

AD9361 `RESETB` is software-controllable through the Zynq GPIO/EMIO path and is already described in the current Linux device tree. This is useful for AD9361 driver initialization and possible radio-only recovery, but it is not equivalent to removing board power.

## Automation Decision

The existing Windows -> NX -> SDR software automation can:

1. Copy SD boot files to `/sd`.
2. Run `sync`.
3. Issue Linux `reboot`.
4. Wait for SSH to return.
5. Run non-motion validation checks.

But this is only a warm reboot. It is not guaranteed equivalent to the physical power-cycle that successfully recovered the board during validation.

Validated behavior so far:

- Physical power-cycle: AD9361 and `cf-ad9361-lpc` probe correctly.
- Linux soft reboot: can leave AD9361 in `Calibration TIMEOUT` / probe `-110`.

Therefore:

- `nGRST` can be used for an external automated board reset only if controlled by hardware outside the SDR, such as an NX-controlled USB relay that shorts K2/nGRST to GND.
- For the most reliable automation, use an NX-controlled power relay/smart PDU/DC switch to fully power-cycle the SDR.
- AD9361 reset GPIO can be tested as a lighter recovery path, but it should not be treated as proven equivalent to physical power removal.

## Recommended Hardware Automation Options

Preferred:

```text
NX USB relay / smart DC switch -> SDR power input
```

This reproduces the validated physical power-cycle.

Acceptable experiment:

```text
NX USB relay dry contact -> SDR K2 reset switch pads / nGRST-to-GND
```

This automates board-level reset, but may not discharge RF/analog rails.

Software-only fallback:

```text
ssh root@192.168.1.10 "sync; reboot"
```

This is fast, but already observed to be insufficient for reliable AD9361 recovery.

## Safe Next Step

Do not wire anything to `nGRST` until the exact K2 pads/test point are identified physically with a multimeter.

If external automation hardware is available, start with a relay across K2 or a relay on SDR DC input, controlled from NX. Then validate using:

```bash
for d in /sys/bus/iio/devices/iio:device*; do [ -e "$d/name" ] && echo "$d $(cat "$d/name")"; done
dmesg | grep -E 'ad9361|cf_axi_adc|79020000|79024000|Tuning|Calibration TIMEOUT'
```
