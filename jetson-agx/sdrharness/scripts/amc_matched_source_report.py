#!/usr/bin/env python3
"""Read back matched baseline and compare four views on identical validation rows."""
import argparse
import csv
import hashlib
import json
import time
from pathlib import Path
import numpy as np


def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
    return h.hexdigest()


def read(p):return json.loads(Path(p).read_text())


def write(p,data):p.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')


def load(p):
    assert sha(p)==read(p.with_suffix('.json'))['sha256'],p
    with np.load(p,allow_pickle=False) as f:return {k:f[k] for k in f.files}


def csv_write(p,rows):
    with p.open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def run(root,sinr_root,wait=False):
    import h5py
    import amc_validation_eval as e
    from amc_matched_source_baseline import transform
    started=time.monotonic()
    def ready(path):
        while not path.exists():
            assert wait and time.monotonic()-started<48*3600,('missing result',str(path))
            assert read(root/'progress.json')['status']!='failed','inference failed'
            time.sleep(10)
    plan=read(root/'plan.json')
    if not wait:assert read(root/'complete.json')['status']=='complete'
    parent=Path(plan['parent']);assert sha(parent/'complete.json')==plan['parent_complete_sha256']
    assert sha(Path(plan['control'])/'complete.json')==plan['control_complete_sha256']
    summaries=[];strata=[];class_rows=[];checks=[];totals=dict(coverage=0,new_payload=0,numerical=0,reused_original=0,reused_control=0)
    for d in plan['datasets']:
        ds=d['dataset'];n=d['rows'];c=len(d['class_names'])
        with h5py.File(d['vds']) as f:meta={k:f[k][:] for k in ('source_row','validation_rank','class_id','source_snr_db')}
        with np.load(sinr_root/ds/'sinr.npz') as f:
            bins=f['reference_bin'];sinr=f['raw_sinr_db']
            for k in ('source_row','validation_rank','class_id'):assert np.array_equal(meta[k],f[k])
        expected=np.searchsorted([-10,-5,0,5,10,15,20],sinr,side='right');expected[~np.isfinite(sinr)]=8
        assert np.array_equal(expected,bins)
        ready(root/ds/'amplitude-audit.json')
        audit=read(root/ds/'amplitude-audit.json');assert audit['rows']==n and audit['tx_same_bytes_after_row_rescaling']
        input_hashes={};identical=np.zeros(n,bool);peaks=np.empty(n);oh=hashlib.sha256();mh=hashlib.sha256()
        for start in range(0,n,2048):
            end=min(start+2048,n);s=slice(start,end)
            x=e.source_values(d,meta['source_row'][s],meta['class_id'][s],meta['source_snr_db'][s]);y=transform(x,ds)
            peaks[s]=np.abs(x[:,0].astype(float)+1j*x[:,1].astype(float)).max(1)
            oh.update(x.tobytes());mh.update(y.tobytes());input_hashes[start]=hashlib.sha256(y.tobytes()).hexdigest();identical[s]=np.all(x==y,axis=(1,2))
        assert oh.hexdigest()==audit['original_input_sha256'] and mh.hexdigest()==audit['matched_input_sha256']
        assert identical.sum()==audit['identical_original_rows']
        del x,y
        capture=Path(plan['source_campaign'])/ds;seal=read(capture/'dataset-complete.json');offset=0
        assert sha(capture/'dataset-complete.json')==d['seal_sha256']
        for receipt in seal['batch_receipts']:
            batch=capture/f"batch-{receipt['batch']:05d}"
            assert sha(batch/'batch-complete.json')==receipt['sha256']
            expected_plan=next(f['sha256'] for f in read(batch/'batch-complete.json')['files'] if f['path']=='plan.json')
            assert sha(batch/'plan.json')==expected_plan
            bp=read(batch/'plan.json');members=bp['source']['contract']['source_rows'];count=len(members)
            assert np.array_equal(members,meta['source_row'][offset:offset+count])
            assert np.allclose(bp['transport']['row_scales'],.2*np.sqrt(10)/peaks[offset:offset+count],atol=0,rtol=1e-12)
            offset+=count
        assert offset==n
        for spec in [m for m in plan['models'] if m['dataset']==ds]:
            model=spec['variant'];out=root/ds/model;ready(out/'result.json');r=read(out/'result.json')
            assert r['plan_sha256']==sha(root/'plan.json') and r['strict_load'] and r['rows']==n
            for path,digest in spec['files'].items():assert sha(path)==digest
            preds={p:np.empty(n,np.int64) for p in ('source','matched','raw','guard')};reuse=np.empty(n,np.int8)
            control=None
            if ds=='rml2018a' and model in ('amc_mamba_d10','baseline_mcformer'):
                cp=Path(plan['control'])/model/'predictions.npz';assert sha(cp)==read(cp.parent/'result.json')['predictions_sha256']
                with np.load(cp) as f:control={k:f[k] for k in ('validation_rank','rms_logits')}
                control_index={int(v):i for i,v in enumerate(control['validation_rank'])}
            for start in range(0,n,2048):
                end=min(start+2048,n);s=slice(start,end);name=f'rows-{start:07d}.npz'
                matched=load(out/name);source=load(parent/ds/model/'source'/name);rx=load(parent/ds/model/name)
                for a in (matched,source,rx):
                    for k in ('source_row','validation_rank','class_id'):assert np.array_equal(a[k],meta[k][s])
                assert str(matched['input_sha256'])==input_hashes[start]
                for p,a in (('source',source),('matched',matched),('raw',rx),('guard',rx)):
                    logits=a[p+'_logits'];pred=a[p+'_prediction']
                    assert logits.shape==(end-start,c) and np.isfinite(logits).all() and np.array_equal(pred,logits.argmax(1))
                    preds[p][s]=pred
                rr=matched['reuse_origin'];reuse[s]=rr;assert np.isin(rr,[0,1,2]).all()
                assert np.array_equal(rr==1,identical[s])
                assert np.array_equal(matched['matched_logits'][rr==1],source['source_logits'][rr==1])
                if control is not None:
                    ii=np.array([j for j in range(end-start) if start+j in control_index],dtype=int)
                    assert np.array_equal(np.flatnonzero(rr==2),ii)
                    assert np.array_equal(matched['matched_logits'][ii],control['rms_logits'][[control_index[start+j] for j in ii]])
                else:assert not (rr==2).any()
            truth=meta['class_id'];correct={p:preds[p]==truth for p in preds};matrix=np.zeros((c,c),np.int64);np.add.at(matrix,(truth,preds['matched']),1)
            assert np.array_equal(matrix,r['confusion']) and int(matrix.trace())==r['correct']
            for p in ('source','raw','guard'):assert int(correct[p].sum())==r['original'][p]['correct']
            assert (reuse==0).sum()==r['new_payload_forward_rows'] and (reuse==1).sum()==r['reused_original_rows'] and (reuse==2).sum()==r['reused_control_rows']
            row=dict(dataset=ds,model=model,rows=n,**{p:float(correct[p].mean()*100) for p in preds})
            row.update(source_matched_changed_rows=int((preds['source']!=preds['matched']).sum()),matched_guard_changed_rows=int((preds['matched']!=preds['guard']).sum()),source_to_matched_pp=row['matched']-row['source'],matched_to_guard_pp=row['guard']-row['matched'],raw_to_guard_pp=row['guard']-row['raw']);summaries.append(row)
            for cls in [-1,*range(c)]:
                for bin_id in [-1,*range(9)]:
                    mask=np.ones(n,bool)
                    if cls>=0:mask&=truth==cls
                    if bin_id>=0:mask&=bins==bin_id
                    count=int(mask.sum())
                    v=dict(dataset=ds,model=model,class_id=cls,reference_bin=bin_id,rows=count,**{p+'_correct':int(correct[p][mask].sum()) for p in preds},raw_to_guard_fixed=int((~correct['raw']&correct['guard']&mask).sum()),raw_to_guard_regressed=int((correct['raw']&~correct['guard']&mask).sum()),matched_guard_prediction_agreement=int(((preds['matched']==preds['guard'])&mask).sum()))
                    strata.append(v)
                    if cls>=0 and bin_id==-1:class_rows.append(v)
            totals['coverage']+=n;totals['new_payload']+=r['new_payload_forward_rows'];totals['numerical']+=r['numerical_forward_rows'];totals['reused_original']+=r['reused_original_rows'];totals['reused_control']+=r['reused_control_rows']
            checks.append(dict(dataset=ds,model=model,rows=n,result_sha256=sha(out/'result.json')))
            print(ds,model,'verified',flush=True)
    ready(root/'complete.json');assert read(root/'complete.json')['status']=='complete'
    assert totals['coverage']==713385*8 and len(checks)==32
    assert totals['new_payload']+totals['reused_original']+totals['reused_control']==totals['coverage']
    csv_write(root/'summary.csv',summaries);csv_write(root/'strata.csv',strata);csv_write(root/'classes.csv',class_rows)
    write(root/'verification.json',dict(status='passed',totals=totals,models=checks,plan_sha256=sha(root/'plan.json'),sinr_parent=str(sinr_root),sinr_files={str(sinr_root/d['dataset']/'sinr.npz'):sha(sinr_root/d['dataset']/'sinr.npz') for d in plan['datasets']},checks=['all prediction shard SHA, identities, finite logits and argmax','all model artifact hashes','517 sealed batch plans and 713385 TX row scales','all transformed input hashes and original/normalized byte identity','reused source/control logits exact equality','summary/confusion counts','same raw-reference SINR memberships including invalid']))


def plot(root):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    rows=list(csv.DictReader((root/'summary.csv').open()));fig,axs=plt.subplots(2,2,figsize=(17,10),constrained_layout=True)
    for ax,ds in zip(axs.flat,dict.fromkeys(r['dataset'] for r in rows)):
        rr=[r for r in rows if r['dataset']==ds];xx=np.arange(len(rr));width=.2
        for j,p in enumerate(('source','matched','raw','guard')):ax.bar(xx+(j-1.5)*width,[float(r[p]) for r in rr],width,label=p)
        ax.set_title(ds);ax.set_xticks(xx,[r['model'].replace('baseline_','').replace('amc_mamba_d10','D10') for r in rr],rotation=30);ax.set_ylim(0,100);ax.set_ylabel('Accuracy (%)');ax.grid(axis='y',alpha=.2)
    axs[0,0].legend(ncol=4);fig.suptitle('Same seed42 validation members: original / amplitude-matched source / received raw / guard')
    for ext in ('png','svg'):fig.savefig(root/f'four-view-summary.{ext}',dpi=160)
    plt.close(fig)
    def curves(ax,rr):
        for p in ('source','matched','raw','guard'):
            values=[100*int(r[p+'_correct'])/int(r['rows']) if int(r['rows']) else np.nan for r in rr]
            line,=ax.plot(range(8),values[:8],marker='.',label=p)
            ax.scatter([8],[values[8]],color=line.get_color(),marker='x')
        ax.axvline(7.5,color='gray',linestyle=':',alpha=.6)
    strata=list(csv.DictReader((root/'strata.csv').open()));fig,axs=plt.subplots(2,2,figsize=(14,9),constrained_layout=True)
    for ax,ds in zip(axs.flat,dict.fromkeys(r['dataset'] for r in rows)):
        rr=[r for r in strata if r['dataset']==ds and r['model']=='amc_mamba_d10' and r['class_id']=='-1' and r['reference_bin']!='-1']
        curves(ax,rr)
        ax.set_xticks(range(9),['<-10','-10:-5','-5:0','0:5','5:10','10:15','15:20','>=20','invalid'],rotation=35);ax.set_title(ds);ax.set_ylabel('Accuracy (%)');ax.set_xlabel('Raw-reference conditional SINR bin (dB)');ax.grid(alpha=.2)
    axs[0,0].legend();fig.suptitle('D10: identical members grouped by received raw-reference conditional SINR')
    for ext in ('png','svg'):fig.savefig(root/f'd10-conditional-sinr.{ext}',dpi=160)
    plt.close(fig)
    for ds in dict.fromkeys(r['dataset'] for r in rows):
        fig,axs=plt.subplots(2,4,figsize=(20,9),constrained_layout=True)
        models=[r['model'] for r in rows if r['dataset']==ds]
        for ax,model in zip(axs.flat,models):
            rr=[r for r in strata if r['dataset']==ds and r['model']==model and r['class_id']=='-1' and r['reference_bin']!='-1']
            curves(ax,rr)
            ax.set_xticks(range(9),['<-10','-10:-5','-5:0','0:5','5:10','10:15','15:20','>=20','invalid'],rotation=55);ax.set_title(model.replace('baseline_','').replace('amc_mamba_d10','D10'));ax.set_ylim(0,105);ax.set_ylabel('Accuracy (%)');ax.grid(alpha=.2)
        axs[0,0].legend();fig.suptitle(ds+': same members, raw-reference conditional SINR (dB); invalid separate')
        for ext in ('png','svg'):fig.savefig(root/f'{ds}-all-models-sinr.{ext}',dpi=160)
        plt.close(fig)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--sinr-root',type=Path,required=True);p.add_argument('--plot-only',action='store_true');p.add_argument('--verify-only',action='store_true');p.add_argument('--wait',action='store_true');a=p.parse_args()
    if not a.plot_only:run(a.root,a.sinr_root,a.wait)
    if not a.verify_only:plot(a.root)
