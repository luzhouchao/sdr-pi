#!/usr/bin/env python3
"""Validation-only source TX-scale control. No radio access or training."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import time
import types
import h5py
import numpy as np
import rml2018a_model_collection_eval as ev
import rml2018a_campaign as c

PARENT=Path('/var/tmp/sdrharness-dev/rml2018a-offline-baseline-20260916')
REPO=Path(__file__).resolve().parents[3]


def read(p):
    return json.loads(Path(p).read_text())


def ahash(x):
    return hashlib.sha256(np.ascontiguousarray(x).tobytes()).hexdigest()


def run(out):
    started=time.monotonic()
    def stop(*_):
        raise InterruptedError('deadline/signal')
    for sig in (signal.SIGALRM,signal.SIGTERM,signal.SIGINT):signal.signal(sig,stop)
    signal.alarm(600)
    ev.require(out.parent==PARENT.parent and not out.exists(),'fresh bounded output')
    out.mkdir(mode=0o700)
    evidence=read(REPO/'docs/evidence/RML2018A_OFFLINE_BASELINE_2026-09-16.json')
    ev.require(ev.digest(PARENT/'retention.json')==evidence['retention']['sha256'],'parent seal')
    retained=read(PARENT/'retention.json')
    for r in retained['files']:ev.identity(r['path'],r['sha256'])
    prior=read(PARENT/'plan.json')
    val,split=ev.load_validation_split(prior['split']['path'],ev.SEED42_SPLIT_SHA)
    with np.load(PARENT/'predictions.npz',allow_pickle=False) as f:old={k:f[k] for k in f.files}
    ids=old['source_row'];y=old['truth'];z=old['source_snr_db']
    ev.require(len(ids)==2496 and len(set(ids))==2496 and np.isin(ids,val).all() and ahash(ids)==prior['source_ids_sha256'],'fixed validation IDs')
    collection=read(PARENT/'collection-identity.json')
    ev.identity(collection['path'],collection['sha256'])
    manifest=read(collection['path'])
    model_ids=[ev.identity(ev.COLLECTION/f['relative'],f['sha256']) for f in manifest['transferred_files']]
    # Recover the actual archived function without importing any hardware runner.
    relative='jetson-agx/sdrharness/scripts/rml2018a_snr_stream.py'
    expected={}
    for session in retained['lineage']['sessions']:
        p=Path(session['path']);expected[str(p)]=read(p)['software'][str(REPO/relative)]
    revisions=subprocess.check_output(['git','log','--all','--format=%H','--',relative],cwd=REPO,text=True).split()
    historical={}
    for rev in revisions:
        data=subprocess.check_output(['git','show',rev+':'+relative],cwd=REPO)
        sha=hashlib.sha256(data).hexdigest()
        if sha in expected.values():
            tree=ast.parse(data);node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='packet_block')
            historical[sha]=dict(revision=rev,sha256=sha,function_source=ast.get_source_segment(data.decode(),node))
        if set(historical)==set(expected.values()):break
    ev.require(set(historical)==set(expected.values()),'archived packet implementation missing')
    ev.require(len({v['function_source'] for v in historical.values()})==1,'historical scaling differs')
    source_path=ev.ASSET/'datasets/rml2018a/RML2018a.hdf5'
    plan=dict(schema='source-tx-peak-validation-control-v1',head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        script=ev.identity(__file__),parent_retention=ev.identity(PARENT/'retention.json'),split=split,model=prior['model'],
        source_ids_sha256=ahash(ids),rows=2496,new_predictions=2496,reused_comparators=['source','source_rms','raw','guard','raw_pilot','guard_pilot'],
        rule='complex64 source * (.2*sqrt(10)/max(abs(complex64 source))); historical packet_block dtype/order; no receive correction',
        historical_implementations=historical,plan_implementation_mapping=expected,
        acceptance=dict(member_label_exact=True,historical_payload_bitwise=True,peak_diagnostic_atol=1e-7,peak_diagnostic_failure_action='retain flags and all members; archived payload byte equality remains mandatory',papr_atol_db=2e-6,finite_logits=True,drop_rows=0),
        budget=dict(deadline_seconds=600,host_bytes=4*1024**3,gpu_bytes=4*1024**3,output_bytes=64*1024**2,free_bytes=shutil.disk_usage(out).free),
        precision='original D8 seed42, strict load, FP32, TF32 off, batch1024',rf=False,training=False,
        prior_attempt=ev.identity(PARENT.parent/'rml2018a-source-peak-control-20260916/failure.json'),
        correction='prior theoretical-peak rejection interrupted before inference; unchanged threshold now explicitly retained as failed diagnostic, not relabeled as passed; no samples or IQ changed')
    ev.require(plan['budget']['free_bytes']>1024**3,'disk reserve')
    ev.atomic(out/'plan.json',plan)
    source_id=ev.identity(source_path,ev.ORIGINAL_SHA)
    with h5py.File(source_path,'r') as f:
        x=f['X'][ids];ev.require(np.array_equal(f['Y'][ids].argmax(1),y) and np.array_equal(f['Z'][ids].reshape(-1),z),'source labels/Z')
    values=x[:,:,0]+1j*x[:,:,1]
    peak=.2*np.sqrt(10)
    scaled=values*(peak/np.max(abs(values),axis=1)[:,None])
    ev.require(scaled.dtype==np.complex64 and np.isfinite(scaled).all(),'finite historical dtype')
    scope=dict(np=np,c=c,dsp=types.SimpleNamespace(FRAME_SAMPLES=17920))
    exec(compile(next(iter(historical.values()))['function_source'],'<archived packet_block>','exec'),scope)
    for lo in range(0,len(ids),1024):
        n=min(1024,len(ids)-lo);v=values[lo:lo+n]
        padded=np.concatenate((v,np.repeat(v[-1:],1024-n,axis=0)))
        wave=scope['packet_block'](padded,'offline-verification-only',0)
        payload=wave.reshape(64,17920)[:,1280:1280+16384].reshape(1024,1024)[:n]
        ev.require(np.array_equal(payload,scaled[lo:lo+n]),'archived packet payload mismatch')
    model_input=np.ascontiguousarray(np.stack((scaled.real,scaled.imag),axis=1))
    powers=np.sum(model_input.astype(np.float64)**2,axis=1)
    rms=np.sqrt(powers.mean(1));papr=10*np.log10(powers.max(1)/powers.mean(1))
    peak_error=float(np.max(abs(np.sqrt(powers.max(1))-peak)))
    papr_error=float(np.max(abs(papr-old['source_papr_db'])))
    ev.require(papr_error<=2e-6,'PAPR invariance contract')
    peak_failed=np.abs(np.sqrt(powers.max(1))-peak)>1e-7
    input_audit=dict(source=source_id,model_files=model_ids,input_sha256=ahash(model_input),historical_packet_payload_bitwise=True,
        peak_max_error=peak_error,peak_diagnostic_passed=bool(not peak_failed.any()),peak_diagnostic_failed_rows=ids[peak_failed].tolist(),papr_max_error_db=papr_error,source_peak=np.percentile(np.max(abs(values),axis=1),[5,50,95]).tolist(),
        scaled_rms_p05_p50_p95=np.percentile(rms,[5,50,95]).tolist(),scaled_papr_p05_p50_p95=np.percentile(papr,[5,50,95]).tolist())
    ev.atomic(out/'input-audit.json',input_audit)
    print(json.dumps(dict(stage='verified_input',seconds=time.monotonic()-started)),flush=True)
    torch=ev.setup(out);model=ev.load_model(prior['model'],torch);logits=[]
    for lo in range(0,len(ids),1024):
        ev.require(not (out/'STOP').exists(),'STOP')
        logits.append(ev.predict(model,model_input[lo:lo+1024],torch,'fp32'))
    logits=np.concatenate(logits)
    preds={k:old[k+'_logits'].argmax(1) for k in plan['reused_comparators']};preds['source_tx_peak']=logits.argmax(1)
    def summary(mask):
        correct={k:int(((v==y)&mask).sum()) for k,v in preds.items()};pairs=[]
        for a,b in [('source','source_tx_peak'),('source_rms','source_tx_peak'),('source_tx_peak','guard_pilot'),('source_tx_peak','raw_pilot')]:
            ac=preds[a]==y;bc=preds[b]==y
            pairs.append(dict(before=a,after=b,corrected=int((~ac&bc&mask).sum()),regressed=int((ac&~bc&mask).sum()),
                top1_agreement=int(((preds[a]==preds[b])&mask).sum())))
        return dict(rows=int(mask.sum()),correct=correct,pairs=pairs)
    classes=prior['model']['class_order']
    result=dict(overall=summary(np.ones(2496,bool)),per_class=[dict(label=classes[k],**summary(y==k)) for k in range(24)],
        per_source_snr=[dict(source_snr_db=int(k),**summary(z==k)) for k in sorted(set(z))],
        per_cell=[dict(class_id=k,source_snr_db=int(j),**summary((y==k)&(z==j))) for k in range(24) for j in sorted(set(z))],
        predicted_class_counts={k:np.bincount(p,minlength=24).tolist() for k,p in preds.items()},
        elapsed_seconds=time.monotonic()-started,peak_cuda_bytes=torch.cuda.max_memory_allocated(),peak_host_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        new_predictions=2496,skipped=0,validation_only=True)
    ev.require(result['peak_cuda_bytes']<=4*1024**3 and result['peak_host_rss_bytes']<=4*1024**3,'resource budget')
    np.savez(out/'predictions.npz',source_row=ids,truth=y,source_snr_db=z,validation_rank=np.searchsorted(val,ids),logits=logits,input_rms=rms,input_papr_db=papr,theoretical_peak_diagnostic_failed=peak_failed)
    ev.atomic(out/'results.json',result)
    ev.unchanged(source_id)
    print(json.dumps(dict(stage='complete',overall=result['overall'],seconds=result['elapsed_seconds'])),flush=True)
    signal.alarm(0)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    try:run(args.output)
    finally:
        cache=ev.cache_root(args.output)
        if cache.exists():
            files=[p for p in cache.rglob('*') if p.is_file()]
            ev.atomic(args.output/'cache-cleanup.json',dict(path=str(cache),files=len(files),bytes=sum(p.stat().st_size for p in files)))
            shutil.rmtree(cache);ev.require(not cache.exists(),'cleanup')
