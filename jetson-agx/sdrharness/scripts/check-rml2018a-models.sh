#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
result_root=${1:-"$repo_root/local-assets/amc-eval/results/clean12-single-20260914"}
python3 - "$result_root" <<'PY'
import json, sys
from pathlib import Path
r=Path(sys.argv[1])
print('结果目录:',r)
paused=(r/'PAUSED.json').exists() and (r/'STOP').exists()
if paused:
    pause=json.loads((r/'PAUSED.json').read_text())
    print('状态: 已按用户要求暂停；下面显示旧任务保留进度，不会自动续跑。')
    print('后续选择: 仅 seed42 的 8 个模型；其他 Mamba seeds 不再安排。')
if (r/'plan.json').exists():
    plan=json.loads((r/'plan.json').read_text())
    print('计数规则: 原始数据全量；RX 仅 usable 且 strict_quality_pass；单窗1024点')
    for d in plan['datasets']:
        print(f"  {d['plane']:6} 待识别 {d['selected_rows']:,} / {plan['rows_per_dataset']:,}；跳过 {d['skipped_rows']:,}")
    print(f"共同通过校验的源行: {plan['datasets'][0]['common_rows']:,}")
if (r/'progress.json').exists():
    p=json.loads((r/'progress.json').read_text())
    print('阶段: 已暂停' if paused else '阶段: '+str(p.get('stage')))
    if 'total_predictions' in p:
        n=p['completed_predictions']; total=p['total_predictions']
        print(f'总进度: {n:,} / {total:,} ({n/total:.2%})')
        if 'committed_predictions' in p:
            print(f"已落盘: {p['committed_predictions']:,}；本块已计算但尚未落盘: {n-p['committed_predictions']:,}")
        if 'model' in p:
            print('暂停位置:' if paused else '正在识别:',p['model'],p['dataset'],f"{p['dataset_rows']:,} 条")
    if p.get('stage')=='plotting':
        print(f"混淆矩阵: {p['matrices_complete']} / {p['matrices_total']}")
reports=sorted(r.glob('*-seed*/*-summary.json'))
done=[]
for f in reports:
    s=json.loads(f.read_text())
    if s['complete']:done.append(s)
print(f'已完成模型×数据集: {len(done)} / 36')
for s in done:
    print(f"  {s['model']:32} {s['dataset']:6} ACC {s['accuracy']:.2%}  {s['rows']:,} 条；跳过 {s['skipped_rows']:,}；共同子集 ACC {s['common_accuracy']:.2%}")
if (r/'COMPLETE.json').exists():
    print('全部完成，已通过结果读回核验。')
    print('混淆矩阵:',r/'confusion-matrices')
elif paused:print('退出原因: 用户暂停信号；systemd的非零退出码来自这次人工停止。')
elif (r/'ERROR.json').exists():print('错误记录（若已续跑请结合服务状态）:',(r/'ERROR.json').read_text())
PY
systemctl --user show sdr-rml2018a-clean12-eval-20260914.service \
  -p ActiveState -p SubState -p ExecMainStatus
