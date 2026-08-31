# NX Load Benchmark Baseline

Offline-only benchmark for deciding whether SUM8 aggregate, per-frame summary,
or future FFT/top-bin/band-power summary should be prioritized for FPGA offload.

This experiment does not use SSH, touch SDR `/sd`, start ROS, start the SDR
streaming runtime, or modify active `robot_control`.

Run from the repo root:

```powershell
python experiments\nx_load_benchmark_baseline\benchmark_nx_load_baseline.py `
  --iterations 100 `
  --out-json reports\stage_nx_load_benchmark_baseline\nx_load_benchmark_baseline.json
```

The script reads existing SUM8 evidence JSON under `reports\` when present, and
combines that with local synthetic-IQ CPU timing.
