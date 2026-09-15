#!/usr/bin/env bash
# Read-only viewer; independent of the inference runner and its source pins.
export SDR_COLLECTION_PROGRESS_HELPER="$(cd -- "$(dirname -- "$0")" && pwd)/check-rml2018a-models.sh"
exec python3 -B - "$@" <<'PY'
import argparse
import json
import math
from pathlib import Path
import sys
import time
import os
import subprocess

parser = argparse.ArgumentParser(description="查看 RadioML 全量识别进度；Ctrl+C 只退出查看。")
parser.add_argument("--root", type=Path, default=Path(
    "/home/jetson/sdrharness/local-assets/amc-eval/results/mamba-guard-val-allquality-20260915"))
parser.add_argument("--interval", type=float, default=5, help="刷新间隔秒数，默认 5")
parser.add_argument("--once", action="store_true", help="只显示一次")
args = parser.parse_args()
if not math.isfinite(args.interval) or args.interval <= 0:
    parser.error("刷新间隔必须是有限正数")

phases = {"starting": "启动中", "loading_model": "加载模型", "model_loaded": "模型已加载",
          "verifying_source": "校验源数据", "verifying_snr": "校验数据", "inferring": "识别中", "complete": "已完成",
          "failed": "失败", "stopped": "已暂停"}
try:
    plan = json.loads((args.root / "plan.json").read_text())
    if plan.get("schema", "").startswith(("rml2018a-clean12", "rml2018a-collection")):
        while True:
            if sys.stdout.isatty() and not args.once:
                print("\033[2J\033[H", end="", flush=True)
            subprocess.run(["bash", os.environ["SDR_COLLECTION_PROGRESS_HELPER"], str(args.root)], check=True)
            print("Ctrl+C只退出查看，不停止后台识别。", flush=True)
            if args.once or (args.root / "COMPLETE.json").exists():
                break
            time.sleep(args.interval)
        sys.exit(0)
    total = plan["total_rows"]
    if type(total) is not int or total <= 0:
        raise ValueError("计划中的总样本数无效")
    while True:
        state = json.loads((args.root / "state.json").read_text())
        done = state["completed_rows"]
        if type(done) is not int or not 0 <= done <= total:
            raise ValueError("进度中的已完成样本数无效")
        phase = state["phase"]
        if sys.stdout.isatty() and not args.once:
            print("\033[2J\033[H", end="")
        print(f"识别进度  {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"状态：{phases.get(phase, phase)}")
        print(f"GPU 批量：{plan['batch_size']}")
        print(f"已完成并落盘：{done:,} / {total:,} 条")
        if plan.get("window_count", 1) == 4:
            print(f"四窗联合判决（每种输入）：{done // 4:,} / {total // 4:,} 组")
        print(f"尚未完成：{total - done:,} 条")
        print(f"总进度：{done / total:.2%}")
        print(f"完整 SNR 档：{done // 98304} / {len(plan['groups'])}")
        if "source_snr_db" in state:
            print(f"当前源 SNR：{state['source_snr_db']:+d} dB")
        if state.get("error"):
            print(f"错误：{state['error']}")
        print("以主任务登记的落盘进度计数；Ctrl+C 只退出查看。", flush=True)
        if args.once or phase in ("complete", "failed", "stopped"):
            break
        time.sleep(args.interval)
except KeyboardInterrupt:
    print("\n已退出进度查看，未停止后台识别。")
except (OSError, ValueError, KeyError, TypeError) as error:
    print(f"无法读取进度：{error}", file=sys.stderr)
    sys.exit(1)
PY
