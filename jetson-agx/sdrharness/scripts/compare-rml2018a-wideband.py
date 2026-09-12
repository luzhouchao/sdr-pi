#!/usr/bin/env python3
"""One fixed 500kHz low-pass engineering comparison on sealed QAM captures."""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import signal
import time
import numpy as np
import rml2018a_campaign as c
import rml2018a_guard_tone as guard
import rml2018a_lo_cancellation as lo
import rml2018a_pilot_timing as timing

TAGS = ('source_wide', 'wide', 'wide_timing')


def module(name, file):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def taps():
    n=np.arange(129)-64
    h=(1000000/c.RATE)*np.sinc(1000000/c.RATE*n)*np.kaiser(129,8)
    return h/h.sum()


def prepare(output):
    plan=json.loads((output/'plan.json').read_text());parent=Path(plan['parent'])
    comparison=module('wide_parent','compare-rml2018a-pilot-timing.py');runner=comparison.runner()
    inventory=runner.document(c.REPO/'docs/evidence/RML2018A_QAM_GUARD_REPAIR_2026-09-12.json')
    # Preserve immutable lineage before accessing source/predictions.
    for root in inventory['retained_roots']:
        for f in root['files']:
            path=Path(f['path'])
            c.require(path.stat().st_size==f['bytes'] and c.file_hash(path)==f['sha256'],'sealed parent')
    old=runner.document(parent/'prepared.json');baseline,tensors=comparison.prepare(Path(old['parent']))
    c.require(old==baseline and old['source_rows']==96 and old['tags']==['source','raw','lo','guard','timing'], 'exact QAM parent')
    c.require(plan['batches']==list(c.RML_GUARD_BATCHES) and plan['variants']==list(TAGS) and
              plan['maximum_model_windows']==288 and plan['rf_operations']==0, 'bounded fixed plan')
    h=taps();batches=[];inputs={};all_fidelity=True
    for b in old['results']:
        batch=b['batch'];d=Path(old['parent'])/f'batch-{batch:07d}'
        raw,seal=runner.native_check(d,runner.document(d/'rx-plan.json'));c.require(seal==b['seal'],'native seal')
        corrected,gi=guard.cancel(raw,b['sync']);c.require(gi==b['guard_correction'] and gi['status']=='applied','parent guard')
        sync=b['sync'];n=np.arange(len(raw));rotated=corrected*np.exp(-2j*np.pi*sync['estimated_cfo_hz']*n/c.RATE+1j*sync['phase_rotation_rad'])
        filtered=np.convolve(rotated,h,mode='same');start=sync['payload_marker_offset']+1024
        c.require(start>=64 and start+24576+64<len(raw),'real full-capture FIR halos')
        wide=filtered[start:start+24576].reshape(24,1024)
        ti=b['timing_correction'];c.require(ti['status']=='applied','frozen timing required')
        target=start+np.arange(24576);slope=ti['drift_ppm']/1e6
        coordinates=target+(ti['offset_samples']+slope*target)/(1-slope)
        wide_timing=timing.sample(filtered,coordinates).reshape(24,1024)
        x=tensors[batch]['source'];iq=np.stack((x.real,x.imag),axis=-1)
        frame,scales=c.packet(iq,old['run_id'],batch,level_profile='qam-guard-pilot')
        c.require(c.digest(frame.tobytes())==runner.document(d/'tx-plan.json')['payload_sha256'],'source packet')
        # Actual neighbouring source rows, their TX scales and guards are used.
        # This is a fidelity control, never a source-assisted RX correction.
        source_filtered=np.convolve(np.tile(frame,3),h,mode='same')
        offset=len(frame)+c.GUARD+c.MARKER
        source_wide=source_filtered[offset:offset+24576].reshape(24,1024)/scales[:,None]
        parts=dict(source_wide=source_wide,wide=wide,wide_timing=wide_timing);inputs[batch]=parts;rows=[]
        for k,r in enumerate(b['rows']):
            error=float(np.mean(abs(source_wide[k]-x[k])**2)/np.mean(abs(x[k])**2))
            ratio=float(np.mean(abs(source_wide[k])**2)/np.mean(abs(x[k])**2))
            valid=error<=.003 and .995<=ratio<=1.005
            all_fidelity &= valid
            qualities={}
            for tag,y in (('wide',wide[k]),('wide_timing',wide_timing[k])):
                q=c.receive_quality('synchronized',x[k],y,30.);c.validate_receive_quality(q,30.)
                q.update(rx_sinr_reference_plane='received_payload_after_guard_'+tag+'_before_rms',
                         rx_payload_filter='129-tap Kaiser8 500kHz low-pass; full capture halos')
                qualities[tag]=q
            rows.append(dict(row=r['row'],true_id=r['true_id'],source_relative_error=error,
                source_power_ratio=ratio,source_fidelity_valid=valid,quality=qualities,
                inputs={tag:c.digest(c.normalize_window(v[k]).tobytes()) for tag,v in parts.items()}))
        batches.append(dict(batch=batch,class_id=b['class_id'],seal=seal,rows=rows))
    return dict(schema='rml-wideband-fixed-comparison-v1',parent=str(parent),parent_prepared_sha256=c.file_hash(parent/'prepared.json'),
        parent_inference_sha256=c.file_hash(parent/'inference.json'),plan_sha256=c.file_hash(output/'plan.json'),
        software_sha256=c.file_hash(Path(__file__)),filter_sha256=c.digest(h.astype('<f8').tobytes()),
        all_source_fidelity_valid=bool(all_fidelity),source_rows=96,maximum_model_windows=288,results=batches,
        profile_sha256=old['profile_sha256'],label_map_sha256=old['label_map_sha256'],recognizer_available=False,
        semantics='Single fixed posthoc engineering comparison; not independent accuracy; original noisy X remains SINR reference'),inputs


def infer(output):
    report,inputs=prepare(output);runner=module('wide_compare','compare-rml2018a-pilot-timing.py').runner()
    c.require(report==runner.document(output/'prepared.json'),'prepared replay')
    c.require(report['all_source_fidelity_valid'],'source fidelity failed; no model')
    c.require(not (output/'inference.json').exists(),'no repeat inference')
    scratch=output/'scratch';scratch.mkdir(mode=0o700,exist_ok=True)
    os.environ.update(TMPDIR=str(scratch),XDG_CACHE_HOME=str(scratch),TRITON_CACHE_DIR=str(scratch/'triton'),CUDA_CACHE_PATH=str(scratch/'cuda'))
    from gpu_lease import GpuLease
    lease=GpuLease(scratch/'gpu-gate','mamba');token=None
    receipt=dict(status='failed',prepared_sha256=c.file_hash(output/'prepared.json'),model_windows=0,warmup_windows=0,rows=[])
    try:
        token=asyncio.run(lease.acquire(time.monotonic()+10,request='fixed-wideband'))
        multi=runner.module('wide_spark','validate-b210-multiclass.py')
        with multi.idle_spark_pause(evidence_root=output):
            worker=runner.module('wide_worker','amc-mamba-worker.py');backend=worker.RfV1Backend(runner.PROFILE)
            c.require(all(v.dtype==worker.torch.float32 for v in backend.model.parameters()),'FP32 weights')
            receipt.update(model_identity=backend.admission_identity,warmup_windows=2)
            end=time.monotonic()+540
            for b in report['results']:
                for k,row in enumerate(b['rows']):
                    pred={}
                    for tag in TAGS:
                        c.require(time.monotonic()<end and receipt['model_windows']<288,'model budget')
                        tensor=c.normalize_window(inputs[b['batch']][tag][k]);sha=c.digest(tensor.tobytes())
                        c.require(sha==row['inputs'][tag],'input hash')
                        logits,us=backend.classify_logits(tensor)
                        c.require(np.asarray(logits).shape==(24,) and np.isfinite(logits).all(),'finite logits')
                        pred[tag]=dict(id=int(np.argmax(logits)),logits=logits,input_sha256=sha,inference_us=us)
                        receipt['model_windows']+=1
                    receipt['rows'].append(dict(row=row['row'],batch=b['batch'],true_id=row['true_id'],predictions=pred))
                print(json.dumps(dict(batch=b['batch'],inferred=24)),flush=True)
            del backend
        receipt.update(status='completed',summary={tag:sum(r['predictions'][tag]['id']==r['true_id'] for r in receipt['rows']) for tag in TAGS})
    finally:
        if token is not None:lease.release(token)
        receipt['lease']=lease.metrics.copy();lease.close();c.save(output/'inference.json',receipt)
    return receipt


def verify(output):
    runner=module('wide_verify','compare-rml2018a-pilot-timing.py').runner()
    report,_=prepare(output);c.require(report==runner.document(output/'prepared.json'),'deterministic prepared replay')
    receipt=runner.document(output/'inference.json');c.require(receipt['status']=='completed' and receipt['model_windows']==288 and
        receipt['prepared_sha256']==c.file_hash(output/'prepared.json') and len(receipt['rows'])==96,'inference receipt')
    for (batch,row),p in zip([(b['batch'],r) for b in report['results'] for r in b['rows']],receipt['rows']):
        c.require((batch,row['row'],row['true_id'])==(p['batch'],p['row'],p['true_id']),'row association')
        for tag in TAGS:
            q=p['predictions'][tag]
            c.require(q['input_sha256']==row['inputs'][tag] and len(q['logits'])==24 and np.isfinite(q['logits']).all()
                and int(np.argmax(q['logits']))==q['id'],'prediction verification')
    c.require(receipt['summary']=={t:sum(r['predictions'][t]['id']==r['true_id'] for r in receipt['rows']) for t in TAGS},'summary')
    return dict(status='verified',source_rows=96,model_input_hashes=288,model_reexecuted=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['prepare','infer','verify'])
    parser.add_argument('--output',type=Path,required=True);a=parser.parse_args()
    c.require(a.output.resolve()==a.output and a.output.parent==Path('/var/tmp/sdrharness-dev') and
              a.output.name.startswith('rml-wideband-'),'feature output root')
    def abort(sig,frame):raise RuntimeError('wideband bounded operation interrupted')
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM):signal.signal(sig,abort)
    signal.alarm(650)
    if a.command=='prepare':
        c.require(not (a.output/'prepared.json').exists(),'new prepared record required')
        r,_=prepare(a.output);c.save(a.output/'prepared.json',r);print(json.dumps(dict(source_fidelity_passed=r['all_source_fidelity_valid'])))
    elif a.command=='infer':
        with module('wide_lock','compare-rml2018a-pilot-timing.py').runner().lock(a.output):
            print(json.dumps(infer(a.output)['summary']))
    else:print(json.dumps(verify(a.output)))
