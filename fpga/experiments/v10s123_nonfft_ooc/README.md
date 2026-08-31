# V10S1/S2/S3 Non-FFT OOC

Combined out-of-context synthesis wrapper for the V10S1 quality, V10S2
frame/window, and V10S3 energy/peak modules.

## Contents

- `rtl/p201_v10s123_nonfft_ooc_top.v`: OOC-only wrapper.

## Status

Combined OOC synthesis passed. This directory has no AXI self-test page, no
bitstream, no SD payload, and no hardware validation.

## Use

Use this as a PC gate before packaging the modules into an isolated SDR-testable
candidate such as V10S4 or V10S5.
