#!/usr/bin/env python3
from __future__ import annotations

import runpy
from pathlib import Path


def main() -> None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "experiments" / "nx_load_benchmark_baseline" / "benchmark_nx_load_baseline.py"
        if candidate.exists():
            runpy.run_path(str(candidate), run_name="__main__")
            return
    raise SystemExit("Cannot find experiments/nx_load_benchmark_baseline/benchmark_nx_load_baseline.py from this checkout.")


if __name__ == "__main__":
    main()
