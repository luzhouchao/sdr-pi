#!/usr/bin/env python3
"""Independent SINR counts and descriptive D10/guard-metric association."""
import csv,json,hashlib,os
from pathlib import Path
import numpy as np
ROOT=Path('/var/tmp/sdrharness-dev/rml2018a-d10-partial-20260926')
REPO=Path(__file__).resolve().parents[3]

def main():
    report=json.loads((ROOT/'results.json').read_text())
    with np.load(ROOT/'predictions.npz') as f:p={k:f[k] for k in f.files}
    sinr=json.loads((ROOT/'sinr.json').read_text());x=np.array(sinr['raw_conditional_sinr_db']);y=p['truth']
    names=['raw','alpha25','alpha50','alpha75','guard'];good={k:p[k+'_logits'].argmax(1)==y for k in names}
    assert np.array_equal(sinr['source_row'],p['source_row'])
    edges=[-np.inf,-20,-15,-10,-5,0,5,10,15,20,np.inf]
    masks={'overall':np.ones(len(y),bool),'raw_sinr_below0':np.isfinite(x)&(x<0)}
    masks.update({label:(np.isfinite(x)&(x>=edges[i])&(x<edges[i+1]) if i<10 else ~np.isfinite(x)) for i,label in enumerate(sinr['labels'])})
    table=[]
    for label,m in masks.items():
        assert report[label]['rows']==int(m.sum())
        for name in names:
            assert np.isfinite(p[name+'_logits']).all()
            c=int(good[name][m].sum());assert c==report[label]['correct'][name]
            pair=report[label]['versus_raw'][name]
            assert pair['corrected']==int((~good['raw']&good[name]&m).sum()) and pair['regressed']==int((good['raw']&~good[name]&m).sum())
            table.append(dict(raw_reference_sinr_bin=label,variant=name,rows=int(m.sum()),correct=c,accuracy=100*c/m.sum() if m.any() else None))
    with (ROOT/'sinr-table.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=list(table[0]));w.writeheader();w.writerows(table)
    audit=json.loads((REPO/'docs/evidence/RML2018A_LOW_SNR_ASSOCIATION_2026-09-17.json').read_text())
    rec=next(r for r in audit['files'] if Path(r['path']).name=='rows.csv');assert hashlib.sha256(Path(rec['path']).read_bytes()).hexdigest()==rec['sha256']
    with open(rec['path']) as f:rows={int(r['source_row']):r for r in csv.DictReader(f)}
    joined=[rows[int(i)] for i in p['source_row']]
    assert all(int(r['truth'])==int(t) and int(r['validation_rank'])==int(v) for r,t,v in zip(joined,y,p['validation_rank']))
    assert np.allclose(x,[float(r['raw_conditional_sinr_db']) for r in joined],atol=2e-4,rtol=2e-4)
    metrics=['phase_curvature_abs_rad','guard_error_margin','guard_holdout_over_tone_power']
    bins=np.searchsorted(np.array(edges[1:-1]),x,side='right');low=masks['raw_sinr_below0']
    reg=good['raw']&~good['guard']&low;stable=good['raw']&good['guard']&low
    association=dict(parent=rec,scope='D10 raw SINR<0; descriptive, same-class/same-raw-SINR-bin comparisons; correlated capture context, no significance claims',regressed=int(reg.sum()),stable_correct=int(stable.sum()),metrics={})
    for key in metrics:
        values=np.array([float(r[key]) for r in joined]);scores=[];nr=ns=pairs=0
        for c in range(24):
            for b in range(5):
                a=values[reg&(y==c)&(bins==b)];z=values[stable&(y==c)&(bins==b)]
                if len(a) and len(z):scores.append(float(((a[:,None]>z)+.5*(a[:,None]==z)).mean()));nr+=len(a);ns+=len(z);pairs+=len(a)*len(z)
        association['metrics'][key]=dict(regressed_median=float(np.median(values[reg])),stable_median=float(np.median(values[stable])),matched_cells=len(scores),matched_regressed=nr,matched_stable=ns,pairs=pairs,equal_cell_fraction_regressed_larger=float(np.mean(scores)) if scores else None)
    (ROOT/'guard-association.json').write_text(json.dumps(association,indent=2)+'\n')
    (ROOT/'independent-verification.json').write_text(json.dumps(dict(passed=True,rows=len(y),groups=len(masks),variants=len(names),guard_metric_rows=len(joined)),indent=2)+'\n')
    os.environ['MPLCONFIGDIR']=str(ROOT/'cache/matplotlib')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(13,5))
    for name in names:
        vals=[next(r['accuracy'] for r in table if r['variant']==name and r['raw_reference_sinr_bin']==lab) for lab in sinr['labels'][:8]]
        axes[0].plot(np.arange(-22.5,15,5),vals,marker='.',label=name)
    axes[0].set(xlabel='Raw-reference conditional estimated SINR bin center (dB)',ylabel='Accuracy (%)',title='Same 2,496 diagnostic members');axes[0].legend();axes[0].grid(alpha=.2)
    for label in ['overall','raw_sinr_below0']:
        axes[1].plot([0,.25,.5,.75,1],[100*report[label]['correct'][n]/report[label]['rows'] for n in names],marker='o',label=label)
    axes[1].set(xlabel='Cancellation strength alpha',ylabel='Accuracy (%)',title='Each candidate independently RMS-normalized');axes[1].legend();axes[1].grid(alpha=.2)
    fig.suptitle('D10 partial cancellation: diagnostic comparison, not an adopted adaptive rule');fig.tight_layout();fig.savefig(ROOT/'partial-cancellation.png',dpi=160);plt.close(fig)
    print(json.dumps({k:report[k] for k in ['overall','raw_sinr_below0']}));print(json.dumps(association))

if __name__=='__main__':main()
