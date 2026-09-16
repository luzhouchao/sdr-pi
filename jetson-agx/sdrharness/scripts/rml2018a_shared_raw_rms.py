#!/usr/bin/env python3
"""One validation-only receive amplitude ablation; no RF or source-IQ access."""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import time
import h5py
import numpy as np
import rml2018a_model_collection_eval as ev

PARENT=Path('/var/tmp/sdrharness-dev/rml2018a-offline-baseline-20260916')
REPO=Path(__file__).resolve().parents[3]


def read(p):
    return json.loads(Path(p).read_text())


def ahash(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def distribution(a):
    return np.percentile(a,[5,50,95]).tolist()


def run(out):
    start=time.monotonic()
    def stop(*_):
        raise InterruptedError('finite deadline/signal')
    for sig in (signal.SIGALRM,signal.SIGINT,signal.SIGTERM):signal.signal(sig,stop)
    signal.alarm(600)
    ev.require(out.parent==PARENT.parent and not out.exists(),'fresh isolated output')
    out.mkdir(mode=0o700)
    evidence=read(REPO/'docs/evidence/RML2018A_OFFLINE_BASELINE_2026-09-16.json')
    parent_id=ev.identity(PARENT/'retention.json',evidence['retention']['sha256'])
    retained=read(PARENT/'retention.json')
    for record in retained['files']:ev.identity(record['path'],record['sha256'])
    prior=read(PARENT/'plan.json');rows=read(PARENT/'baseline-rows.json')
    by_id={r['source_row']:r for r in rows}
    with np.load(PARENT/'predictions.npz',allow_pickle=False) as f:old={k:f[k] for k in f.files}
    ids=old['source_row'];y=old['truth'];z=old['source_snr_db']
    val,split=ev.load_validation_split(prior['split']['path'],ev.SEED42_SPLIT_SHA)
    ev.require(len(ids)==2496 and len(set(ids))==2496 and set(by_id)==set(ids) and np.isin(ids,val).all() and ahash(ids)==prior['source_ids_sha256'],'fixed validation membership')
    rr=np.array([by_id[int(i)]['planes']['raw']['received_rms'] for i in ids])
    gr=np.array([by_id[int(i)]['planes']['guard']['received_rms'] for i in ids])
    ev.require(np.isfinite(rr).all() and np.isfinite(gr).all() and (rr>0).all() and (gr>0).all(),'finite RX-only RMS')
    ratio=gr/rr
    collection=read(PARENT/'collection-identity.json');ev.identity(collection['path'],collection['sha256'])
    model_ids=[ev.identity(ev.COLLECTION/f['relative'],f['sha256']) for f in read(collection['path'])['transferred_files']]
    path=ev.CLEAN/'RadioML2018A_RX_guard_1024_per_window_RMS_v1.h5'
    expected=next(r for r in read(PARENT/'input-identities.json') if r['path']==str(path))
    plan=dict(schema='guard-shared-raw-rms-validation-v1',head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        script=ev.identity(__file__),parent_retention=parent_id,split=split,model=prior['model'],input_expected=expected,
        source_ids_sha256=ahash(ids),rows=2496,new_predictions=2496,
        transformation='float32(archived normalized guard * (RX guard pre-RMS / RX raw pre-RMS)); same raw denominator; no source IQ file access or source RMS use',
        reused_comparators=['raw','archived_guard'],precision='FP32, TF32 off, strict original D8 seed42, batch1024',
        acceptance=dict(ids_labels_quality='exact',rms_atol=2e-6,rms_rtol=2e-6,papr_error_max_db=2e-6,finite_logits=True,no_member_drop=True),
        budget=dict(deadline_seconds=600,host_bytes=4*1024**3,gpu_bytes=4*1024**3,output_bytes=64*1024**2,free_bytes=shutil.disk_usage(out).free),
        rf=False,training=False,source_iq_read=False)
    ev.require(plan['budget']['free_bytes']>1024**3,'disk reserve')
    ev.atomic(out/'plan.json',plan)
    input_id=ev.identity(path,expected['sha256'])
    with h5py.File(path,'r') as f:
        source_rows=f['source_row'][:];order=np.argsort(source_rows);at=order[ids]
        ev.require(np.array_equal(source_rows[at],ids),'clean source mapping')
        sort=np.argsort(at);back=np.argsort(sort)
        iq=f['iq'][at[sort]][back]
        metadata={k:f[k][at[sort]][back] for k in ('class_id','source_snr_db','quality_flags','usable','strict_quality_pass','raw_sample_start','raw_sample_count')}
    ev.require(np.array_equal(metadata['class_id'],y) and np.array_equal(metadata['source_snr_db'],z),'labels/SNR')
    ev.require(np.array_equal(metadata['quality_flags'],[by_id[int(i)]['planes']['guard']['quality_flags'] for i in ids]),'quality flags')
    ev.require(np.array_equal(metadata['raw_sample_start'],[by_id[int(i)]['sample_start'] for i in ids]) and (metadata['raw_sample_count']==1024).all(),'raw offsets')
    for k in ('usable','strict_quality_pass'):
        ev.require(np.array_equal(metadata[k],[by_id[int(i)]['planes']['guard'][k] for i in ids]),'quality bool')
    power=np.sum(iq.astype(np.float64)**2,axis=1)
    ev.require(np.allclose(np.sqrt(power.mean(1)),1,atol=2e-6,rtol=0),'parent unit RMS')
    new=np.ascontiguousarray(iq.astype(np.float64)*ratio[:,None,None],dtype=np.float32)
    new_power=np.sum(new.astype(np.float64)**2,axis=1)
    rms=np.sqrt(new_power.mean(1));papr=10*np.log10(new_power.max(1)/new_power.mean(1))
    old_papr=10*np.log10(power.max(1)/power.mean(1))
    ev.require(np.isfinite(new).all() and np.allclose(rms,ratio,atol=2e-6,rtol=2e-6),'shared denominator identity')
    ev.require(np.max(abs(papr-old_papr))<=2e-6,'PAPR unchanged')
    # Independently route through ADC-count reconstruction; exact scalar formula only.
    reconstructed=iq.astype(np.float64)*gr[:,None,None]/rr[:,None,None]
    ev.require(np.allclose(new,reconstructed,atol=2e-6,rtol=2e-6),'equivalent ADC-count formula')
    audit=dict(input=input_id,model_files=model_ids,input_sha256=ahash(new),parent_selected_iq_sha256=ahash(iq),
        rms_ratio_p05_p50_p95=distribution(ratio),rms_max_absolute_error=float(np.max(abs(rms-ratio))),
        papr_max_error_db=float(np.max(abs(papr-old_papr))),metadata_exact=True,guard_skipped=sum(by_id[int(i)]['guard_status']!='applied' for i in ids),
        quality_failed=int((~metadata['strict_quality_pass']).sum()),dropped_rows=0)
    ev.atomic(out/'input-audit.json',audit)
    print(json.dumps(dict(stage='input_verified',seconds=time.monotonic()-start,rms_ratio=audit['rms_ratio_p05_p50_p95'])),flush=True)
    torch=ev.setup(out);model=ev.load_model(prior['model'],torch);logits=[]
    for lo in range(0,len(ids),1024):
        ev.require(not (out/'STOP').exists(),'STOP')
        logits.append(ev.predict(model,new[lo:lo+1024],torch,'fp32'))
    logits=np.concatenate(logits)
    preds=dict(raw=old['raw_logits'].argmax(1),guard=old['archived_guard_logits'].argmax(1),guard_shared_raw_rms=logits.argmax(1))
    def summarize(mask):
        result=dict(rows=int(mask.sum()),correct={k:int(((v==y)&mask).sum()) for k,v in preds.items()},pairs=[],
            rms_ratio_p05_p50_p95=distribution(ratio[mask]))
        for a,b in [('raw','guard'),('raw','guard_shared_raw_rms'),('guard','guard_shared_raw_rms')]:
            ac=preds[a]==y;bc=preds[b]==y
            result['pairs'].append(dict(before=a,after=b,corrected=int((~ac&bc&mask).sum()),regressed=int((ac&~bc&mask).sum()),
                top1_agreement=int(((preds[a]==preds[b])&mask).sum())))
        result['old_raw_to_guard_regressions_rescued']=int(((preds['raw']==y)&(preds['guard']!=y)&(preds['guard_shared_raw_rms']==y)&mask).sum())
        result['old_raw_to_guard_corrections_lost']=int(((preds['raw']!=y)&(preds['guard']==y)&(preds['guard_shared_raw_rms']!=y)&mask).sum())
        return result
    classes=prior['model']['class_order']
    result=dict(overall=summarize(np.ones(len(ids),bool)),am=summarize(np.isin(y,[17,18,19,20])),
        per_class=[dict(label=classes[i],**summarize(y==i)) for i in range(24)],
        per_source_snr=[dict(source_snr_db=int(i),**summarize(z==i)) for i in sorted(set(z))],
        per_cell=[dict(class_id=i,source_snr_db=int(j),**summarize((y==i)&(z==j))) for i in range(24) for j in sorted(set(z))],
        elapsed_seconds=time.monotonic()-start,peak_cuda_bytes=torch.cuda.max_memory_allocated(),peak_host_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        new_predictions=2496,skipped_rows=0,validation_only=True)
    ev.require(result['peak_cuda_bytes']<=4*1024**3 and result['peak_host_rss_bytes']<=4*1024**3,'resource budget')
    np.savez(out/'predictions.npz',source_row=ids,truth=y,validation_rank=np.searchsorted(val,ids),
        logits=logits,raw_received_rms=rr,guard_received_rms=gr,rms_ratio=ratio,input_rms=rms,input_papr_db=papr,**metadata)
    ev.atomic(out/'results.json',result);ev.unchanged(input_id);ev.unchanged(parent_id)
    print(json.dumps(dict(stage='complete',overall=result['overall'],am=result['am'],seconds=result['elapsed_seconds'])),flush=True)
    signal.alarm(0)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    try:run(args.output)
    finally:
        cache=ev.cache_root(args.output)
        if cache.exists():
            files=[p for p in cache.rglob('*') if p.is_file()]
            ev.atomic(args.output/'cache-cleanup.json',dict(path=str(cache),files=len(files),bytes=sum(p.stat().st_size for p in files)))
            shutil.rmtree(cache);ev.require(not cache.exists(),'cache cleanup')
