#!/usr/bin/env python3
"""Finite zero/known/stopped controls with UHD events; no dataset or model access."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid
import numpy as np
import rml2018a_campaign as c
import rml2018a_guard_tone as guard

SCRIPTS=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('event_lo',SCRIPTS/'validate-b210-cable-lo.py')
lo=importlib.util.module_from_spec(spec);spec.loader.exec_module(lo)
campaign=lo.campaign
TAGS=('off-before','cancel-zero','zero1','known1','known2','zero2','off-after')
EVENTS={1:'burst_ack',2:'underflow',4:'sequence_error',8:'late_packet',16:'underflow_in_packet',32:'sequence_error_in_burst',64:'user_payload'}


def waveform(mode,run_id):
    c.require(mode in ('zero','known'),'fixed source mode')
    if mode=='zero':return np.zeros(26112,dtype='<c8')
    rng=np.random.default_rng(20260913)
    bits=rng.integers(0,2,(6144,2))*2-1
    payload=np.repeat((bits[:,0]+1j*bits[:,1])/np.sqrt(2)*(.2*np.sqrt(10)),4)
    return np.concatenate((np.zeros(256),c.marker(run_id,0)*np.sqrt(10),payload,np.zeros(256))).astype('<c8')


def software():
    result={str(SCRIPTS/n):c.file_hash(SCRIPTS/n) for n in (Path(__file__).name,'rml2018a_campaign.py','rml2018a_guard_tone.py','rml2018a_lo_cancellation.py','validate-b210-cable-lo.py','rml2018a-rf-campaign.py','validate-p201-termination-background.py')}
    p=c.REPO/'devices/b210/tx-events.cpp';result[str(p)]=c.file_hash(p)
    return result


def check_root(root):
    c.require(root.is_absolute() and root.resolve()==root and root.parent==Path('/var/tmp/sdrharness-dev') and
              root.name.startswith('b210-event-controls-') and root.name.replace('-','').isalnum(),'event root')


def plan(root):
    check_root(root);c.require(not (root/'plan.json').exists(),'new plan')
    binary=root/'build/tx-events';c.require(binary.is_file(),'built observer required')
    run_id=uuid.uuid4().hex;generation=time.time_ns()//1000000
    points=[]
    for i,tag in enumerate(TAGS):
        rx=None if tag=='cancel-zero' else dict(sweep_id=f'events-{tag}-{generation+i}',session_generation=generation+i,
          frequencies=dict(kind='centers',centers_hz=[c.CENTER]),sample_rate_hz=c.RATE,rf_bandwidth_hz=c.BW,
          gain_db=50,settle_ms=500,frame_samples=c.RX_SAMPLES,aggregate_frames=1,point_timeout_ms=1000,detection_threshold_db=12.)
        mode=None if tag.startswith('off-') else 'zero' if 'zero' in tag else 'known'
        points.append(dict(tag=tag,mode=mode,rx=rx,result_path=str(root/tag),p201_staging=None if rx is None else f'/tmp/sdr-agent-dev/agx-sweep-{generation+i}-0'))
    p=dict(schema='b210-event-controls-v1',base_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=c.REPO,text=True).strip(),run_id=run_id,
      software=software(),binary=dict(path=str(binary),bytes=binary.stat().st_size,sha256=c.file_hash(binary)),tx_identity=campaign.transport_module().identity('agx'),
      connection='B210 RF A TX/RX ->20dB50ohm2W DC-8GHz attenuator+15cm SMA ->P201 RX1',
      rf=dict(center_hz=c.CENTER,rate_sps=c.RATE,bandwidth_hz=c.BW,tx_gain_db=60,rx_gain_db=50,tx_lo_offset_hz=250000,peak=.2*np.sqrt(10)),
      waveforms={m:dict(bytes=26112*8,sha256=c.digest(waveform(m,run_id).tobytes())) for m in ('zero','known')},points=points,
      maximum_tx_seconds=20,maximum_tx_samples=26112*321*5,maximum_rx_bytes=6*c.RX_SAMPLES*4,maximum_log_bytes_per_tx=16000000,
      reserve_bytes=128*1024*1024,free_bytes=shutil.disk_usage(root).free,deadline_seconds=400,point_outer_deadline_seconds=65,rx_deadline_seconds=15,
      maximum_component_peak_counts=512,source_rows=0,model_windows=0,recognizer_available=False,
      timestamp_semantics='AGX monotonic/unix receipt times plus UHD device time when supplied; P201 native start timestamp unavailable; no exact TX/RX sample mapping',
      stop='parent SIGINT/SIGTERM -> Controller generation cancel and identified TX SIGINT; hard timeout65s; finite4s source even without receiver',
      criteria='Six captures plus one active cancellation; retain all failures/events; descriptive power and guard residual only; no SINR/model/gate changes')
    c.require(p['free_bytes']>p['reserve_bytes'],'disk reserve');c.save(root/'plan.json',p);return p


def validate_plan(root,p):
    check_root(root)
    c.require(p['schema']=='b210-event-controls-v1' and p['software']==software(),'sealed diagnostic software')
    c.require(p['binary']['path']==str(root/'build/tx-events') and c.file_hash(root/'build/tx-events')==p['binary']['sha256'],'sealed binary')
    c.require(p['tx_identity']==campaign.transport_module().identity('agx'),'sealed runtime')
    c.require(p['rf']==dict(center_hz=c.CENTER,rate_sps=c.RATE,bandwidth_hz=c.BW,tx_gain_db=60,rx_gain_db=50,tx_lo_offset_hz=250000,peak=.2*np.sqrt(10)),'fixed RF')
    c.require([v['tag'] for v in p['points']]==list(TAGS),'finite point order')
    c.require(p['maximum_tx_seconds']==20 and p['maximum_tx_samples']==41909760 and p['maximum_rx_bytes']==1572840,'finite budget')
    for i,point in enumerate(p['points']):
        tag=point['tag'];mode=None if tag.startswith('off-') else 'zero' if 'zero' in tag else 'known'
        c.require(point['mode']==mode and point['result_path']==str(root/tag),'point identity')
        if point['rx'] is not None:
            rx=point['rx'];gen=rx['session_generation']
            expected=dict(sweep_id=f'events-{tag}-{gen}',session_generation=gen,frequencies=dict(kind='centers',centers_hz=[c.CENTER]),sample_rate_hz=c.RATE,rf_bandwidth_hz=c.BW,gain_db=50,settle_ms=500,frame_samples=c.RX_SAMPLES,aggregate_frames=1,point_timeout_ms=1000,detection_threshold_db=12.)
            c.require(rx==expected and type(gen) is int and gen>0 and point['p201_staging']==f'/tmp/sdr-agent-dev/agx-sweep-{gen}-0','fixed RX')
        c.require((point['rx'] is None)==(tag=='cancel-zero'),'RX presence')
    for m in ('zero','known'):c.require(p['waveforms'][m]==dict(bytes=208896,sha256=c.digest(waveform(m,p['run_id']).tobytes())),'fixed waveform')


def parse_events(path,complete=True):
    c.require(path.stat().st_size<16000000,'event byte bound')
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    c.require(len(rows)<40010 and rows[-1]['kind']=='summary','bounded final summary')
    sends=[r for r in rows if r['kind']=='send'];events=[r for r in rows if r['kind']=='async'];offset=0
    for r in sends:
        c.require(r['offset_samples']==offset and 0<=r['accepted']<=r['requested']<=1024 and r['requested']>0 and
          r['host_before_ns']<=r['host_after_ns'] and r['start_of_burst']==(offset==0),'send accounting/timestamps')
        offset+=r['accepted']
    last=rows[-1];c.require(last['accepted_samples']==offset<=8381952 and last['send_records']==len(sends) and last['async_records']==len(events),'event summary counts')
    if complete:c.require(last['status']=='sent_complete' and offset==8381952,'finite send completion')
    else:c.require(last['status']=='failed' and 'cancel' in last['error'].lower(),'active cancellation receipt')
    c.require(sum(r['kind']=='go' for r in rows)==1 and sum(r['kind']=='summary' for r in rows)==1,'unique GO/summary')
    go=next(r for r in rows if r['kind']=='go');anchors=[r for r in rows if r['kind']=='clock_bracket']
    described=[]
    for r in events:
        c.require(r['channel']==0 and isinstance(r['has_device_time'],bool) and
          ((r['device_seconds'] is not None)==r['has_device_time']),'event timestamp presence')
        described.append(dict(**r,name=EVENTS.get(r['event_code'],'unrecognized_event_code'),
          nominal_sample_from_scheduled_start=None if not r['has_device_time'] else (r['device_seconds']-go['scheduled_device_seconds'])*c.RATE))
    return dict(summary=last,event_counts={str(k):sum(e['event_code']==k for e in events) for k in sorted(set(e['event_code'] for e in events))},
      events=described,clock_brackets=anchors,scheduled_device_seconds=go['scheduled_device_seconds'],
      host_send_span_ns=None if not sends else [sends[0]['host_before_ns'],sends[-1]['host_after_ns']],
      sample_index_semantics='Nominal TX schedule index only, may be outside burst; not P201 capture index, especially after discontinuity')


def acquire(root):
    p=campaign.document(root/'plan.json');validate_plan(root,p)
    return acquire_validated(root,p,lambda point:waveform(point['mode'],p['run_id']).tobytes())


def acquire_validated(root,p,packet_bytes):
    """Internal executor: callers must validate their own fixed finite plan first."""
    bg=campaign.module('event_bg','validate-p201-termination-background.py');tr=campaign.transport_module().Transport('agx',bg)
    with (root/'started.json').open('x') as f:json.dump(dict(pid=os.getpid(),started_ns=time.time_ns(),plan_sha256=c.file_hash(root/'plan.json')),f)
    baseline=lo.preflight(bg,tr);c.save(root/'preflight.json',baseline)
    result=dict(status='failed',source_rows=p['source_rows'],model_windows=0)
    signal.alarm(400)
    try:
        for point in p['points']:
            dest=Path(point['result_path']);c.require(not dest.exists(),'fresh point');dest.mkdir(mode=0o700)
            bg.idle();tr.preflight();bg.restoration(baseline['radio'])
            c.require(shutil.disk_usage(root).free>p['reserve_bytes'],'point space')
            if point['p201_staging']:bg.ssh('test ! -e '+shlex.quote(point['p201_staging']))
            audit=dict(point=point,status='failed',host_start_unix_ns=time.time_ns(),host_start_mono_ns=time.monotonic_ns(),free_bytes=shutil.disk_usage(root).free,restored=False)
            c.save(dest/'audit.json',audit);tx=None;rx=None;log=None
            try:
                if point['mode']:
                    packet=dest/'packet.fc32';packet.write_bytes(packet_bytes(point))
                    c.require(c.file_hash(packet)==(point['packet_sha256'] if 'packet_sha256' in point else p['waveforms'][point['mode']]['sha256']),'staged source')
                    log=(dest/'tx-uhd.log').open('wb')
                    tx=subprocess.Popen(['timeout','--signal=INT','--kill-after=3s','65s',p['binary']['path'],str(packet),str(dest/'tx-events.jsonl')],env=tr.env(),cwd=dest,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log)
                    ready=json.loads(campaign.read_line(tx,35));c.require(ready['event']=='ready','observer ready');audit['tx_ready']=ready
                    tx.stdin.write(b'GO\n');tx.stdin.flush();ack=json.loads(campaign.read_line(tx,3));c.require(ack['event']=='tx_start','observer GO');audit['tx_start']=ack
                    if point['tag']=='cancel-zero':
                        time.sleep(.25);audit['cancel_mono_ns']=time.monotonic_ns();os.kill(ready['pid'],signal.SIGINT)
                if point['rx']:
                    (dest/'rx').mkdir();c.save(dest/'rx-plan.json',point['rx'])
                    audit['rx_launch_mono_ns']=time.monotonic_ns()
                    rx=subprocess.Popen([str(bg.BINARY),'--mode','sweep','--sdrd','192.168.1.10:43110','--sigmf-directory',str(dest/'rx')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                    stdout,stderr=rx.communicate(json.dumps(point['rx']).encode(),timeout=15);audit['rx_return_mono_ns']=time.monotonic_ns();(dest/'rx-stderr.log').write_bytes(stderr)
                    c.require(rx.returncode==0,'RX return');c.save(dest/'report.json',json.loads(stdout))
                    raw,seal=campaign.native_check(dest,point['rx']);audit['seal']=seal;audit['component_peak_counts']=float(max(abs(raw.real).max(),abs(raw.imag).max()))
                    c.require(audit['component_peak_counts']<=512,'component peak gate')
                if tx:
                    rest,_=tx.communicate(timeout=12);audit['tx_stdout_tail']=rest.decode();audit['tx_exit']=tx.returncode
                    c.require(tx.returncode==(1 if point['tag']=='cancel-zero' else 0),'observer exit')
                    audit['events']=parse_events(dest/'tx-events.jsonl',complete=point['tag']!='cancel-zero')
                audit['status']='cancel_verified' if point['tag']=='cancel-zero' else 'captured'
            except BaseException as e:
                audit['error']=f'{type(e).__name__}: {e}';raise
            finally:
                if rx is not None and rx.poll() is None:
                    try:bg.command([bg.BINARY,'--mode','cancel','--sdrd','192.168.1.10:43110','--session-generation',str(point['rx']['session_generation'])],timeout=6)
                    finally:
                        rx.terminate()
                        try:rx.communicate(timeout=8)
                        except subprocess.TimeoutExpired:rx.kill();rx.communicate(timeout=3)
                if tx is not None and tx.poll() is None:
                    tx.send_signal(signal.SIGINT)
                    try:tx.communicate(timeout=4)
                    except subprocess.TimeoutExpired:tx.kill();tx.communicate(timeout=3)
                if log:log.close()
                try:
                    audit['radio_after']=bg.restoration(baseline['radio']);audit['b210_after']=tr.preflight()
                    c.require(bg.ssh('pidof sdrd').split()==baseline['daemon_pid'],'single unchanged daemon')
                    if point['p201_staging']:bg.ssh('test ! -e '+shlex.quote(point['p201_staging']))
                    packet=dest/'packet.fc32'
                    if packet.exists():
                        c.require(c.file_hash(packet)==(point['packet_sha256'] if 'packet_sha256' in point else p['waveforms'][point['mode']]['sha256']),'source removal hash');audit['removed_packet_bytes']=packet.stat().st_size;packet.unlink()
                    audit['restored']=True
                finally:c.save(dest/'audit.json',audit)
            print(json.dumps(dict(tag=point['tag'],status=audit['status'],peak=audit.get('component_peak_counts'),events=audit.get('events',{}).get('event_counts'),restored=audit['restored'])),flush=True)
        result['status']='completed'
    finally:
        signal.alarm(0)
        for s in (signal.SIGINT,signal.SIGTERM):signal.signal(s,signal.SIG_IGN)
        result['after']=lo.preflight(bg,tr);result['restored']=result['after']==baseline;c.save(root/'postflight.json',result)
        c.require(result['restored'],'complete restoration')


def analyze(root):
    p=campaign.document(root/'plan.json');results=[]
    for point in p['points']:
        d=Path(point['result_path']);a=campaign.document(d/'audit.json');c.require(a['restored'],'restored point')
        result=dict(tag=point['tag'],status=a['status'],events=None)
        if point['mode']:
            result['events']=parse_events(d/'tx-events.jsonl',complete=point['tag']!='cancel-zero');c.require(result['events']==a['events'],'event replay')
        if point['rx']:
            raw,seal=campaign.native_check(d,point['rx']);c.require(seal==a['seal'],'native seal replay');n=np.arange(len(raw))
            frequency,power=lo.spectrum(raw[:32768]);indices=np.flatnonzero(abs(frequency-250000)<=17000);f=float(frequency[indices[np.argmax(power[indices])]])
            carrier=np.exp(2j*np.pi*f*n/c.RATE);amp=np.mean(raw[:32768]/carrier[:32768]);residual=raw-amp*carrier
            blocks=[float(np.mean(abs(residual[k:k+256])**2)) for k in range(0,len(raw)-255,256)]
            result.update(seal=seal,component_peak_counts=a['component_peak_counts'],raw_power_counts2=float(np.mean(abs(raw)**2)),candidate_lo_hz=f,
              candidate_tone_power_counts2=float(abs(amp)**2),candidate_residual_blocks256=blocks,
              residual_power_p50_counts2=float(np.median(blocks)),residual_power_max_counts2=max(blocks),
              frequency_fit='prefix32768 FFT bin peak within250kHz+-17kHz; descriptive, no signal-presence or SINR claim',
              rx_host_bracket=[a['rx_launch_mono_ns'],a['rx_return_mono_ns']])
            if point['mode']=='known':
                try:
                    _,sync=c.synchronize(raw,p['run_id'],0,24);_,g=guard.cancel(raw,sync);result.update(sync=sync,guard=g)
                except ValueError as e:result['sync_error']=str(e)
        results.append(result)
    result=dict(schema='b210-event-controls-analysis-v1',plan_sha256=c.file_hash(root/'plan.json'),results=results,
      source_rows=0,model_windows=0,rf_timestamp_continuity_verified=False,
      limitation='TX async device timestamps are optional; P201 capture sample start is not clock-mapped. Zero/stopped residual can include LO; known payload energy is not background.')
    target=root/'analysis.json'
    if target.exists():c.require(result==campaign.document(target),'numeric replay')
    else:c.save(target,result)
    return result


if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('command',choices=['plan','acquire','analyze']);a.add_argument('--root',type=Path,required=True);args=a.parse_args()
    def abort(sig,frame):raise RuntimeError(f'event control stop {sig}')
    for s in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM):signal.signal(s,abort)
    value={'plan':plan,'acquire':acquire,'analyze':analyze}[args.command](args.root)
    if args.command!='acquire':print(json.dumps(value,indent=2))
