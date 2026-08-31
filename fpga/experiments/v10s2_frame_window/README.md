# V10S2 Frame Window

Reusable non-FFT RTL for sample framing, optional decimation, and lightweight
windowing.

## Contents

- `rtl/p201_v10s2_frame_window.v`: frame/window data path.
- `rtl/p201_v10s2_hann8_coeff.v`: small Hann coefficient helper.
- `test/tb_p201_v10s2_frame_window.v`: deterministic module testbench.

## Status

XSIM passed and the module is included in the V10S1/S2/S3 combined OOC pass.
It has no standalone SD payload and is not hardware validated.

## Integration Rule

Use this to remove repeated NX frame-boundary and pre-window bookkeeping only
after an isolated candidate passes the hardware gate.
