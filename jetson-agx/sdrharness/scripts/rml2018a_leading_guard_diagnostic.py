#!/usr/bin/env python3
"""Fixed validation ADC ablation: one preceding guard; no RF or training."""
import argparse
from collections import Counter,defaultdict
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
import rml2018a_campaign as c
import rml2018a_guard_tone as guard
import rml2018a_guard_leading as leading
from rml2018a_guard_gpu import GuardBatch
from rml2018a_campaign_gpu import PayloadBatch
from rml2018a_offline_baseline import errors,DSP_NAMES

PARENT=Path('/var/tmp/sdrharness-dev/rml2018a-offline-baseline-20260916')
OUT=Path('/var/tmp/sdrharness-dev/rml2018a-leading-guard-20260916')
S=Path(__file__).resolve().parent


def read(path):return json.loads(Path(path).read_text())
def save(path,value):ev.atomic(path,value)
def ahash(x):return hashlib.sha256(np.ascontiguousarray(x).tobytes()).hexdigest()
def identity(path):
    path=Path(path);st=path.stat();return dict(path=str(path),bytes=st.st_size,mtime_ns=st.st_mtime_ns,sha256=ev.digest(path))
def check():
    ev.require(not (OUT/'STOP').exists(),'STOP requested')
def software():return {str(S/n):ev.digest(S/n) for n in [Path(__file__).name,'rml2018a_guard_leading.py','rml2018a_model_collection_eval.py',*DSP_NAMES]}


def parents():
    pin=read(S.parents[2]/'docs/evidence/RML2018A_OFFLINE_BASELINE_2026-09-16.json')['retention']
    ev.require(ev.digest(PARENT/'retention.json')==pin['sha256'],'parent manifest')
    retained=read(PARENT/'retention.json')['files']
    for name in ['plan.json','baseline-rows.json','predictions.npz','input-identities.json','collection-identity.json']:
        item=next(x for x in retained if Path(x['path']).name==name);ev.require(ev.digest(PARENT/name)==item['sha256'],'parent '+name)
    parent=read(PARENT/'plan.json');rows=sorted(read(PARENT/'baseline-rows.json'),key=lambda r:r['index'])
    with np.load(PARENT/'predictions.npz') as f:
        old={k:f[k] for k in ['source_row','validation_rank','truth','source_snr_db','raw_logits','archived_guard_logits']}
    val,split=ev.load_validation_split(parent['split']['path'],parent['split']['sha256'])
    ids=old['source_row'];ev.require(len(ids)==len(rows)==2496 and np.array_equal(ids,[x['source_row'] for x in rows]),'members')
    ev.require(np.array_equal(val[old['validation_rank']],ids) and len(np.unique(ids))==2496,'original val ranks')
    collection=read(PARENT/'collection-identity.json');ev.require(ev.digest(collection['path'])==collection['sha256'],'collection')
    spec=parent['model'];required={spec['config_relative'],spec['checkpoint']['relative']}
    model_files=[identity(ev.COLLECTION/x['relative']) for x in read(collection['path'])['transferred_files'] if x['relative'] in required or x['relative'].startswith('source/')]
    expected={str(ev.COLLECTION/x['relative']):x['sha256'] for x in read(collection['path'])['transferred_files']}
    ev.require(all(x['sha256']==expected[x['path']] for x in model_files),'model source/config/weight identity')
    return parent,rows,old,model_files


def plan():
    ev.require(not (OUT/'plan.json').exists(),'new plan');parent,rows,old,model_files=parents()
    entries={x['path']:x for x in read(PARENT/'input-identities.json')};paths={x[k] for x in rows for k in ['raw_path','path']}
    inputs=[]
    for path in sorted(paths):
        v=entries[path];st=Path(path).stat();ev.require(st.st_size==v['bytes'] and st.st_mtime_ns==v['mtime_ns'],'parent ADC/H5 metadata')
        inputs.append(dict(**v,full_sha_recomputed=False))
    for frames in {x['frames'] for x in rows}:
        historic=read(Path(frames).parent/'plan.json')
        for name in DSP_NAMES:ev.require(ev.digest(S/name)==historic['software'][str(S/name)],'historical DSP '+name)
    p=dict(schema='leading-guard-fixed-val-v1',head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        software=software(),parent_plan=identity(PARENT/'plan.json'),model=parent['model'],model_files=model_files,
        split=parent['split'],source_ids_sha256=ahash(old['source_row']),rows=2496,inputs=inputs,
        fixed='Archived timing/CFO/phase, historical DSP and single-frame CUDA FP64 fit on both arms, per-window independent RMS, D8 FP32/TF32off/batch1024',
        changed='Add preceding384-point guard; context starts448 instead of256 before pilot, same65535 length; shared future guard interiors unchanged',
        fallback='Keep archived guard on first frame/nonexact preceding spacing or any candidate rejection; retain all2496',
        tolerances=dict(iq_atol=2e-6,iq_rtol=2e-6,logits_atol=2e-4,logits_rtol=2e-4,baseline_top1=1.),
        metrics='Common three future heldout halves and preceding heldout half; absolute payload LO-region +/-10kHz power before RMS; paired accuracy all/class/sourceSNR/AM',
        candidate_review_gate='Overall correct >1341, AM correct >=154, median common holdout candidate/baseline <=1; research evidence only, no production enable',
        budget=dict(deadline_seconds=1800,host_bytes=8*1024**3,gpu_bytes=4*1024**3,output_bytes=128*1024**2,
                    maximum_context_bytes=2496*(65535+192)*4,new_predictions=4992,free_bytes=shutil.disk_usage(OUT).free),
        rf=False,training=False,source_payload_for_fit=False,validation_only=True)
    ev.require(p['budget']['free_bytes']>1024**3,'disk reserve');save(OUT/'plan.json',p);return p


def band_power(z):
    w=np.hanning(1024);f=np.fft.fftfreq(4096,1/c.RATE)
    p=abs(np.fft.fft(z*w,4096))**2/(4096*np.sum(w*w))
    return float(p[abs(f-250000)<=10000].sum())


def prediction(info,n):
    q=info['v1'];return complex(q['amplitude_real'],q['amplitude_imag'])*np.exp(2j*np.pi*q['frequency_hz']*n/c.RATE)


def run():
    start=time.monotonic();p=read(OUT/'plan.json');ev.require(p['software']==software(),'sealed software')
    ev.require(not (OUT/'started.json').exists(),'one run');save(OUT/'started.json',dict(time_ns=time.time_ns()))
    signal.alarm(1800);parent,rows,old,_=parents();ids=old['source_row'];y=old['truth'];z=old['source_snr_db']
    for v in p['inputs']:
        st=Path(v['path']).stat();ev.require(st.st_size==v['bytes'] and st.st_mtime_ns==v['mtime_ns'],'input metadata')
    torch=ev.setup(OUT);payload=PayloadBatch();fitter=GuardBatch(torch)
    saved=np.empty((2496,2,1024),np.float32);baseline=np.empty_like(saved);candidate=np.empty_like(saved)
    frame_cache={};frame_ids={};records=[];groups=defaultdict(list);maximum=dict(raw=0.,guard=0.)
    for row in rows:groups[row['raw_path']].append(row)
    def frame_record(row,index):
        path=Path(row['frames'])/f'{index//64:03d}.json'
        if str(path) not in frame_cache:
            frame_cache[str(path)]=read(path);frame_ids[str(path)]=identity(path)
        return frame_cache[str(path)][index%64]
    for raw_path,group in groups.items():
        frame_cache.clear()
        native=np.memmap(raw_path,dtype='<i2',mode='r').reshape(-1,2)
        h5s={}
        try:
            for row in group:
                check();i=row['index'];fr=row['frame'];a=frame_record(row,fr);at=a['marker_offset'];hz=a['cfo_hz'];phase=a['phase_rotation_rad']
                ev.require(at>=448 and at-256+65535<=len(native),'full before/after ADC context')
                iq=native[at-448:at-256+65535];base_iq=iq[192:]
                ev.require(ahash(base_iq)==row['sync']['context_sha256'],'original ADC context SHA')
                all_z=iq[:,0].astype(float)+1j*iq[:,1].astype(float);raw=all_z[192:];leading_z=all_z[:65535]
                sync=dict(marker_offset=256,payload_marker_offset=256,estimated_cfo_hz=hz)
                fit=fitter.fit([raw],[sync],16)[0];corrected,info=guard.cancel(raw,sync,16,pilot_only=True,frequency_fit=fit)
                ev.require((info['status'],info['reason'])==(a['guard']['status'],a['guard']['reason']) and info['status']=='applied','baseline guard decision')
                previous=frame_record(row,fr-1) if fr else None;spacing=None if previous is None else at-previous['marker_offset']
                fit_new=None
                if fr and spacing==17920:
                    ns=dict(marker_offset=448,payload_marker_offset=448,estimated_cfo_hz=hz)
                    fit_new=fitter.fit([leading_z],[ns],16)[0]
                new_payload,newinfo=leading.cancel(leading_z,hz,frame_index=fr,previous_spacing_samples=spacing,frequency_fit=fit_new)
                pos=at+1024+np.arange(16384);rotation=np.exp(-2j*np.pi*hz*pos/c.RATE+1j*phase)
                old_payload=corrected[1280:17664]*rotation;raw_payload=raw[1280:17664]*rotation
                wi=row['window_in_frame'];base_tensor=payload.normalize(old_payload.reshape(16,1024))[wi]
                raw_tensor=payload.normalize(raw_payload.reshape(16,1024))[wi]
                if row['path'] not in h5s:h5s[row['path']]=h5py.File(row['path'],'r')
                g=h5s[row['path']][f"blocks/{row['block']:03d}"];j=int(np.searchsorted(g['source_row'][:],ids[i]))
                ev.require(int(g['source_row'][j])==ids[i] and int(g['class_id'][j])==y[i] and float(g['source_snr_db'][j])==z[i],'source row/label/SNR')
                ev.require(int(g['raw_sample_start'][j])==row['sample_start']==at+1024+wi*1024,'payload coordinates')
                discrete={plane:bool(g['valid/'+plane][j]) for plane in ('raw','guard')}
                ev.require(all(discrete[plane]==row['planes'][plane]['usable'] for plane in discrete),'quality lineage')
                saved[i]=g['inputs/guard'][j];baseline[i]=base_tensor
                errs={plane:errors(value,g['inputs/'+plane][j],2e-6,2e-6) for plane,value in [('raw',raw_tensor),('guard',base_tensor)]}
                ev.require(all(v['passed'] for v in errs.values()),'baseline ADC input tolerance')
                for plane in errs:maximum[plane]=max(maximum[plane],errs[plane]['max_abs'])
                if new_payload is None:
                    candidate[i]=saved[i];effective=old_payload;proposal=info;shift=-192
                else:
                    effective=new_payload*rotation;candidate[i]=payload.normalize(effective.reshape(16,1024))[wi];proposal=newinfo['proposal'];shift=0
                common=np.concatenate([np.arange(k*17920+192,k*17920+384) for k in (1,2,3)])
                old_error=leading_z[common]-prediction(info,common-192)
                new_error=leading_z[common]-prediction(proposal,common+shift)
                held=dict(common_baseline_power=float(np.mean(abs(old_error)**2)),common_candidate_power=float(np.mean(abs(new_error)**2)))
                if previous and spacing==17920:
                    n=np.arange(192,384);held.update(preceding_baseline_power=float(np.mean(abs(leading_z[n]-prediction(info,n-192))**2)),
                        preceding_candidate_power=float(np.mean(abs(leading_z[n]-prediction(proposal,n+shift))**2)))
                bp=old_payload.reshape(16,1024)[wi];cp=effective.reshape(16,1024)[wi]
                record=dict(**row,previous_spacing_samples=spacing,candidate=newinfo,baseline_replay_errors=errs,
                    original_quality_flags={plane:row['planes'][plane]['quality_flags'] for plane in ('raw','guard')},
                    quality_scope='Historical flags retained; candidate tone/pilot gates reported separately; no new source-assisted SINR',
                    context_with_leading_sha256=ahash(iq),baseline_input_sha256=ahash(base_tensor),candidate_input_sha256=ahash(candidate[i]),
                    candidate_input_rms=float(np.sqrt(np.mean(np.sum(candidate[i].astype(float)**2,axis=0)))),
                    candidate_input_papr_db=float(10*np.log10(np.max(abs(cp)**2)/np.mean(abs(cp)**2))),
                    holdout=held,payload_lo_region_baseline_counts2=band_power(bp),payload_lo_region_candidate_counts2=band_power(cp))
                records.append(record)
                if len(records)%96==0:print(json.dumps(dict(stage='replay',rows=len(records),seconds=time.monotonic()-start)),flush=True)
        finally:
            for f in h5s.values():f.close()
            del native
    records.sort(key=lambda r:r['index']);ev.require(len(records)==2496,'no member drop')
    save(OUT/'rows.json',records);save(OUT/'frame-identities.json',list(frame_ids.values()))
    save(OUT/'input-audit.json',dict(maximum_baseline_iq_error=maximum,rows=2496,source_ids_sha256=ahash(ids),
        baseline_input_sha256=ahash(baseline),candidate_input_sha256=ahash(candidate),historical_quality_retained=True))
    model=ev.load_model(parent['model'],torch)
    current=np.concatenate([ev.predict(model,baseline[k:k+1024],torch,'fp32') for k in range(0,2496,1024)])
    comparison=errors(current,old['archived_guard_logits'],2e-4,2e-4)
    comparison['top1_agreement']=float(np.mean(current.argmax(1)==old['archived_guard_logits'].argmax(1)))
    save(OUT/'baseline-model-check.json',comparison);ev.require(comparison['passed'] and comparison['top1_agreement']==1.,'baseline model reproduction')
    fresh=np.concatenate([ev.predict(model,candidate[k:k+1024],torch,'fp32') for k in range(0,2496,1024)])
    pred=dict(raw=old['raw_logits'].argmax(1),guard=current.argmax(1),leading_guard=fresh.argmax(1))
    applied=np.array([r['candidate']['status']=='applied' for r in records]);common_ratio=np.array([r['holdout']['common_candidate_power']/r['holdout']['common_baseline_power'] for r in records])
    lo_ratio=np.array([r['payload_lo_region_candidate_counts2']/r['payload_lo_region_baseline_counts2'] for r in records])
    def summarize(mask):
        answer=dict(rows=int(mask.sum()),correct={k:int(np.sum((v==y)&mask)) for k,v in pred.items()},pairs=[],applied=int(np.sum(applied&mask)),fallback=int(np.sum(~applied&mask)),
            common_holdout_ratio_p05_p50_p95=np.percentile(common_ratio[mask],[5,50,95]).tolist(),payload_lo_region_ratio_p05_p50_p95=np.percentile(lo_ratio[mask],[5,50,95]).tolist())
        for left,right in [('raw','guard'),('raw','leading_guard'),('guard','leading_guard')]:
            aa=pred[left]==y;bb=pred[right]==y;answer['pairs'].append(dict(before=left,after=right,corrected=int(np.sum(~aa&bb&mask)),regressed=int(np.sum(aa&~bb&mask)),changed_top1=int(np.sum((pred[left]!=pred[right])&mask))))
        return answer
    overall=summarize(np.ones(2496,bool));am=summarize(np.isin(y,[17,18,19,20]))
    result=dict(overall=overall,am=am,per_class=[dict(class_id=k,label=parent['model']['class_order'][k],**summarize(y==k)) for k in range(24)],
        per_source_snr=[dict(source_snr_db=int(k),**summarize(z==k)) for k in sorted(set(z))],
        per_cell=[dict(class_id=k,source_snr_db=int(zz),**summarize((y==k)&(z==zz))) for k in range(24) for zz in sorted(set(z))],
        fallback_reasons=dict(Counter(r['candidate']['reason'] for r in records if r['candidate']['status']!='applied')),
        review_gate_passed=bool(overall['correct']['leading_guard']>1341 and am['correct']['leading_guard']>=154 and np.median(common_ratio)<=1),
        baseline_model=comparison,elapsed_seconds=time.monotonic()-start,peak_cuda_bytes=torch.cuda.max_memory_allocated(),peak_host_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        new_predictions=4992,dropped=0,validation_only=True,production_enabled=False)
    ev.require(result['peak_cuda_bytes']<=4*1024**3 and result['peak_host_rss_bytes']<=8*1024**3,'resource budget')
    np.savez_compressed(OUT/'predictions.npz',source_row=ids,validation_rank=old['validation_rank'],truth=y,source_snr_db=z,
        raw_logits=old['raw_logits'],baseline_logits=current,candidate_logits=fresh,applied=applied,common_holdout_ratio=common_ratio,payload_lo_region_ratio=lo_ratio)
    save(OUT/'results.json',result);signal.alarm(0);print(json.dumps(dict(stage='complete',overall=overall,am=am,seconds=result['elapsed_seconds'])),flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('command',choices=['plan','run']);args=ap.parse_args()
    def stop(sig,frame):raise InterruptedError(f'leading guard stop {sig}')
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM):signal.signal(sig,stop)
    try:
        result={'plan':plan,'run':run}[args.command]()
        if result is not None:print(json.dumps(result))
    finally:
        cache=ev.cache_root(OUT)
        if cache.exists():
            files=[p for p in cache.rglob('*') if p.is_file()];save(OUT/'cache-cleanup.json',dict(path=str(cache),files=len(files),bytes=sum(p.stat().st_size for p in files)))
            shutil.rmtree(cache);ev.require(not cache.exists(),'cache cleanup')
