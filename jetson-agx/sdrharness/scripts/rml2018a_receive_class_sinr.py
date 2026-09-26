#!/usr/bin/env python3
"""Read-only paired class x raw conditional-SINR decomposition, no model/RF."""
import argparse,csv,hashlib,json
from pathlib import Path
import numpy as np

REPO=Path(__file__).resolve().parents[3]
D10=Path('/var/tmp/sdrharness-dev/rml2018a-d10-common-20260922')
JOIN=Path('/var/tmp/sdrharness-dev/rml2018a-sinr-stratification-20260922/joined-predictions.npz')
EDGES=np.array([-20,-15,-10,-5,0,5,10,15,20])
LABELS=['<-20','[-20,-15)','[-15,-10)','[-10,-5)','[-5,0)','[0,5)','[5,10)','[10,15)','[15,20)','>=20','invalid']


def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def load():
    identities=[]
    for audit,paths in [('RML2018A_D10_COMMON_2026-09-22.json',[D10/'raw-predictions.npz',D10/'guard-predictions.npz']),('RML2018A_SINR_STRATIFICATION_2026-09-22.json',[JOIN])]:
        archive=json.loads((REPO/'docs/evidence'/audit).read_text())
        for path in paths:
            rec=next(r for r in archive['files'] if r['path']==str(path))
            assert digest(path)==rec['sha256'];identities.append(rec)
    with np.load(JOIN,allow_pickle=False) as f:
        members={k:f[k].copy() for k in ('source_row','truth','validation_rank','raw_sinr_db')}
        preds={'CNN2':{p:f['baseline_cnn2_stable-seed42_'+p].copy() for p in ('raw','guard')}}
    preds['D10']={}
    for plane in ('raw','guard'):
        with np.load(D10/(plane+'-predictions.npz'),allow_pickle=False) as f:
            for k in ('source_row','truth','validation_rank'):assert np.array_equal(f[k],members[k])
            pred=f['predicted_class'];assert np.array_equal(pred,f['logits'].argmax(1));preds['D10'][plane]=pred.copy()
    assert len(members['truth'])==369497 and len(np.unique(members['source_row']))==369497
    assert np.array_equal(members['source_row']//106496,members['truth'])
    labelpath=REPO/'jetson-agx/sdrharness/config/amc/rml2018a-labels.server-v1.json'
    identities.append(dict(path=str(labelpath),sha256=digest(labelpath),bytes=labelpath.stat().st_size))
    return members,preds,json.loads(labelpath.read_text())['classes'],identities


def summarize(y,a,b,mask):
    aa=a[mask]==y[mask];bb=b[mask]==y[mask];n=int(mask.sum())
    fixed=int((~aa&bb).sum());lost=int((aa&~bb).sum());raw=int(aa.sum());guard=int(bb.sum())
    assert guard-raw==fixed-lost
    return dict(rows=n,raw_correct=raw,guard_correct=guard,corrected=fixed,regressed=lost,net=guard-raw,
        raw_accuracy=100*raw/n if n else None,guard_accuracy=100*guard/n if n else None,delta_pp=100*(guard-raw)/n if n else None)


def main(root):
    assert root.resolve()==root and root.parent==Path('/var/tmp/sdrharness-dev');root.mkdir(exist_ok=False)
    m,preds,names,identities=load();y=m['truth'];sinr=m['raw_sinr_db'];valid=np.isfinite(sinr)
    bins=np.where(valid,np.searchsorted(EDGES,sinr,side='right'),10);low=valid&(sinr<0)
    save(root/'plan.json',dict(schema='receive-class-sinr-v1',identities=identities,script_sha256=digest(__file__),rows=len(y),models=list(preds),
        bins=LABELS,grouping='same member paired raw-reference conditional estimated receive SINR; invalid separate',low='finite raw conditional SINR <0dB',
        scope='descriptive decomposition of existing inspected validation engineering results; no causal attribution, no threshold fitting',no_rf=True,no_inference=True))
    tables=[];byclass=[];results={};transitions=[]
    for model,p in preds.items():
        a,b=p['raw'],p['guard']
        overall={name:summarize(y,a,b,mask) for name,mask in [('all',np.ones(len(y),bool)),('low',low),('nonnegative',valid&(sinr>=0)),('invalid',~valid)]}
        results[model]=overall
        for cls,name in enumerate(names):
            for bin_id,label in enumerate(LABELS):tables.append(dict(model=model,class_id=cls,class_name=name,sinr_bin=label,**summarize(y,a,b,(y==cls)&(bins==bin_id))))
            for subset,mask in [('all',y==cls),('low',(y==cls)&low)]:
                rec=dict(model=model,class_id=cls,class_name=name,subset=subset,**summarize(y,a,b,mask));byclass.append(rec)
            lost=(y==cls)&low&(a==y)&(b!=y)
            for target,count in enumerate(np.bincount(b[lost],minlength=24)):
                if count:transitions.append(dict(model=model,true_class=name,guard_prediction=names[target],regressions=int(count)))
        for subset in ('all','low'):
            sums=[r for r in byclass if r['model']==model and r['subset']==subset]
            for key in ('rows','raw_correct','guard_correct','corrected','regressed','net'):assert sum(r[key] for r in sums)==overall[subset][key]
        for key in ('rows','raw_correct','guard_correct','corrected','regressed','net'):
            assert sum(r[key] for r in tables if r['model']==model)==overall['all'][key]
    for filename,rows in [('class-sinr.csv',tables),('class-overall-low.csv',byclass),('low-regression-transitions.csv',transitions)]:
        with (root/filename).open('w') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    save(root/'results.json',dict(overall=results,classes=byclass,bins=tables,transitions=transitions))
    for model in preds:
        print(model,results[model]['low'])
        print('low class net:',[(r['class_name'],r['rows'],r['net'],r['regressed']) for r in sorted(byclass,key=lambda x:x['net']) if r['model']==model and r['subset']=='low'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);main(p.parse_args().out)
