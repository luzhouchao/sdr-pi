#!/usr/bin/env python3
"""Fixed TX60 tone repeats with timestamped events; no RML/model access."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import signal
import time
import uuid
import numpy as np

S=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('tone_event_base',S/'validate-b210-event-controls.py')
e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)
c=e.c;lo=e.lo
TAGS=('off-before','tone1','tone2','off-after')
RF=dict(center_hz=2455000000,rate_sps=2100000,bandwidth_hz=1500000,tx_gain_db=60,
        rx_gain_db=40,tx_lo_offset_hz=250000,tone_hz=98437.5,peak=.1*np.sqrt(10))


def waveform():
    # Repeat exactly the historical 1024-point tone, without long-index phase drift.
    _,z=c.lo_reference('0'*32,1,schema=c.LO_GAIN_PAIR_SCHEMA)
    return np.tile(z,26)[:26112].astype('<c8')


def software():
    return {**e.software(),str(Path(__file__).resolve()):c.file_hash(__file__),
            str(S/'rml2018a_event_archive.py'):c.file_hash(S/'rml2018a_event_archive.py')}


def points(root,generation):
    result=[];sha=c.digest(waveform().tobytes())
    for i,tag in enumerate(TAGS):
        gen=generation+i
        rx=dict(sweep_id=f'tone-events-{tag}-{gen}',session_generation=gen,
            frequencies=dict(kind='centers',centers_hz=[RF['center_hz']]),sample_rate_hz=c.RATE,
            rf_bandwidth_hz=c.BW,gain_db=40,settle_ms=500,frame_samples=c.RX_SAMPLES,
            aggregate_frames=1,point_timeout_ms=1000,detection_threshold_db=12.)
        result.append(dict(tag=tag,mode='tone' if i in (1,2) else None,rx=rx,
            result_path=str(root/tag),packet_sha256=sha,
            p201_staging=f'/tmp/sdr-agent-dev/agx-sweep-{gen}-0'))
    return result


def plan(root):
    e.check_root(root);c.require(not (root/'plan.json').exists(),'fresh plan')
    binary=root/'build/tx-events';c.require(binary.is_file(),'built observer required')
    generation=time.time_ns()//1000000
    p=dict(schema='b210-tone-events-v1',run_id=uuid.uuid4().hex,generation=generation,
        software=software(),binary=dict(path=str(binary),bytes=binary.stat().st_size,sha256=c.file_hash(binary)),
        daemon_sha256=lo.FULL_SNR_DAEMON_SHA256,tx_identity=e.campaign.transport_module().identity('agx'),
        rf=RF,points=points(root,generation),source_rows=0,model_windows=0,recognizer_available=False,
        maximum_tx_samples=2*8381952,maximum_tx_seconds=8,maximum_rx_bytes=4*65535*4,
        maximum_log_bytes_per_tx=16000000,maximum_component_peak_counts=512,
        reserve_bytes=128*1024*1024,free_bytes=shutil.disk_usage(root).free,deadline_seconds=400,
        connection='B210 RF A TX/RX ->20dB attenuator +15cm coax ->P201 RX1',
        stop='Runner INT/TERM -> generation cancel, TX INT; outer TX timeout65s, finite4s feed',
        criteria='All four captures retained; exact send accounting, RF readback, restoration; report all async events by device time, missing time stays unknown',
        limitation='New buffered/timed/EOB sender differs from prior FIFO helper; cannot retrospectively time old U/S; P201 sample clock not mapped')
    c.require(p['free_bytes']>p['reserve_bytes'],'disk reserve');c.save(root/'plan.json',p);return p


def validate(root,p):
    e.check_root(root)
    c.require(p['schema']=='b210-tone-events-v1' and p['software']==software(),'sealed software')
    c.require(p['rf']==RF and p['source_rows']==p['model_windows']==0,'fixed RF and no dataset/model')
    c.require(type(p['generation']) is int and p['generation']>0 and p['points']==points(root,p['generation']),'fixed points')
    c.require(p['daemon_sha256']==lo.FULL_SNR_DAEMON_SHA256,'pinned deployed daemon')
    c.require(p['tx_identity']==e.campaign.transport_module().identity('agx'),'sealed runtime')
    binary=root/'build/tx-events'
    c.require(p['binary']==dict(path=str(binary),bytes=binary.stat().st_size,sha256=c.file_hash(binary)),'sealed binary')
    for k,v in dict(maximum_tx_samples=16763904,maximum_tx_seconds=8,maximum_rx_bytes=1048560,
                    maximum_log_bytes_per_tx=16000000,maximum_component_peak_counts=512,
                    reserve_bytes=128*1024*1024,deadline_seconds=400).items():
        c.require(p[k]==v,'fixed budget '+k)


def acquire(root):
    p=e.campaign.document(root/'plan.json');validate(root,p)
    return e.acquire_validated(root,p,lambda point:waveform().tobytes())


def event_phases(events,start,end):
    result=[]
    for event in events:
        t=event['device_seconds']
        phase='unknown' if t is None else 'before_start' if t<start else 'within_nominal_burst' if t<end else 'at_or_after_nominal_end'
        result.append(dict(**event,phase=phase,seconds_from_nominal_end=None if t is None else t-end))
    return result


def analyze(root):
    p=e.campaign.document(root/'plan.json');raws={};audits={};result=[]
    for point in p['points']:
        d=root/point['tag'];a=e.campaign.document(d/'audit.json');z,seal=e.campaign.native_check(d,point['rx'])
        c.require(a['status']=='captured' and a['restored'] and a['seal']==seal,'retained capture/restoration')
        raws[point['tag']]=z;audits[point['tag']]=a
    controls={key:raws[key] for key in ('off-before','off-after')}
    for tag in ('tone1','tone2'):
        d=root/tag;events=e.parse_events(d/'tx-events.jsonl');a=audits[tag]
        c.require(events==a['events'],'event replay')
        records=[json.loads(line) for line in (d/'tx-events.jsonl').read_text().splitlines()]
        configs=[x for x in records if x['kind']=='configuration'];ends=[x for x in records if x['kind']=='eob']
        c.require(len(configs)==len(ends)==1,'configuration and EOB')
        config=configs[0];end=ends[0]
        c.require(abs(config['actual_rf_freq_hz']-2455250000)<1 and abs(config['actual_dsp_freq_hz']+250000)<1,'RF/DSP readback')
        c.require(config['gain_db']==60 and config['bandwidth_hz']==1500000 and abs(config['rate_sps']-2100000)<1,'fixed actual RF')
        nominal_end=events['scheduled_device_seconds']+events['summary']['accepted_samples']/config['rate_sps']
        c.require(abs(end['nominal_end_device_seconds']-nominal_end)<1e-9 and end['host_before_ns']<=end['host_after_ns'],'EOB accounting')
        metrics=lo.line_metrics(raws[tag],controls,dict(tone_hz=RF['tone_hz'],lo_offset_hz=250000))
        result.append(dict(tag=tag,configuration=config,eob=end,event_counts=events['event_counts'],
            events=event_phases(events['events'],events['scheduled_device_seconds'],nominal_end),
            accepted_samples=events['summary']['accepted_samples'],clock_brackets=events['clock_brackets'],
            rx_host_bracket=[a['rx_launch_mono_ns'],a['rx_return_mono_ns']],metrics=metrics))
    answer=dict(schema='b210-tone-events-analysis-v1',plan_sha256=c.file_hash(root/'plan.json'),results=result,
        limitation=p['limitation'],all_async_events_retained=True,model_windows=0)
    c.save(root/'analysis.json',answer);return answer


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('command',choices=['plan','acquire','analyze']);ap.add_argument('--root',type=Path,required=True);args=ap.parse_args()
    def stop(sig,frame):raise RuntimeError(f'tone event stop {sig}')
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM):signal.signal(sig,stop)
    value={'plan':plan,'acquire':acquire,'analyze':analyze}[args.command](args.root)
    if value is not None:print(json.dumps(value,indent=2))
