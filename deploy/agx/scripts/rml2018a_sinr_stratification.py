#!/usr/bin/env python3
"""Read-only SINR rebinning of existing common-validation model predictions."""
import csv
import json
from pathlib import Path
import signal
import time
import resource
import shutil
import numpy as np
import rml2018a_model_collection_eval as ev

ROOT=Path('/var/tmp/sdrharness-dev/rml2018a-sinr-stratification-20260922')
PARENT=ev.ASSET/'results/seed42-val-fresh-20260914'
D10=Path('/var/tmp/sdrharness-dev/rml2018a-d10-replay-20260922')
BASE=Path('/var/tmp/sdrharness-dev/rml2018a-offline-baseline-20260916')
EDGES=np.array([-20,-15,-10,-5,0,5,10,15,20],float)
LABELS=['<-20','[-20,-15)','[-15,-10)','[-10,-5)','[-5,0)','[0,5)','[5,10)','[10,15)','[15,20)','>=20','invalid']


def bins(x):
    return np.where(np.isfinite(x),np.searchsorted(EDGES,x,side='right'),10)


def summarize(y,a,b,mask):
    n=int(mask.sum());ac=a==y;bc=b==y;ca=int((ac&mask).sum());cb=int((bc&mask).sum())
    return dict(rows=n,raw_correct=ca,guard_correct=cb,raw_acc_percent=100*ca/n if n else None,guard_acc_percent=100*cb/n if n else None,
                change_pp=100*(cb-ca)/n if n else None,corrected=int((~ac&bc&mask).sum()),regressed=int((ac&~bc&mask).sum()))


def main():
    ROOT.mkdir(exist_ok=False);start=time.monotonic()
    signal.signal(signal.SIGALRM,lambda *_: (_ for _ in ()).throw(TimeoutError('600 seconds')));signal.alarm(600)
    seal=json.loads((PARENT/'retention.json').read_text());records={r['path']:r for r in seal['files']}
    source_plan=json.loads((PARENT/'plan.json').read_text())
    planned=[r for r in seal['files'] if Path(r['path']).suffix=='.npz' and (Path(r['path']).parent.name in ('raw','guard') or Path(r['path']).name in ('raw-metadata.npz','guard-metadata.npz'))]
    ev.require(ev.digest(PARENT/'plan.json')==seal['plan_sha256'],'parent plan SHA')
    for rec in json.loads((ev.REPO/'docs/evidence/RML2018A_D10_REPLAY_2026-09-22.json').read_text())['files']:ev.identity(rec['path'],rec['sha256'])
    baseline_seal=json.loads((BASE/'retention.json').read_text());baseline_rec=next(r for r in baseline_seal['files'] if Path(r['path']).name=='baseline-rows.json');ev.identity(baseline_rec['path'],baseline_rec['sha256'])
    plan=dict(schema='sinr-rebin-v1',script=ev.identity(__file__),parent_plan=ev.identity(PARENT/'plan.json'),parent_retention=ev.identity(PARENT/'retention.json'),prediction_inputs=planned,d10=ev.identity(D10/'predictions.npz'),baseline_rms_sinr=baseline_rec,
        bin_edges_db=EDGES.tolist(),labels=LABELS,primary='same-member raw-reference conditional estimated SINR; left-closed right-open bins',secondary='each plane uses own conditional SINR on same common population; not paired difference by bin',
        populations=['8 models common369497 validation rows','9 models shared2496 diagnostic validation rows'],invalid='nonfinite SINR retained in explicit invalid bin',budget=dict(seconds=600,host_bytes=1024**3,output_bytes=128*1024**2,free_bytes=shutil.disk_usage(ROOT).free),new_inference=False,rf=False)
    ev.atomic(ROOT/'plan.json',plan)
    metadata={}
    for plane in ('raw','guard'):
        path=PARENT/(plane+'-metadata.npz');ev.identity(path,records[str(path)]['sha256'])
        with np.load(path,allow_pickle=False) as f:
            metadata[plane]={k:f[k] for k in ('source_row','class_id','source_snr_db','raw_sinr_db','guard_sinr_db','common_source_subset','selected_for_inference','validation_rank')}
    rm=metadata['raw'];idx=np.flatnonzero(rm['common_source_subset']);idx=idx[np.argsort(rm['source_row'][idx])]
    ids=rm['source_row'][idx];truth=rm['class_id'][idx];raw_sinr=rm['raw_sinr_db'][idx];guard_sinr=rm['guard_sinr_db'][idx]
    ev.require(len(ids)==369497 and len(np.unique(ids))==len(ids),'common population')
    for plane,m in metadata.items():
        ix=np.flatnonzero(m['common_source_subset']);ix=ix[np.argsort(m['source_row'][ix])]
        ev.require(np.array_equal(m['source_row'][ix],ids) and np.array_equal(m['class_id'][ix],truth),'common identities')
        ev.require(m['selected_for_inference'][ix].all(),'common subset selected')
        for k,target in [('raw_sinr_db',raw_sinr),('guard_sinr_db',guard_sinr)]:ev.require(np.array_equal(m[k][ix],target,equal_nan=True),'SINR plane consistency')
    with np.load(D10/'predictions.npz',allow_pickle=False) as f:d10={k:f[k] for k in f.files}
    sub=np.searchsorted(ids,d10['source_row']);ev.require(np.array_equal(ids[sub],d10['source_row']) and np.array_equal(truth[sub],d10['truth']),'D10 membership')
    baseline={r['source_row']:r for r in json.loads((BASE/'baseline-rows.json').read_text())}
    sinr_check={}
    for plane,current in [('raw',raw_sinr[sub]),('guard',guard_sinr[sub])]:
        values=np.array([baseline[int(i)]['planes'][plane]['conditional_effective_sinr_db'] for i in ids[sub]])
        ev.require(np.allclose(values,current,atol=2e-4,rtol=2e-4,equal_nan=True),'D10 SINR lineage')
        ev.require(np.array_equal(bins(values),bins(current)),'D10 SINR bins stable')
        sinr_check[plane]=float(np.max(abs(values-current)))
    predictions={};models={}
    for spec in source_plan['models']:
        name=spec['variant']+'-seed42';models[name]=spec['display_name'];predictions[name]={}
        for plane,m in metadata.items():
            out=np.full(len(ids),-1,np.int16)
            for path in sorted((PARENT/name/plane).glob('*.npz')):
                ev.identity(path,records[str(path)]['sha256'])
                with np.load(path,allow_pickle=False) as f:
                    rows=f['dataset_row'];source=m['source_row'][rows];pred=f['predicted_class'];logits=f['logits']
                    ev.require(np.array_equal(pred,logits.argmax(1)) and np.isfinite(logits).all(),'stored predictions')
                    use=m['common_source_subset'][rows];at=np.searchsorted(ids,source[use]);ev.require(np.array_equal(ids[at],source[use]) and (out[at]<0).all(),'unique prediction join')
                    out[at]=pred[use]
            ev.require((out>=0).all() and (out<24).all(),'complete predictions');predictions[name][plane]=out
        print('joined',name,flush=True)
    old_summary=json.loads(Path('/var/tmp/sdrharness-dev/rml2018a-lo-effect-20260915/paired-normalization.json').read_text())
    for m in old_summary['models']:
        for plane in ('raw','guard'):ev.require(int((predictions[m['model']][plane][sub]==truth[sub]).sum())==m[plane+'_correct'],'historical2496 counts')
    masks=[(label,bins(raw_sinr)==i) for i,label in enumerate(LABELS)]
    report=[];own=[]
    saved=dict(source_row=ids,truth=truth,validation_rank=rm['validation_rank'][idx],source_snr_db=rm['source_snr_db'][idx],raw_sinr_db=raw_sinr,guard_sinr_db=guard_sinr,subset_indices=sub)
    for population,take in [('common369497',np.arange(len(ids))),('shared2496',sub)]:
        usemodels=dict(models)
        if population=='shared2496':usemodels['amc_mamba_d10-seed42']='D10'
        for name,display in usemodels.items():
            a=predictions[name]['raw'][take] if name in predictions else d10['raw_logits'].argmax(1)
            b=predictions[name]['guard'][take] if name in predictions else d10['guard_logits'].argmax(1)
            for i,label in enumerate(LABELS):
                report.append(dict(population=population,model=name,display=display,raw_reference_sinr_bin=label,**summarize(truth[take],a,b,bins(raw_sinr[take])==i)))
                for plane,pred,sinr in [('raw',a,raw_sinr[take]),('guard',b,guard_sinr[take])]:
                    mask=bins(sinr)==i;n=int(mask.sum());correct=int(((pred==truth[take])&mask).sum())
                    own.append(dict(population=population,model=name,plane=plane,sinr_bin=label,rows=n,correct=correct,accuracy=100*correct/n if n else None))
            if name in predictions and population=='common369497':
                for plane in ('raw','guard'):saved[name+'_'+plane]=predictions[name][plane]
    saved['d10_raw']=d10['raw_logits'].argmax(1);saved['d10_guard']=d10['guard_logits'].argmax(1)
    np.savez_compressed(ROOT/'joined-predictions.npz',**saved)
    for name,data in [('paired-bins.csv',report),('own-sinr-bins.csv',own)]:
        with (ROOT/name).open('w') as f:w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    summary=dict(populations={'common369497':len(ids),'shared2496':len(sub)},models=models,d10_sinr_float_error=sinr_check,bin_counts={p:np.bincount(bins(x),minlength=11).tolist() for p,x in [('raw',raw_sinr),('guard',guard_sinr)]},paired=report,own=own,seconds=time.monotonic()-start,rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    ev.require(summary['rss_bytes']<1024**3,'RSS budget');ev.atomic(ROOT/'results.json',summary)
    ev.require(sum(p.stat().st_size for p in ROOT.iterdir() if p.is_file())<128*1024**2,'output budget');signal.alarm(0)
    print(json.dumps({k:summary[k] for k in ['populations','bin_counts','seconds','rss_bytes']}),flush=True)

if __name__=='__main__':main()
