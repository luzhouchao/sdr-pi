#!/usr/bin/env python3
"""Bounded, sealed-IQ guard cancellation replay; optional48-window inference.

No RF execution or changes to the existing campaign/default preprocessing.
"""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import time

import h5py
import numpy as np

import rml2018a_campaign as c
import rml2018a_lo_cancellation as lo

BATCHES = (4267,22016)


def runner():
    spec=importlib.util.spec_from_file_location('lo_replay_runner',Path(__file__).with_name('rml2018a-rf-campaign.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def prepare(root):
    r=runner();p=r.load_plan(root)
    c.require(p['tx_level_profile']=='gain-pair-pilot', 'registered two-class paired parent')
    results=[];tensors={}
    for index in BATCHES:
        d=root/f'batch-{index:07d}';a=r.document(d/'audit.json');s=r.document(d/'source.json')
        done=r.document(d/'capture-complete.json')
        c.require(c.file_hash(d/'audit.json')==done['audit_sha256'] and a['restored'] and
            a['status']==done['status']=='synchronized', 'restored sealed capture')
        c.require(done['rows']==s['rows']==c.batch_rows(2555904,index), 'source row association')
        raw,seal=r.native_check(d,r.document(d/'rx-plan.json'))
        c.require(seal==a['seal'], 'native seal')
        baseline,sync=c.synchronize(raw,p['run_id'],index,24)
        c.require(sync==a['sync'], 'original synchronization replay')
        corrected,info=lo.cancel(raw,sync)
        received=lo.payload(corrected,sync)
        # Source and predictions are read only after the canceller has finished.
        with h5py.File(p['source']['path'],'r') as h:
            iq=h['X'][s['rows']];labels=h['Y'][s['rows']].argmax(axis=1);zs=h['Z'][s['rows']].ravel()
        c.require(c.digest(iq.tobytes())==s['original_iq_sha256'] and
            labels.tolist()==s['class_ids'] and zs.tolist()==s['source_snr_db'] and np.all(zs==30), 'source seal')
        pred=r.document(d/'predictions.json')
        c.require(pred['audit_sha256']==done['audit_sha256'] and pred['sync']==sync and
            pred['profile_sha256']==p['profile_sha256'] and pred['label_map_sha256']==p['label_map_sha256'], 'parent predictions')
        rows=[]
        for k,row in enumerate(s['rows']):
            x=iq[k,:,0].astype(float)+1j*iq[k,:,1];y=received[k]
            raw_q=c.receive_quality('synchronized',x,baseline[k],float(zs[k]))
            c.require(all(a['receive_quality'][k][key]==value for key,value in raw_q.items()),'raw quality replay')
            q=lo.quality(x,y,float(zs[k]),info)
            old=pred['rows'][k]
            c.require(old['row']==row and old['true_id']==int(labels[k]), 'prediction association')
            for tag,value in (('source',x),('received',baseline[k])):
                pp=old[tag+'_prediction']
                c.require(c.digest(c.normalize_window(value).tobytes())==pp['input_sha256'] and
                    len(pp['logits'])==24 and np.isfinite(pp['logits']).all() and
                    int(np.argmax(pp['logits']))==pp['id'], 'parent model input/logits')
            def metrics(value):
                xc=x-x.mean();yc=value-value.mean();g=np.vdot(xc,yc)/np.vdot(xc,xc)
                residual=value-g*x;spec=abs(np.fft.fft(residual))**2/1024**2
                band=abs(np.fft.fftfreq(1024,1/c.RATE)-250000)<=10000
                return dict(correlation=float(abs(np.vdot(x,value))/(np.linalg.norm(x)*np.linalg.norm(value))),
                    reference_power_counts2=float(np.mean(abs(g*x)**2)),
                    residual_power_counts2=float(np.mean(abs(residual)**2)),
                    lo_band_power_counts2=float(spec[band].sum()))
            rows.append(dict(row=row,true_id=int(labels[k]),source_snr_db=float(zs[k]),
                raw_quality=raw_q,post_cancel_quality=q,raw_metrics=metrics(baseline[k]),
                post_cancel_metrics=metrics(y),corrected_input_sha256=c.digest(c.normalize_window(y).tobytes()),
                parent_source_id=old['source_prediction']['id'],parent_received_id=old['received_prediction']['id']))
        values=[v['post_cancel_quality']['rx_sinr_db'] for v in rows if v['post_cancel_quality']['rx_sinr_status']=='estimated']
        raw_values=[v['raw_quality']['rx_sinr_db'] for v in rows if v['raw_quality']['rx_sinr_status']=='estimated']
        summary=dict(rows=24,raw_estimated_rows=len(raw_values),post_cancel_estimated_rows=len(values),
            raw_sinr_median_db=float(np.median(raw_values)) if raw_values else None,
            post_cancel_sinr_median_db=float(np.median(values)) if values else None,
            post_cancel_sinr_min_db=min(values) if values else None,post_cancel_sinr_max_db=max(values) if values else None,
            post_cancel_at_least_15db=sum(v>=15 for v in values),post_cancel_at_least_20db=sum(v>=20 for v in values),
            raw_correlation_median=float(np.median([v['raw_metrics']['correlation'] for v in rows])),
            post_cancel_correlation_median=float(np.median([v['post_cancel_metrics']['correlation'] for v in rows])))
        eligible=(info['status']=='applied' and len(values)==24 and len(raw_values)==24 and
            summary['post_cancel_sinr_median_db']>=15 and all(v['post_cancel_quality']['rx_sinr_db']>=v['raw_quality']['rx_sinr_db'] for v in rows))
        results.append(dict(batch=index,seal=seal,parent_audit_sha256=done['audit_sha256'],
            parent_source_sha256=c.file_hash(d/'source.json'),parent_predictions_sha256=c.file_hash(d/'predictions.json'),
            fixed_sync=sync,cancellation=info,rows=rows,summary=summary,inference_eligible=eligible,
            parent_model_identity=pred['model_identity']))
        tensors[index]=received
    report=dict(schema='rml2018a-guard-lo-replay-v1',parent=str(root),
        parent_plan_sha256=c.file_hash(root/'run-plan.json'),parent_run_id=p['run_id'],
        software={name:c.file_hash(Path(__file__).with_name(name)) for name in
            ('diagnose-rml2018a-lo-cancellation.py','rml2018a_lo_cancellation.py','rml2018a_campaign.py')},
        contract=lo.contract(),results=results,inference_eligible=all(v['inference_eligible'] for v in results),
        new_rf_captures=0,model_inferences=0,recognizer_available=False,
        semantics='Post-hoc retained-IQ engineering DSP. Fixed original synchronization; raw IQ/quality unchanged. Post-cancel quality is conditional, not calibrated physical RF SINR or independent admission.')
    return report,tensors


def infer(root, output):
    r=runner();prepared=r.document(output/'prepared.json');report,tensors=prepare(root)
    c.require(report==prepared,'prepared evidence/source/software changed')
    c.require(report['inference_eligible'],'offline quality gate; no model execution')
    c.require(not (output/'inference.json').exists(),'inference already exists; do not rerun')
    p=r.load_plan(root);scratch=output/'scratch'
    c.require(scratch.is_dir() and scratch.resolve()==scratch, 'bounded scratch')
    os.environ.update(TMPDIR=str(scratch),XDG_CACHE_HOME=str(scratch),TRITON_CACHE_DIR=str(scratch/'triton'),
        CUDA_CACHE_PATH=str(scratch/'cuda'),PYTHONDONTWRITEBYTECODE='1')
    multi=r.module('lo_replay_multi','validate-b210-multiclass.py')
    from gpu_lease import GpuLease
    lease=GpuLease(scratch/'gpu-gate','mamba');token=None
    receipt=dict(status='failed',prepared_sha256=c.file_hash(output/'prepared.json'),rows=[],
        maximum_model_windows=48,model_windows=0,warmup_windows=0,maximum_warmup_windows=2,
        deadline_seconds=580,new_rf_captures=0,recognizer_available=False,name_status='provisional',
        profile_sha256=p['profile_sha256'],label_map_sha256=p['label_map_sha256'],
        semantics='Corrected48 reused engineering rows only; source/raw predictions reused, not independent accuracy')
    try:
        token=asyncio.run(lease.acquire(time.monotonic()+10,request='rml-guard-lo-cancel'))
        with multi.idle_spark_pause(evidence_root=output):
            w=r.module('lo_replay_worker','amc-mamba-worker.py');backend=w.RfV1Backend(r.PROFILE)
            c.require(all(v.dtype==w.torch.float32 for v in backend.model.parameters()),'frozen FP32 weights')
            receipt.update(model_identity=backend.admission_identity,warmup_windows=2)
            c.require(all(v['parent_model_identity']==backend.admission_identity for v in report['results']), 'same frozen model')
            deadline=time.monotonic()+580
            for result in report['results']:
                index=result['batch']
                for k,row in enumerate(result['rows']):
                    c.require(time.monotonic()<deadline and receipt['model_windows']<48,'inference budget')
                    tensor=c.normalize_window(tensors[index][k]);sha=c.digest(tensor.tobytes())
                    c.require(sha==row['corrected_input_sha256'],'actual model input')
                    logits,us=backend.classify_logits(tensor)
                    c.require(np.asarray(logits).shape==(24,) and np.isfinite(logits).all(),'finite24 logits')
                    receipt['rows'].append(dict(batch=index,row=row['row'],true_id=row['true_id'],
                        id=int(np.argmax(logits)),logits=logits,input_sha256=sha,inference_us=us))
                    receipt['model_windows']+=1
                print(json.dumps(dict(event='lo_cancel_inferred',batch=index,rows=24)),flush=True)
            del backend
        receipt.update(status='completed',correct=sum(v['id']==v['true_id'] for v in receipt['rows']))
    except BaseException as e:
        receipt['error']=f'{type(e).__name__}: {e}';raise
    finally:
        if token is not None:lease.release(token)
        receipt['gpu_lease']=lease.metrics.copy();lease.close()
        c.save(output/'inference.json',receipt)
    return receipt


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('analyze','infer','verify'))
    p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    c.require(args.output.is_absolute() and args.output.resolve()==args.output and
        args.output.parent==Path('/var/tmp/sdrharness-dev') and args.output.name.startswith('rml-lo-cancel-'), 'derived root')
    if args.command=='analyze':
        c.require(not (args.output/'prepared.json').exists(),'derived report already exists')
        c.require(shutil.disk_usage(args.output.parent).free>64*1024*1024,'derived reserve')
        args.output.mkdir(mode=0o700,exist_ok=True);(args.output/'scratch').mkdir(mode=0o700,exist_ok=True)
        report,_=prepare(args.root);c.save(args.output/'prepared.json',report)
        print(json.dumps([dict(batch=v['batch'],cancellation=v['cancellation'],summary=v['summary']) for v in report['results']],indent=2))
    elif args.command=='verify':
        report,_=prepare(args.root);c.require(report==runner().document(args.output/'prepared.json'),'exact deterministic replay')
        receipt=runner().document(args.output/'inference.json') if (args.output/'inference.json').exists() else None
        if receipt:
            c.require(receipt['status']=='completed' and receipt['prepared_sha256']==c.file_hash(args.output/'prepared.json') and
                receipt['model_windows']==len(receipt['rows'])==48,'inference receipt')
            expected=[(b['batch'],v) for b in report['results'] for v in b['rows']]
            for (batch,row),pred in zip(expected,receipt['rows']):
                c.require((pred['batch'],pred['row'],pred['true_id'])==(batch,row['row'],row['true_id']) and
                    pred['input_sha256']==row['corrected_input_sha256'] and len(pred['logits'])==24 and
                    np.isfinite(pred['logits']).all() and int(np.argmax(pred['logits']))==pred['id'],'prediction replay')
            c.require(receipt['correct']==sum(v['id']==v['true_id'] for v in receipt['rows']),'prediction count')
            c.require(all(v['parent_model_identity']==receipt['model_identity'] for v in report['results']),'model identity')
        print(json.dumps(dict(status='verified',native_captures=2,quality_rows=48,parent_model_input_hashes=96,
            new_model_input_hashes=48 if receipt else 0,model_reexecuted=False,new_rf=0)))
    else:
        def abort(sig,frame):raise RuntimeError(f'inference stopped by signal{sig}')
        signal.signal(signal.SIGINT,abort);signal.signal(signal.SIGTERM,abort)
        result=infer(args.root,args.output)
        print(json.dumps({k:v for k,v in result.items() if k not in ('rows','model_identity')}))


if __name__=='__main__':main()
