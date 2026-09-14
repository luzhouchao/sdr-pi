#!/usr/bin/env python3
"""Draw stored engineering confusion matrices with the system plotting runtime."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import numpy as np


def require(ok, reason):
    if not ok: raise ValueError(reason)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic(path, value):
    path=Path(path);tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n');tmp.replace(path)


def cache_root(root):
    token=hashlib.sha256(str(root).encode()).hexdigest()[:16]
    return Path('/var/tmp/sdrharness-dev')/f'rml2018a-collection-cache-{token}'


def render(root, plan):
    """Publication-exportable row-normalized confusion matrices; no inference."""
    cache = cache_root(root)/"matplotlib"
    cache.mkdir(parents=True,exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(cache)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    exported = []
    for spec in plan["models"]:
        name = f"{spec['variant']}-seed{spec['seed']}"
        for ds in plan["datasets"]:
            plane = ds["plane"]
            s = json.loads((root/name/f"{plane}-summary.json").read_text())
            require(s["complete"], "cannot render incomplete summary")
            counts = np.asarray(s["confusion_by_snr"],np.int64).sum(0)
            common = np.asarray(s["common_confusion_by_snr"],np.int64).sum(0)
            totals = counts.sum(1,keepdims=True)
            pct = np.divide(counts*100.0,totals,out=np.zeros((24,24)),where=totals!=0)
            folder = root/"confusion-matrices"/name
            folder.mkdir(parents=True,exist_ok=True)
            for suffix, table in (("counts",counts),("percent",pct),("common-counts",common)):
                with (folder/f"{plane}-{suffix}.csv").open("w",newline="") as f:
                    w=csv.writer(f);w.writerow(["true/predicted",*plan["classes"]])
                    w.writerows([label,*row] for label,row in zip(plan["classes"],table.tolist()))
            fig, ax = plt.subplots(figsize=(12,10),layout="constrained")
            im = ax.imshow(pct,vmin=0,vmax=100,cmap="Blues",interpolation="nearest")
            ax.set_xticks(range(24),plan["classes"],rotation=60,ha="right",fontsize=8)
            ax.set_yticks(range(24),plan["classes"],fontsize=8)
            ax.set_xlabel("Predicted modulation");ax.set_ylabel("True source modulation")
            ax.set_title(f"{spec['display_name']} seed {spec['seed']} | {plane}\n"
                         f"{'Server seed42 validation' if 'split' in plan else 'Single 1024-point window'} | ACC {s['accuracy']:.2%} | N={s['rows']:,} | skipped={s['skipped_rows']:,}",fontsize=11)
            for i in range(24):
                for j in range(24):
                    if pct[i,j]>=1 or i==j:
                        ax.text(j,i,f"{pct[i,j]:.1f}",ha="center",va="center",fontsize=6,
                                color="white" if pct[i,j]>50 else "black")
            fig.colorbar(im,ax=ax,label="Within each true class (%)",shrink=.8)
            for ext in ("png","svg"):
                p=folder/f"{plane}.{ext}"
                fig.savefig(p,dpi=180)
                exported.append(dict(path=str(p),bytes=p.stat().st_size,sha256=digest(p)))
            plt.close(fig)
            atomic(root/"progress.json",dict(stage="plotting",matrices_complete=len(exported)//2,matrices_total=len(plan["models"])*len(plan["datasets"]),
                                             total_predictions=plan["total_predictions"],completed_predictions=plan["total_predictions"]))
    atomic(root/"plots.json",dict(matrices=len(plan["models"])*len(plan["datasets"]),formats=["png","svg","counts.csv","percent.csv","common-counts.csv"],files=exported))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args();root=args.root.resolve()
    plan=json.loads((root/'plan.json').read_text())
    try:
        render(root,plan)
    finally:
        cache=cache_root(root)/'matplotlib'
        if cache.exists():shutil.rmtree(cache)
