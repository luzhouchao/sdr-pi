"""Timestamped finite backend of rml2018a-rf-campaign; no independent CLI.

The boundary profile exercises ordinary contiguous24 indexing at mixed Y/Z
boundaries. Its allowlist and attempt ceilings do not authorize a full RF run.
"""
import json
import math
from pathlib import Path
import signal
import time

import h5py
import numpy as np
import rml2018a_campaign as c
import rml2018a_event_archive as storage
import rml2018a_campaign_coverage as coverage
import importlib.util

SCRIPTS=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('campaign_event_reuse',SCRIPTS/'rml2018a-event-retest.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
m=r.m
PROFILE='event-boundary-pilot'
TAGS=('source','raw','guard')
SEMANTICS='Finite contiguous24 campaign boundary/resume engineering comparison. Per-row original Y/Z; fixed source/raw/guard with all failures. Conditional source-assisted SINR includes link distortion, not calibrated RF SINR. Clean pilot; single1024 inference, not blind synchronization, production four-window aggregation or independent accuracy.'


ANALYSIS_CHANGES=('rml2018a_campaign_events.py','rml2018a-rf-campaign.py','compare-rml2018a-pilot-timing.py')


def validate_quality(raw,guarded,z,info,synchronized):
    c.validate_receive_quality(raw,z)
    c.require(guarded['rx_sinr_reference_plane']==r.guard.PLANE,'guard reference plane')
    if synchronized:
        c.require(guarded['rx_interference_cancellation']==(r.guard.METHOD if info['status']=='applied' else 'none_skipped'),'guard method')
    # Only adapt the reference-plane field for the shared arithmetic validator;
    # the saved guarded result keeps its actual plane and correction identity.
    c.validate_receive_quality({**guarded,'rx_sinr_reference_plane':raw['rx_sinr_reference_plane']},z)


def analysis_versions(root):
    paths=list(root.glob('analysis-plan-v*.json'))
    expected=[root/f'analysis-plan-v{i}.json' for i in range(1,len(paths)+1)]
    c.require(set(paths)==set(expected),'contiguous analysis revision history')
    return expected


def analysis_fields(root,p,revision):
    validate(root,p,analysis_only=True)
    captures={str(i):capture_complete(root,p,i) for i in c.RML_BOUNDARY_BATCHES}
    c.require(all(captures.values()),'analysis revision requires all finite captures sealed')
    c.require(type(revision) is int and revision>=1,'analysis revision number')
    return dict(schema='rml2018a-boundary-analysis-revision-v1',revision=revision,
        previous_analysis_sha256=c.file_hash(root/f'analysis-plan-v{revision-1}.json') if revision>1 else None,parent_plan_sha256=c.file_hash(root/'run-plan.json'),
        software=r.software(),captures=captures,maximum_new_tx_seconds=0,maximum_new_rx_bytes=0,
        allowed_commands=['infer','summary','verify'],maximum_model_windows=limits()['maximum_model_windows'],
        reason='Correct guard reference-plane validation and use campaign root for bounded Spark isolation; original IQ, DSP, source Y/Z, RF and model unchanged',
        semantics=SEMANTICS)


def register_analysis(root):
    revision=len(analysis_versions(root))+1;path=root/f'analysis-plan-v{revision}.json'
    p=m.document(root/'run-plan.json');value=analysis_fields(root,p,revision);c.save(path,value)
    return dict(status='analysis_planned',sha256=c.file_hash(path),maximum_new_tx_seconds=0)


def verify_analysis(root,p):
    versions=analysis_versions(root);c.require(versions,'analysis revision required')
    c.require(m.document(versions[-1])==analysis_fields(root,p,len(versions)),'analysis revision identity')


def verify_completed(root,p,indices):
    # Exercise the same completed-acquire path under an analysis-only plan.
    # Precheck ALL selected receipts before any call; it cannot create an attempt.
    c.require(all(capture_complete(root,p,i) for i in indices),'read-only completed capture verification')
    before={str(path):c.file_hash(path) for path in root.glob('batch-*/attempt-*/*') if path.is_file()}
    for index in indices:
        acquire_batch(root,p,index)
        prediction_complete(root,p,index)
    after={str(path):c.file_hash(path) for path in root.glob('batch-*/attempt-*/*') if path.is_file()}
    c.require(before==after,'read-only verification changed attempts')
    return dict(status='verified',batches=list(indices),new_tx_attempts=0,new_model_windows=0)


def indices(p):
    return p['execution_limits']['allowed_batch_indices']


def semantics(profile):
    return SEMANTICS if profile==PROFILE else SEMANTICS+' Explicit1-32 batch chunk; bounded lossless event archives, pauses and full failure retention.'


def limits(profile=PROFILE,selected=None):
    if profile=='event-chunk':return storage.budget(selected)
    c.require(profile==PROFILE,'event profile')
    n=len(c.RML_BOUNDARY_BATCHES)
    return dict(allowed_batch_indices=list(c.RML_BOUNDARY_BATCHES),maximum_attempts_per_batch=2,
        maximum_tx_seconds=n*2*4,maximum_tx_samples=n*2*8381952,
        maximum_rx_iq_bytes=n*2*c.RX_SAMPLES*4,maximum_source_rows=n*24,
        maximum_inference_attempts_per_shard=2,maximum_model_windows=n*72*2,
        maximum_warmup_windows=n*2*2,reserve_bytes=256*1024*1024)


def source(run_id,batch,profile=PROFILE):
    c.require(type(batch) is int and batch in c.level_batches(profile),'boundary allowlist')
    rows=c.batch_rows(2555904,batch)
    with h5py.File(m.DATASET,'r') as h:
        iq=h['X'][rows];y=h['Y'][rows];zs=h['Z'][rows].ravel()
    ids=y.argmax(axis=1)
    c.require(np.array_equal(y,np.eye(24)[ids]) and np.isfinite(zs).all(),'one-hot Y / finite Z')
    c.require(ids.tolist()==[x//106496 for x in rows] and
        zs.tolist()==[2*((x%106496)//4096)-20 for x in rows],'per-row boundary membership')
    frame,scales=c.packet(iq,run_id,batch,level_profile=profile)
    tx=c.tx_plan(frame,run_id,batch,rows,60,level_profile=profile);c.validate_tx(tx,frame.tobytes())
    return iq,frame,dict(rows=rows,class_ids=ids.tolist(),source_snr_db=zs.tolist(),
        original_iq_sha256=c.digest(iq.tobytes()),scales=scales.tolist()),tx


def register(root,p):
    p.update(event_identity=r.identity(),event_software=r.software(),event_generation=time.time_ns()//1000000,
        guard_contract=r.guard.contract(),connection=r.fixed_fields()['connection'],semantics=semantics(p['tx_level_profile']),
        scope=f"{len(indices(p))*24} registered chunk rows; up to two attempts each, no full-dataset execution")
    p['event_sources']={str(b):dict(source=source(p['run_id'],b,p['tx_level_profile'])[2],tx=source(p['run_id'],b,p['tx_level_profile'])[3]) for b in indices(p)}
    if 'coverage' in p:
        parents,old=coverage.history(root.parent,root)
    else:
        # Preserve the exact disjoint-only contract of legacy sealed profiles.
        old=set();parents=[]
        for pattern in (coverage.PATTERNS[0],*coverage.PATTERNS[2:]):
            for path in sorted(root.parent.glob(pattern)):
                old.update(coverage.source_rows(path));parents.append(dict(path=str(path),sha256=c.file_hash(path)))
    rows={row for v in p['event_sources'].values() for row in v['source']['rows']}
    c.require(len(rows)==len(indices(p))*24,'unique chunk rows')
    if 'coverage' in p:coverage.authorize(root,p,parents,rows&old)
    else:c.require(not rows&old,'new disjoint boundary rows')
    p['source_disjointness']=dict(parents=parents,previous_unique_rows=len(old),intersection=len(rows&old))
    validate(root,p)


def validate(root,p,analysis_only=False):
    profile=p['tx_level_profile']
    c.require(profile in (PROFILE,'event-chunk') and p['execution_limits']==limits(profile,indices(p)),'finite event limits')
    c.require(not analysis_only or profile==PROFILE,'analysis revisions remain boundary-only')
    c.require(p['rf']==dict(center_hz=c.CENTER,rate_sps=c.RATE,bandwidth_hz=c.BW,tx_gain_db=60,
        rx_gain_db=50,peak=c.packet_peak(profile),tx_lo_offset_hz=250000,settle_ms=500,
        point_deadline_ms=1000,rx_samples=c.RX_SAMPLES),'exact event RF')
    c.require(p['event_identity']==r.identity(),'event runtime changed')
    current=r.software()
    c.require(set(p['event_software'])==set(current),'event software membership')
    for path,sha in p['event_software'].items():
        if analysis_only and Path(path).name in ANALYSIS_CHANGES:
            c.require(c.file_hash(root/'acquisition-software'/Path(path).name)==sha,'archived acquisition software')
        else:c.require(current[path]==sha,'event software changed')
    c.require(p['guard_contract']==r.guard.contract() and p['semantics']==semantics(profile) and
        p['connection']==r.fixed_fields()['connection'],'comparison/connection contract')
    c.require(type(p['event_generation']) is int and p['event_generation']>0,'generation')
    c.require(set(p['event_sources'])=={str(b) for b in indices(p)},'source batches')
    for batch in indices(p):
        _,_,src,tx=source(p['run_id'],batch,profile)
        c.require(p['event_sources'][str(batch)]==dict(source=src,tx=tx),'sealed source X/Y/Z')
    old=set()
    for parent in p['source_disjointness']['parents']:
        path=Path(parent['path']);c.require(c.file_hash(path)==parent['sha256'],'prior evidence changed')
        old.update(coverage.source_rows(path))
    rows={row for v in p['event_sources'].values() for row in v['source']['rows']}
    if 'coverage' in p:coverage.authorize(root,p,p['source_disjointness']['parents'],rows&old)
    else:c.require(not old&rows,'disjointness replay')
    c.require(p['source_disjointness']['intersection']==len(old&rows) and
        len(old)==p['source_disjointness']['previous_unique_rows'],'historical intersection replay')



def batch_dir(root,index):return root/f'batch-{index:07d}'


def attempt_plan(root,p,index,attempt):
    c.require(index in indices(p) and type(attempt) is int and 0<=attempt<2,'finite attempt')
    dest=batch_dir(root,index)/f'attempt-{attempt}'
    gen=p['event_generation']+indices(p).index(index)*2+attempt
    v=p['event_sources'][str(index)];rx=r.rx_plan(f'boundary-{index}',gen)
    point=dict(tag='capture',mode='rml',batch=index,source=v['source'],tx=v['tx'],
        packet_sha256=v['tx']['payload_sha256'],rx=rx,result_path=str(dest/'capture'),
        p201_staging=f'/tmp/sdr-agent-dev/agx-sweep-{gen}-0')
    return dict(schema='rml2018a-event-campaign-attempt-v1',parent_plan_sha256=c.file_hash(root/'run-plan.json'),
        points=[point],binary=p['event_identity']['binary'],source_rows=24,model_windows=0,
        reserve_bytes=p['execution_limits']['reserve_bytes'],deadline_seconds=400,maximum_tx_seconds=4,
        maximum_tx_samples=8381952,maximum_rx_bytes=262140,maximum_log_bytes_per_tx=16000000,
        agx_path=str(dest),p201_path=point['p201_staging'],stop=r.fixed_fields()['stop'])


def event_path(directory,p):
    if p.get('tx_level_profile')=='event-chunk':return storage.verify(directory)
    return directory/'tx-events.jsonl'


def finalize_storage(root,p,index,attempt):
    if p.get('tx_level_profile')=='event-chunk':
        directory=batch_dir(root,index)/f'attempt-{attempt}'/'capture'
        audit=m.document(directory/'audit.json')
        c.require(audit['status']=='captured' and audit['restored'],'archive only completed/restored new acquisition')
        storage.seal(directory);storage.space(root,p['execution_limits'])


def attempt_seal(root,p,index,attempt):
    dest=batch_dir(root,index)/f'attempt-{attempt}';plan=attempt_plan(root,p,index,attempt)
    c.require(m.document(dest/'plan.json')==plan,'attempt plan changed')
    after=m.document(dest/'postflight.json');audit=m.document(dest/'capture/audit.json')
    c.require(after['status']=='completed' and after['restored'] and audit['status']=='captured' and audit['restored'],'captured/restored attempt')
    _,seal=m.native_check(dest/'capture',plan['points'][0]['rx'])
    c.require(seal==audit['seal'] and audit['point']==plan['points'][0] and
        audit['component_peak_counts']<=512,'native attempt association')
    c.require(r.events.parse_events(event_path(dest/'capture',p))==audit['events'] and audit['tx_exit']==0,'TX event seal')
    return dict(attempt=attempt,rows=p['event_sources'][str(index)]['source']['rows'],
        parent_plan_sha256=c.file_hash(root/'run-plan.json'),plan_sha256=c.file_hash(dest/'plan.json'),
        audit_sha256=c.file_hash(dest/'capture/audit.json'),postflight_sha256=c.file_hash(dest/'postflight.json'),seal=seal,
        **({'event_storage_sha256':c.file_hash(dest/'capture/event-storage.json')} if p.get('tx_level_profile')=='event-chunk' else {}))


def capture_complete(root,p,index):
    path=batch_dir(root,index)/'capture-complete.json'
    if not path.exists():return None
    done=m.document(path)
    c.require(m.document(path.parent/'source.json')==p['event_sources'][str(index)]['source'],'completed source receipt changed')
    c.require(done==attempt_seal(root,p,index,done['attempt']),'completed capture changed')
    return done


def acquire_batch(root,p,index,retry_failed=False):
    done=capture_complete(root,p,index)
    if done:
        print(json.dumps(dict(event='capture_skipped',batch=index)),flush=True);return done
    dest=batch_dir(root,index);dest.mkdir(mode=0o700,exist_ok=True)
    src=p['event_sources'][str(index)]['source']
    if (dest/'source.json').exists():c.require(m.document(dest/'source.json')==src,'source receipt changed')
    else:c.save(dest/'source.json',src)
    for attempt in range(p.get('execution_limits',limits())['maximum_attempts_per_batch']):
        run=dest/f'attempt-{attempt}'
        if run.exists():
            c.require(m.document(run/'plan.json')==attempt_plan(root,p,index,attempt),'existing attempt plan')
            after=m.document(run/'postflight.json')
            if after['status']=='completed':
                # Recover a completed acquisition interrupted just before publishing.
                finalize_storage(root,p,index,attempt)
                done=attempt_seal(root,p,index,attempt);c.save(dest/'capture-complete.json',done);return done
            c.require(retry_failed and after.get('restored') is True and
                m.document(run/'capture/audit.json')['restored'] is True,'retry requires recorded restoration and --retry-failed')
            continue
        if p.get('tx_level_profile')=='event-chunk':storage.space(root,p['execution_limits'])
        run.mkdir(mode=0o700);plan=attempt_plan(root,p,index,attempt);c.save(run/'plan.json',plan)
        print(json.dumps(dict(event='event_batch_plan',batch=index,attempt=attempt,**plan)),flush=True)
        def payload(point):
            _,frame,actual,tx=source(p['run_id'],index,p['tx_level_profile'])
            c.require(actual==point['source'] and tx==point['tx'],'source before TX');return frame.tobytes()
        # Shared finite executor masks stop signals during its final restoration.
        # Restore the campaign's handlers AND remaining outer deadline afterwards.
        handlers={s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM)}
        remaining=signal.alarm(0);start=time.monotonic()
        try:r.events.acquire_validated(run,plan,payload)
        finally:
            for sig,handler in handlers.items():signal.signal(sig,handler)
            signal.alarm(max(1,remaining-math.ceil(time.monotonic()-start)) if remaining else 0)
        finalize_storage(root,p,index,attempt)
        done=attempt_seal(root,p,index,attempt);c.save(dest/'capture-complete.json',done);return done
    raise ValueError('finite capture attempt budget exhausted; failed evidence retained')


def prepare(root,p,indices):
    results=[];tensors={}
    for index in indices:
        done=capture_complete(root,p,index);c.require(done is not None,'capture not completed')
        dest=batch_dir(root,index)/f"attempt-{done['attempt']}"/'capture'
        raw,seal=m.native_check(dest,m.document(dest/'rx-plan.json'))
        received,guarded,sync,info,error=r.receive_parts(raw,p['run_id'],index)
        iq,_,src,_=source(p['run_id'],index,p['tx_level_profile']);z=iq[:,:,0]+1j*iq[:,:,1]
        parts=dict(source=z,raw=received,guard=guarded);tensors[index]=parts
        status='sync_failed' if sync is None else 'synchronized';rows=[]
        for k,row in enumerate(src['rows']):
            snr=float(src['source_snr_db'][k]);q=c.receive_quality(status,z[k],None if received is None else received[k],snr)
            gq={**q,'rx_sinr_reference_plane':r.guard.PLANE} if guarded is None else r.guard.quality(z[k],guarded[k],snr,info)
            validate_quality(q,gq,snr,info,sync is not None)
            rows.append(dict(row=row,true_id=src['class_ids'][k],source_snr_db=snr,quality=dict(raw=q,guard=gq),
                inputs={tag:None if values is None else c.digest(c.normalize_window(values[k]).tobytes()) for tag,values in parts.items()}))
        results.append(dict(batch=index,seal=seal,parent_capture_sha256=c.file_hash(batch_dir(root,index)/'capture-complete.json'),
            status=status,sync=sync,sync_error=error,guard_correction=info,rows=rows))
    return dict(schema='rml2018a-event-campaign-comparison-v1',parent_plan_sha256=c.file_hash(root/'run-plan.json'),
        source_rows=len(indices)*24,maximum_model_windows=len(indices)*72,maximum_warmups=2,
        profile_sha256=p['profile_sha256'],label_map_sha256=p['label_map_sha256'],tags=list(TAGS),
        results=results,semantics=p['semantics'],recognizer_available=False),tensors


def prediction_complete(root,p,index):
    dest=batch_dir(root,index);path=dest/'predictions.json'
    if not path.exists():return False
    value=m.document(path);done=capture_complete(root,p,index)
    c.require(done is not None and value['capture_sha256']==c.file_hash(dest/'capture-complete.json'),'prediction capture association')
    shard=Path(value['inference_path'])
    c.require(shard.resolve()==shard and shard.parent.parent==root and shard.parent.name.startswith('inference-') and shard.name in ('attempt-0','attempt-1'),'inference path')
    c.require(c.file_hash(shard/'inference.json')==value['inference_sha256'],'completed inference changed')
    receipt=m.document(shard/'inference.json');report=m.document(shard/'prepared.json')
    c.require(receipt['status']=='completed' and receipt['prepared_sha256']==c.file_hash(shard/'prepared.json'),'completed inference receipt')
    expected=[x for x in receipt['rows'] if x['batch']==index]
    c.require(value['rows']==expected and [x['row'] for x in expected]==done['rows'],'prediction rows')
    current,_=prepare(root,p,[index]);saved=[b for b in report['results'] if b['batch']==index]
    c.require(saved==current['results'],'prediction source/quality replay')
    for row,pred in zip(saved[0]['rows'],expected):
        c.require(row['true_id']==pred['true_id'],'prediction true class')
        for tag in TAGS:
            q=pred['predictions'][tag]
            if row['inputs'][tag] is None:c.require(q is None,'missing input prediction')
            else:c.require(q['input_sha256']==row['inputs'][tag] and len(q['logits'])==24 and
                np.isfinite(q['logits']).all() and int(np.argmax(q['logits']))==q['id'],'prediction replay')
    return True


def infer_batches(root,p,indices):
    # First finish publication from a complete shard, even if the requested
    # pending subset changed after an interruption. No CUDA/model reexecution.
    for receipt in sorted(root.glob('inference-*/attempt-*/inference.json')):
        if m.document(receipt)['status']=='completed':publish(root,p,receipt.parent)
    pending=[i for i in indices if not prediction_complete(root,p,i)]
    if not pending:return
    key=c.digest(json.dumps(pending).encode())[:16];base=root/f'inference-{key}'
    base.mkdir(mode=0o700,exist_ok=True)
    for attempt in range(2):
        out=base/f'attempt-{attempt}'
        if out.exists():
            old=m.document(out/'inference.json');c.require(old['status']=='failed','inference attempt state')
            continue
        prior=[m.document(path) for path in root.glob('inference-*/attempt-*/prepared.json')]
        c.require(all(sum(any(b['batch']==index for b in old['results']) for old in prior)<2 for index in pending),'per-batch inference attempt ceiling across shards')
        out.mkdir(mode=0o700);report,_=prepare(root,p,pending);c.save(out/'prepared.json',report)
        r.compare.infer(root,out,prepare_inputs=lambda _:prepare(root,p,pending),isolation_root=root)
        publish(root,p,out);return
    raise ValueError('finite inference attempt budget exhausted')


def publish(root,p,out):
    report=m.document(out/'prepared.json');indices=[b['batch'] for b in report['results']]
    c.require(len(indices)==len(set(indices)) and set(indices)<=set(p.get('execution_limits',limits())['allowed_batch_indices']),'inference batches')
    r.compare.verify(root,out,prepare_inputs=lambda _:prepare(root,p,indices))
    receipt=m.document(out/'inference.json')
    for index in indices:
        dest=batch_dir(root,index);value=dict(schema='rml2018a-event-campaign-predictions-v1',batch=index,
            capture_sha256=c.file_hash(dest/'capture-complete.json'),inference_path=str(out),
            inference_sha256=c.file_hash(out/'inference.json'),rows=[x for x in receipt['rows'] if x['batch']==index])
        if (dest/'predictions.json').exists():c.require(m.document(dest/'predictions.json')==value,'existing prediction receipt changed')
        else:c.save(dest/'predictions.json',value)


def aggregate(rows):
    result={tag:dict(total=len(rows),predicted=0,correct=0) for tag in TAGS}
    quality={tag:dict(estimated=0,invalid=0,not_measured=0,pending=0) for tag in ('raw','guard')}
    for row in rows:
        for tag in TAGS:
            pred=row['predictions'].get(tag)
            result[tag]['predicted']+=int(pred is not None)
            result[tag]['correct']+=int(pred is not None and pred['id']==row['true_id'])
        for tag in quality:quality[tag][row.get('quality',{}).get(tag,{}).get('rx_sinr_status','pending')]+=1
    def good(row,tag):return row['predictions'].get(tag) is not None and row['predictions'][tag]['id']==row['true_id']
    reasons={tag:{} for tag in ('raw','guard')}
    cross={tag:{status:dict(total=0,correct=0) for status in quality[tag]} for tag in quality}
    for row in rows:
        for tag in quality:
            q=row.get('quality',{}).get(tag,{})
            status=q.get('rx_sinr_status','pending');cross[tag][status]['total']+=1
            cross[tag][status]['correct']+=int(good(row,tag))
            if status!='estimated':
                reason=q.get('rx_sinr_reason','pending');reasons[tag][reason]=reasons[tag].get(reason,0)+1
    return dict(classification=result,quality=quality,quality_reasons=reasons,recognition_by_quality=cross,raw_to_guard=dict(
        corrected=sum(not good(row,'raw') and good(row,'guard') for row in rows),
        regressed=sum(good(row,'raw') and not good(row,'guard') for row in rows)))


def summarize(root,p):
    rows=[];states={};attempts=0;completed=0
    for index in indices(p):
        dest=batch_dir(root,index);src=p['event_sources'][str(index)]['source']
        attempts+=sum((dest/f'attempt-{i}'/'started.json').exists() for i in range(2))
        done=capture_complete(root,p,index);has=prediction_complete(root,p,index)
        state='not_attempted' if not dest.exists() else 'capture_failed_or_pending' if not done else 'inferred' if has else 'inference_pending'
        states[str(index)]=state;completed+=int(done is not None)
        prepared=prepare(root,p,[index])[0]['results'][0]['rows'] if done else None
        pred=m.document(dest/'predictions.json')['rows'] if has else None
        for k,row in enumerate(src['rows']):
            rows.append(dict(row=row,batch=index,true_id=src['class_ids'][k],source_snr_db=src['source_snr_db'][k],
                state=state,quality=prepared[k]['quality'] if prepared else {},predictions=pred[k]['predictions'] if pred else {}))
    result=dict(schema='rml2018a-event-campaign-summary-v1',total_dataset_rows=2555904,
        registered_source_rows=len(rows),capture_attempts=attempts,captured_rows=completed*24,
        not_captured_rows=len(rows)-completed*24,batch_states=states,rows=rows,**aggregate(rows),
        by_source_snr={str(z):aggregate([v for v in rows if v['source_snr_db']==z]) for z in sorted({v['source_snr_db'] for v in rows})},
        by_class={str(cid):aggregate([v for v in rows if v['true_id']==cid]) for cid in sorted({v['true_id'] for v in rows})},
        by_class_source_snr={f'{cid}/{z}':aggregate([v for v in rows if v['true_id']==cid and v['source_snr_db']==z]) for cid,z in sorted({(v['true_id'],v['source_snr_db']) for v in rows})},
        complete=all(s=='inferred' for s in states.values()),whole_dataset_complete=False,
        semantics=p['semantics'],recognizer_available=False)
    c.save(root/'summary.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'}),flush=True);return result


def pause_receipt(root,p,selected,command):
    """A bounded CLI invocation ends here; it never schedules the next chunk."""
    c.require(set(selected)<=set(indices(p)),'pause members')
    usage={**storage.space(root,p['execution_limits']),**storage.retained_usage(root,p['execution_limits'])}
    captures={str(i):capture_complete(root,p,i) for i in selected}
    predictions={str(i):prediction_complete(root,p,i) for i in selected}
    c.require(all(captures.values()),'pause requires restored completed captures')
    if command in ('infer','run'):c.require(all(predictions.values()),'pause requires complete inference')
    key=c.digest(json.dumps(dict(indices=selected,command=command),sort_keys=True).encode())[:16]
    folder=root/'chunks';folder.mkdir(mode=0o700,exist_ok=True);path=folder/f'{key}.json'
    value=dict(schema='rml2018a-finite-chunk-pause-v1',parent_plan_sha256=c.file_hash(root/'run-plan.json'),
        batch_indices=selected,source_rows=[r for i in selected for r in p['event_sources'][str(i)]['source']['rows']],
        command=command,captures=captures,predictions=predictions,automatic_next_chunk=False,
        new_rf_permission=False)
    if path.exists():c.require(m.document(path)==value,'completed chunk changed')
    else:c.save(path,value)
    print(json.dumps(dict(event='chunk_paused',receipt=str(path),registered_batches=len(indices(p)),selected_batches=len(selected),**usage)),flush=True)
    return value
