#!/usr/bin/env python3
"""One finite four-class Z30 retest, timestamped TX and frozen source/raw/guard inference."""
import argparse
import json
from pathlib import Path
import shutil
import signal
import subprocess
import time
import uuid

import h5py
import numpy as np
import rml2018a_campaign as c
import rml2018a_guard_tone as guard
import rml2018a_lo_cancellation as lo
import importlib.util

SCRIPTS=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('retest_events',SCRIPTS/'validate-b210-event-controls.py')
events=importlib.util.module_from_spec(spec);spec.loader.exec_module(events)
m=events.campaign
compare=m.module('retest_compare','compare-rml2018a-pilot-timing.py')
PROFILE='event-retest-pilot'
TAGS=('off-before',*(f'batch-{b:07d}' for b in c.RML_EVENT_BATCHES),'off-after')
BUILD=Path('/var/tmp/sdrharness-dev/b210-event-controls-20260913/build-receipt.json')
DATA_SHA='e3dd0bef66a3426959ee66a1709a8c0a95d4f8395d18aaf6f1214bdbc763bd38'
SEMANTICS='96 new Z30 engineering rows; fixed source/raw/guard, all failures retained. Conditional SINR includes link distortion; not calibrated physical SINR or independent accuracy. No TX/RX sample clock mapping.'


def check_root(root):
    c.require(root.is_absolute() and root.resolve()==root and root.parent==Path('/var/tmp/sdrharness-dev') and
              root.name.startswith('b210-rml-event-retest-') and root.name.replace('-','').isalnum(),'finite retest root')


def software():
    result=events.software()
    for name in set(m.campaign_software())|set(compare.software())|{Path(__file__).name}:
        p=SCRIPTS/name;result[str(p)]=c.file_hash(p)
    p=c.REPO/'devices/b210/transport.py';result[str(p)]=c.file_hash(p)
    return result


def rx_plan(tag,generation):
    return dict(sweep_id=f'retest-{tag}-{generation}',session_generation=generation,
        frequencies=dict(kind='centers',centers_hz=[c.CENTER]),sample_rate_hz=c.RATE,rf_bandwidth_hz=c.BW,
        gain_db=50,settle_ms=500,frame_samples=c.RX_SAMPLES,aggregate_frames=1,
        point_timeout_ms=1000,detection_threshold_db=12.)


def source(run_id,batch,cid):
    rows=c.batch_rows(2555904,batch)
    with h5py.File(m.DATASET,'r') as h:
        iq=h['X'][rows];labels=h['Y'][rows].argmax(axis=1);zs=h['Z'][rows].ravel()
    c.require(iq.shape==(24,1024,2) and np.all(labels==cid) and np.all(zs==30),'new source X/Y/Z membership')
    frame,scales=c.packet(iq,run_id,batch,level_profile=PROFILE)
    tx=c.tx_plan(frame,run_id,batch,rows,60,level_profile=PROFILE);c.validate_tx(tx,frame.tobytes())
    return iq,frame,dict(rows=rows,class_ids=labels.tolist(),source_snr_db=zs.tolist(),
        original_iq_sha256=c.digest(iq.tobytes()),scales=scales.tolist()),tx


def fixed_points(root,run_id,generation):
    points=[]
    for i,tag in enumerate(TAGS):
        point=dict(tag=tag,mode=None if tag.startswith('off-') else 'rml',rx=rx_plan(tag,generation+i),
            result_path=str(root/tag),p201_staging=f'/tmp/sdr-agent-dev/agx-sweep-{generation+i}-0')
        if point['mode']:
            batch=c.RML_EVENT_BATCHES[i-1];cid=c.RML_EVENT_CLASSES[i-1]
            _,_,s,tx=source(run_id,batch,cid)
            point.update(batch=batch,class_id=cid,source=s,tx=tx,packet_sha256=tx['payload_sha256'])
        points.append(point)
    return points


def fixed_fields():
    return dict(schema='rml2018a-event-retest-v1',tx_level_profile=PROFILE,
        connection='B210 RF A TX/RX ->20dB50ohm2W DC-8GHz attenuator+15cm SMA ->P201 RX1',
        rf=dict(center_hz=c.CENTER,rate_sps=c.RATE,bandwidth_hz=c.BW,tx_gain_db=60,rx_gain_db=50,
            tx_lo_offset_hz=250000,peak=c.packet_peak(PROFILE)),
        maximum_tx_seconds=16,maximum_tx_samples=33527808,maximum_rx_bytes=1572840,
        maximum_log_bytes_per_tx=16000000,reserve_bytes=128*1024*1024,deadline_seconds=400,
        point_outer_deadline_seconds=65,rx_deadline_seconds=15,maximum_component_peak_counts=512,
        source_rows=96,model_windows=0,maximum_model_windows=288,maximum_warmups=2,inference_deadline_seconds=650,
        recognizer_available=False,guard_contract=guard.contract(),semantics=SEMANTICS,
        stop='Parent SIGINT/SIGTERM -> Controller generation cancel + identified TX SIGINT; 65s hard outer TX timeout, finite4s TX; full radio/USB restoration. Inference restores idle Spark and GPU lease.')


def identity():
    build=m.document(BUILD);binary=Path(build['binary'])
    c.require(c.file_hash(binary)==build['binary_sha256'] and binary.stat().st_size==build['binary_bytes'] and
        c.file_hash(build['source'])==build['source_sha256'] and
        c.file_hash(build['library']['path'])==build['library']['sha256'],'validated event executable')
    c.require(c.file_hash(m.PROFILE)=='6c1dac991b45e3738e19a6a55a9f3a1b6d3db8510ceef35ee77cdd34e2982dab' and
        c.file_hash(m.LABELS)=='859f74d4776bb58dd5dd54106e168b47f5c4053c5170b13275ed59b15a30bac3','frozen profile and label map')
    return dict(binary=dict(path=str(binary),sha256=build['binary_sha256'],bytes=build['binary_bytes']),
        build_receipt_sha256=c.file_hash(BUILD),tx_identity=m.transport_module().identity('agx'),
        profile_sha256=c.file_hash(m.PROFILE),label_map_sha256=c.file_hash(m.LABELS))


def plan(root):
    check_root(root);c.require(not root.exists(),'new retest only');root.mkdir(mode=0o700)
    print('Checking full original dataset SHA-256 (read-only)...',flush=True)
    c.require(m.DATASET.stat().st_size==21449148312 and c.file_hash(m.DATASET)==DATA_SHA,'full dataset pin')
    run_id=uuid.uuid4().hex;gen=time.time_ns()//1000000
    p=dict(**fixed_fields(),**identity(),software=software(),run_id=run_id,generation=gen,
        base_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=c.REPO,text=True).strip(),
        source=dict(path=str(m.DATASET),bytes=m.DATASET.stat().st_size,mtime_ns=m.DATASET.stat().st_mtime_ns,sha256=DATA_SHA),
        free_bytes=shutil.disk_usage(root).free,points=fixed_points(root,run_id,gen))
    c.require(p['free_bytes']>p['reserve_bytes'],'disk reserve')
    # Earlier RF diagnostics remain immutable. No source row from any previous
    # native campaign source.json may enter this new finite experiment.
    old=set();parents=[]
    for path in sorted(root.parent.glob('b210-rml2018a-*/batch-*/source.json')):
        d=m.document(path);old.update(d['rows']);parents.append(dict(path=str(path),sha256=c.file_hash(path)))
    rows=[r for point in p['points'] if point['mode'] for r in point['source']['rows']]
    c.require(len(set(rows))==96 and not old.intersection(rows),'new disjoint source rows')
    p['source_disjointness']=dict(previous_source_records=parents,previous_unique_rows=len(old),intersection=0)
    validate(root,p);c.save(root/'plan.json',p)
    return dict(status='planned',root=str(root),plan_sha256=c.file_hash(root/'plan.json'),source_rows=96,
        maximum_tx_seconds=16,maximum_rx_bytes=1572840,maximum_model_windows=288,free_bytes=p['free_bytes'])


def validate(root,p):
    check_root(root)
    c.require(all(p.get(k)==v for k,v in fixed_fields().items()),'fixed finite retest settings')
    c.require(all(p.get(k)==v for k,v in identity().items()) and p['software']==software(),'sealed software/runtime')
    c.require(type(p['generation']) is int and p['generation']>0 and len(p['run_id'])==32 and
        all(x in '0123456789abcdef' for x in p['run_id']),'run identity')
    c.require(p['points']==fixed_points(root,p['run_id'],p['generation']),'exact finite points/source/paths')
    stat=m.DATASET.stat()
    c.require(p['source']==dict(path=str(m.DATASET),bytes=stat.st_size,mtime_ns=stat.st_mtime_ns,sha256=DATA_SHA),'source dataset identity')
    c.require(p['free_bytes']>p['reserve_bytes'],'planned disk reserve')
    old=set()
    for parent in p['source_disjointness']['previous_source_records']:
        path=Path(parent['path'])
        c.require(c.file_hash(path)==parent['sha256'],'immutable prior source record')
        old.update(m.document(path)['rows'])
    rows={r for point in p['points'] if point['mode'] for r in point['source']['rows']}
    c.require(len(rows)==96 and not old.intersection(rows) and
        p['source_disjointness']['intersection']==0 and p['source_disjointness']['previous_unique_rows']==len(old),'source disjointness replay')


def acquire(root):
    p=m.document(root/'plan.json');validate(root,p)
    def packet_bytes(point):
        _,frame,s,tx=source(p['run_id'],point['batch'],point['class_id'])
        c.require(s==point['source'] and tx==point['tx'],'source immediately before TX')
        return frame.tobytes()
    return events.acquire_validated(root,p,packet_bytes)


def receive_parts(raw,run_id,batch):
    try:received,sync=c.synchronize(raw,run_id,batch,24)
    except ValueError as error:
        return None,None,None,dict(status='skipped',reason='not_synchronized'),str(error)
    corrected,info=guard.cancel(raw,sync)
    return received,lo.payload(corrected,sync),sync,info,None


def prepare(root):
    p=m.document(root/'plan.json');validate(root,p)
    after=m.document(root/'postflight.json');c.require(after['status']=='completed' and after['restored'],'restored acquisition')
    results=[];tensors={};controls=[]
    for point in p['points']:
        d=Path(point['result_path']);a=m.document(d/'audit.json')
        c.require(a['status']=='captured' and a['restored'],'captured/restored audit')
        raw,seal=m.native_check(d,point['rx']);c.require(seal==a['seal'],'native replay')
        peak=float(max(abs(raw.real).max(),abs(raw.imag).max()))
        c.require(peak==a['component_peak_counts'] and peak<=512,'headroom')
        if not point['mode']:
            blocks=[float(np.mean(abs(raw[k:k+256])**2)) for k in range(0,len(raw)-255,256)]
            controls.append(dict(tag=point['tag'],seal=seal,component_peak_counts=peak,
                power_blocks256=blocks,power_p50_counts2=float(np.median(blocks)),power_max_counts2=max(blocks)))
            continue
        event=events.parse_events(d/'tx-events.jsonl');c.require(event==a['events'] and a['tx_exit']==0,'timestamped TX replay')
        batch=point['batch'];received,guarded,sync,info,error=receive_parts(raw,p['run_id'],batch)
        # Receiver DSP is fixed and does not consume source labels or predictions.
        iq,_,_,_=source(p['run_id'],batch,point['class_id']);src=iq[:,:,0]+1j*iq[:,:,1]
        parts=dict(source=src,raw=received,guard=guarded);tensors[batch]=parts;rows=[]
        status='sync_failed' if sync is None else 'synchronized'
        for k,row in enumerate(point['source']['rows']):
            q=c.receive_quality(status,src[k],None if received is None else received[k],30.)
            c.validate_receive_quality(q,30.)
            gq={**q,'rx_sinr_reference_plane':guard.PLANE} if guarded is None else guard.quality(src[k],guarded[k],30.,info)
            rows.append(dict(row=row,true_id=point['class_id'],source_snr_db=30.,quality=dict(raw=q,guard=gq),
                inputs={tag:None if value is None else c.digest(c.normalize_window(value[k]).tobytes()) for tag,value in parts.items()}))
        summary={}
        for tag in ('raw','guard'):
            vals=[r['quality'][tag]['rx_sinr_db'] for r in rows if r['quality'][tag]['rx_sinr_status']=='estimated']
            summary[tag]=dict(total_rows=24,estimated_rows=len(vals),median_db=float(np.median(vals)) if vals else None,
                min_db=min(vals) if vals else None,max_db=max(vals) if vals else None)
        results.append(dict(batch=batch,class_id=point['class_id'],class_name=m.document(m.LABELS)['classes'][point['class_id']],
            seal=seal,parent_audit_sha256=c.file_hash(d/'audit.json'),status=status,sync=sync,sync_error=error,
            component_peak_counts=peak,guard_correction=info,quality_summary=summary,events=event,rows=rows))
    report=dict(schema='rml2018a-event-retest-comparison-v1',parent=str(root),parent_plan_sha256=c.file_hash(root/'plan.json'),
        run_id=p['run_id'],software=software(),source_rows=96,maximum_model_windows=288,maximum_warmups=2,
        profile_sha256=p['profile_sha256'],label_map_sha256=p['label_map_sha256'],recognizer_available=False,
        tags=['source','raw','guard'],semantics=SEMANTICS,results=results,stopped_controls=controls)
    return report,tensors


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['plan','acquire','prepare','infer','verify'])
    parser.add_argument('--root',type=Path,required=True);args=parser.parse_args();root=args.root;check_root(root)
    def abort(sig,frame):raise RuntimeError(f'finite retest stop {sig}')
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM):signal.signal(sig,abort)
    signal.alarm(650)
    if args.command=='plan':result=plan(root)
    else:
        with m.lock(root):
            if args.command=='acquire':result=acquire(root)
            elif args.command=='prepare':
                c.require(not (root/'prepared.json').exists(),'new prepared record')
                report,_=prepare(root);c.save(root/'prepared.json',report)
                result=[dict(batch=r['batch'],name=r['class_name'],status=r['status'],guard=r['guard_correction']['status'],
                    reason=r['guard_correction'].get('reason'),quality=r['quality_summary']) for r in report['results']]
            elif args.command=='infer':result=compare.infer(root,root,prepare_inputs=prepare)['summary']
            else:result=compare.verify(root,root,prepare_inputs=prepare)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
