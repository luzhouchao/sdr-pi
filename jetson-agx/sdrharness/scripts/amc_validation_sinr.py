#!/usr/bin/env python3
"""Derived conditional SINR strata; frozen inputs/predictions remain read-only."""
import argparse
import csv
import json
import os
from pathlib import Path
import time
import h5py
import numpy as np
import amc_validation_eval as inference
import amc_rrc_pilot_report as pilot

c=pilot.r.c
atomic=inference.atomic
EDGES=np.array([-np.inf,-10,-5,0,5,10,15,20,np.inf])
BIN_NAMES=['<-10','[-10,-5)','[-5,0)','[0,5)','[5,10)','[10,15)','[15,20)','>=20','invalid']

def bin_ids(values):
    out=np.searchsorted(EDGES,values,side='right')-1
    out[~np.isfinite(values)]=8
    return out

def pair_counts(y,raw,guard,source,mask):
    a=raw[mask]==y[mask];b=guard[mask]==y[mask]
    return dict(rows=int(mask.sum()),source_correct=int((source[mask]==y[mask]).sum()),
        raw_correct=int(a.sum()),guard_correct=int(b.sum()),
        corrected=int((~a&b).sum()),regressed=int((a&~b).sum()))

def estimate_batch(capture,batch,d):
    corpus,_,_=inference.capture.batch_artifacts(batch)
    receipt=inference.read(batch/'batch-complete.json');processed=corpus/'processed.h5'
    expected=next(x for x in receipt['files'] if x['path']==str(processed.relative_to(batch)))
    c.require(inference.backend.digest(processed)==expected['sha256'],'sealed processing input')
    with h5py.File(processed) as f:
        blocks=list(f['blocks'].values())
        ids=np.concatenate([b['source_row'][:] for b in blocks]);labels=np.concatenate([b['class_id'][:] for b in blocks])
        z=np.concatenate([b['source_snr_db'][:] for b in blocks]);qs=[json.loads(q) for b in blocks for q in b['quality_json'][:]]
        source=inference.source_values(d,ids,labels,z);x=source[:,0].astype(np.float64)+1j*source[:,1].astype(np.float64)
        values=dict(source_row=ids,class_id=labels,source_snr_db=z,guard_applied=np.array([q['guard_status']=='applied' for q in qs]))
        for tag in ('raw','guard'):
            v=np.concatenate([b['inputs/'+tag][:] for b in blocks]);valid=np.concatenate([b['valid/'+tag][:] for b in blocks])
            rms=np.array([q[tag]['normalization_rms'] for q in qs]);y=(v[:,0].astype(np.float64)+1j*v[:,1].astype(np.float64))*rms[:,None]
            qualities=[pilot.quality(a,b,zz) if ok else dict(rx_sinr_db=None,rx_sinr_reason='unsynchronized') for a,b,zz,ok in zip(x,y,z,valid)]
            values[tag+'_sinr_db']=np.array([q['rx_sinr_db'] if q['rx_sinr_db'] is not None else np.nan for q in qualities])
            values[tag+'_reason']=np.array([q['rx_sinr_reason'] or '' for q in qualities],dtype='U64')
            values[tag+'_normalization_rms']=rms
            for metric in ('gain_disagreement','residual_power_ratio','reference_residual_db'):
                values[tag+'_'+metric]=np.array([(q.get('rx_sinr_diagnostics') or {}).get(metric) if
                    (q.get('rx_sinr_diagnostics') or {}).get(metric) is not None else np.nan for q in qualities])
    return values,expected['sha256']

def run(root,source):
    c.require(root.is_absolute() and root.resolve()==root and not root.exists(),'fresh derived result root')
    plan=inference.effective_plan(source,source/'resident-source-revision-v1.json')
    complete=inference.read(source/'complete.json');c.require(complete['status']=='complete','complete predictions')
    capture=Path(plan['source']);root.mkdir(mode=0o700)
    identity=dict(schema='amc-validation-conditional-sinr-v1',inference_root=str(source),capture_root=str(capture),
        inference_complete_sha256=inference.backend.digest(source/'complete.json'),
        inference_verification_sha256=inference.backend.digest(source/'final-verification.json'),
        method=pilot.METHOD,reference='matched_decimated_before_rms',paired_bins_reference='raw conditional SINR, identical rows for source/raw/guard',
        bins=BIN_NAMES,script_sha256=inference.backend.digest(__file__),estimator_sha256=inference.backend.digest(pilot.__file__),
        scalar_estimator_sha256=inference.backend.digest(c.__file__),
        assumptions=['nominal source Z partitions noisy source X power','held-out scalar channel error includes distortion',
                     'conditional engineering estimate, not independent calibrated SINR'],scope='all four original validation sets, no new inference/RF; invalid values retained separately')
    atomic(root/'plan.json',identity);results=[];csvrows=[]
    for d in plan['datasets']:
        name=d['dataset'];folder=root/name;folder.mkdir()
        c.require(inference.backend.digest(d['source_path'])==d['source_sha256'],'source identity')
        seal=inference.read(capture/name/'dataset-complete.json');parts=[];parents=[]
        for item in seal['batch_receipts']:
            batch=capture/name/f"batch-{item['batch']:05d}"
            c.require(inference.backend.digest(batch/'batch-complete.json')==item['sha256'],'batch receipt')
            values,parent=estimate_batch(capture,batch,d);parts.append(values);parents.append(dict(batch=item['batch'],processed_sha256=parent))
            atomic(root/'progress.json',dict(dataset=name,batch=item['batch'],batches=seal['batches'],status='estimating'))
        values={key:np.concatenate([part[key] for part in parts]) for key in parts[0]};del parts
        ids=values['source_row'];y=values['class_id'];c.require(len(y)==d['rows'],'full validation')
        c.require(np.array_equal(ids,np.load(capture/name/'validation-rows.npy',allow_pickle=False)),'same validation rank')
        values['validation_rank']=np.arange(len(ids));values['reference_bin']=bin_ids(values['raw_sinr_db'])
        with (folder/'sinr.npz').open('wb') as f:np.savez_compressed(f,**values);f.flush();os.fsync(f.fileno())
        dataset=dict(dataset=name,rows=len(ids),sinr_sha256=inference.backend.digest(folder/'sinr.npz'),parents=parents,models=[],validity={})
        for tag in ('raw','guard'):
            a=values[tag+'_sinr_db'];reasons,counts=np.unique(values[tag+'_reason'][~np.isfinite(a)],return_counts=True)
            dataset['validity'][tag]=dict(valid=int(np.isfinite(a).sum()),invalid=int((~np.isfinite(a)).sum()),
                invalid_reasons=dict(zip(map(str,reasons),map(int,counts))))
        classes=d['class_names']
        if name=='rml2018a':classes=inference.read(c.REPO/'jetson-agx/sdrharness/config/amc/rml2018a-labels.server-v1.json')['classes']
        for variant in inference.VARIANTS:
            out=source/name/variant;pred={tag:[] for tag in ('source','raw','guard')}
            for start in range(0,len(ids),inference.CHUNK):
                end=min(start+inference.CHUNK,len(ids))
                for tags,path in [(('raw','guard'),out/f'rows-{start:07d}.npz'),(('source',),out/'source'/f'rows-{start:07d}.npz')]:
                    c.require(inference.backend.digest(path)==inference.read(path.with_suffix('.json'))['sha256'],'prediction identity')
                    with np.load(path,allow_pickle=False) as v:
                        c.require(np.array_equal(v['source_row'],ids[start:end]) and np.array_equal(v['class_id'],y[start:end]),'paired members')
                        for tag in tags:pred[tag].append(v[tag+'_prediction'])
            pred={tag:np.concatenate(a) for tag,a in pred.items()};model=dict(model=variant,bins=[],classes=[])
            for class_id in [-1,*range(len(classes))]:
                records=[]
                for i,label in enumerate(BIN_NAMES):
                    mask=(values['reference_bin']==i)&((y==class_id) if class_id>=0 else True)
                    counts=pair_counts(y,pred['raw'],pred['guard'],pred['source'],mask)
                    record=dict(bin=label,**counts);records.append(record)
                    csvrows.append(dict(dataset=name,model=variant,class_id=class_id,class_name='ALL' if class_id<0 else classes[class_id],**record))
                if class_id<0:model['bins']=records
                else:model['classes'].append(dict(class_id=class_id,class_name=classes[class_id],bins=records))
            c.require(sum(x['rows'] for x in model['bins'])==len(ids),'no invalid members dropped')
            original=inference.read(out/'result-three-planes.json')
            for tag in pred:c.require(sum(x[tag+'_correct'] for x in model['bins'])==original['planes'][tag]['correct'],'strata reproduce full score')
            dataset['models'].append(model)
        atomic(folder/'report.json',dataset);results.append(dataset)
        print(json.dumps(dict(dataset=name,validity=dataset['validity'])),flush=True)
    with (root/'strata.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(csvrows[0]));writer.writeheader();writer.writerows(csvrows)
    atomic(root/'complete.json',dict(status='complete',plan_sha256=inference.backend.digest(root/'plan.json'),
        csv_sha256=inference.backend.digest(root/'strata.csv'),datasets=[dict(dataset=d['dataset'],report_sha256=inference.backend.digest(root/d['dataset']/'report.json')) for d in results]))
    atomic(root/'progress.json',dict(status='complete',datasets=4,rows=sum(d['rows'] for d in results)))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--source',type=Path,required=True);a=p.parse_args();run(a.root,a.source)
