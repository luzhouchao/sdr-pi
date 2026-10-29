#!/usr/bin/env python3
"""Fixed alpha25 evaluation on remaining members, with prior subset separated."""
import csv,json,hashlib,os
from pathlib import Path
import numpy as np
ROOT=Path('/var/tmp/sdrharness-dev/rml2018a-d10-alpha25-common-20260926')
BASE=Path('/var/tmp/sdrharness-dev/rml2018a-d10-common-20260922')
REPO=Path(__file__).resolve().parents[3]
EDGES=np.array([-20,-15,-10,-5,0,5,10,15,20])
LABELS=['<-20','[-20,-15)','[-15,-10)','[-10,-5)','[-5,0)','[0,5)','[5,10)','[10,15)','[15,20)','>=20','invalid']

def main():
    assert (ROOT/'complete.json').exists()
    with np.load(ROOT/'members.npz') as f:members={k:f[k] for k in f.files}
    ids=members['source_row'];truth=members['truth'];sinr=members['raw_sinr_db'];n=len(ids)
    seal=json.loads((REPO/'docs/evidence/RML2018A_D10_COMMON_2026-09-22.json').read_text())
    sources=[];pred={}
    for name in ('raw','alpha25','guard'):
        path=(ROOT if name=='alpha25' else BASE)/(name+'-predictions.npz')
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        if name!='alpha25':assert sha==next(r['sha256'] for r in seal['files'] if r['path']==str(path))
        sources.append(dict(path=str(path),sha256=sha))
        with np.load(path) as f:
            for k,target in [('source_row',ids),('truth',truth),('validation_rank',members['validation_rank'])]:assert np.array_equal(f[k],target)
            assert np.isfinite(f['logits']).all() and np.array_equal(f['logits'].argmax(1),f['predicted_class']);pred[name]=f['predicted_class']
    sub=np.zeros(n,bool);sub[members['subset_indices']]=True
    assert sub.sum()==2496 and (~sub).sum()==367001
    populations={'remaining367001':~sub,'prior2496':sub,'all369497':np.ones(n,bool)}
    bins=np.where(np.isfinite(sinr),np.searchsorted(EDGES,sinr,side='right'),10)
    good={k:v==truth for k,v in pred.items()}
    rows=[]
    for pop,selected in populations.items():
        masks={'overall':selected,'raw_sinr_below0':selected&np.isfinite(sinr)&(sinr<0)}
        masks.update({label:selected&(bins==i) for i,label in enumerate(LABELS)})
        for label,m in masks.items():
            count=int(m.sum());r=dict(population=pop,raw_reference_sinr_bin=label,rows=count)
            for name,g in good.items():
                c=int(g[m].sum());r[name+'_correct']=c;r[name+'_accuracy']=100*c/count if count else None
            for ref in ('raw','guard'):
                a=good['alpha25'][m];b=good[ref][m]
                r['alpha25_vs_'+ref+'_corrected']=int((a&~b).sum());r['alpha25_vs_'+ref+'_regressed']=int((~a&b).sum())
                r['alpha25_vs_'+ref+'_change_pp']=100*(int(a.sum())-int(b.sum()))/count if count else None
            rows.append(r)
    # Independent interval/count path rather than digitize/searchsorted.
    boundaries=[-np.inf,*EDGES.tolist(),np.inf]
    for r in rows:
        m=populations[r['population']].copy();label=r['raw_reference_sinr_bin']
        if label=='raw_sinr_below0':m&=np.isfinite(sinr)&(sinr<0)
        elif label=='invalid':m&=~np.isfinite(sinr)
        elif label!='overall':
            i=LABELS.index(label);m&=np.isfinite(sinr)&(sinr>=boundaries[i])&(sinr<boundaries[i+1])
        assert r['rows']==int(m.sum())
        for name in good:assert r[name+'_correct']==int(np.count_nonzero(pred[name][m]==truth[m]))
        for ref in ('raw','guard'):
            delta=good['alpha25'][m].astype(int)-good[ref][m].astype(int)
            assert r['alpha25_vs_'+ref+'_corrected']==int((delta==1).sum()) and r['alpha25_vs_'+ref+'_regressed']==int((delta==-1).sum())
    result=dict(alpha=.25,primary_population='remaining367001',independent_locked_test=False,sources=sources,rows=rows,conditional_estimated_sinr=True,production_changes=False)
    (ROOT/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    with (ROOT/'sinr-table.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    (ROOT/'independent-verification.json').write_text(json.dumps(dict(passed=True,rows=n,groups=len(rows),methods='exact source/rank/truth joins, SHA-pinned baselines, logits argmax, independent interval masks and signed paired correctness differences',no_member_overlap_between_remaining_and_prior=True),indent=2)+'\n')
    os.environ['MPLCONFIGDIR']=str(ROOT/'cache/matplotlib')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(13,5))
    q=[r for r in rows if r['population']=='remaining367001' and r['raw_reference_sinr_bin'] in LABELS[:8]]
    centers=np.arange(-22.5,15,5)
    for name,label in [('raw','No cancellation'),('alpha25','25% cancellation'),('guard','Full cancellation')]:
        axes[0].plot(centers,[r[name+'_accuracy'] for r in q],marker='.',label=label)
    axes[0].set(xlabel='Raw-reference SINR bin center (dB)',ylabel='Accuracy (%)',title='Remaining 367,001 validation members');axes[0].legend();axes[0].grid(alpha=.2)
    for ref,label in [('raw','25% minus none'),('guard','25% minus full')]:axes[1].plot(centers,[r['alpha25_vs_'+ref+'_change_pp'] for r in q],marker='.',label=label)
    axes[1].axhline(0,color='gray',lw=1);axes[1].set(xlabel='Raw-reference SINR bin center (dB)',ylabel='Paired accuracy change (percentage points)',title='Same members within each bin');axes[1].legend();axes[1].grid(alpha=.2)
    fig.suptitle('D10 fixed 25% cancellation; conditional estimated receive SINR\nPrior 2,496 diagnostic members excluded; lower open bin displayed at -22.5 dB')
    fig.tight_layout();fig.savefig(ROOT/'remaining-comparison.png',dpi=160);plt.close(fig)
    print(json.dumps([r for r in rows if r['population']=='remaining367001' and r['raw_reference_sinr_bin'] in ['overall','raw_sinr_below0','[5,10)']]))

if __name__=='__main__':main()
