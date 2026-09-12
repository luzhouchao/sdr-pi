#!/usr/bin/env python3
"""Finite AGX B210 tone/LO attribution using the existing TX and Controller paths."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid

import numpy as np

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import rml2018a_campaign as c

spec = importlib.util.spec_from_file_location('lo_campaign', SCRIPTS/'rml2018a-rf-campaign.py')
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)
TAGS = ('before', 'positive', 'negative', 'half-amplitude', 'positive-repeat', 'after')
GAIN_PAIR_TAGS = ('before', 'baseline1', 'paired1', 'baseline2', 'paired2', 'after')
EXPERIMENTS = {'lo-offset': c.LO_REFERENCE_SCHEMA, 'gain-pair': c.LO_GAIN_PAIR_SCHEMA}


def gain_pair_criteria():
    return dict(maximum_abs_tone_change_db=1., minimum_lo_suppression_db=6.,
        both_pairs_required=True, meaning='Engineering tone mitigation only; no model or modulation-fidelity admission')


def tags_for(schema):
    c.require(schema in EXPERIMENTS.values(), 'registered LO experiment')
    return TAGS if schema == c.LO_REFERENCE_SCHEMA else GAIN_PAIR_TAGS


def software():
    return {name: c.file_hash(SCRIPTS/name) for name in (
        Path(__file__).name, 'rml2018a_campaign.py', 'rml2018a-nx-tx.py',
        'rml2018a-rf-campaign.py', 'validate-p201-termination-background.py',
        'validate-b210-p201-link.py')}


def check_root(root):
    c.require(root.is_absolute() and root.resolve() == root and
        root.parent == Path('/var/tmp/sdrharness-dev') and root.name.startswith('b210-cablelo-') and
        root.name.replace('-', '').isalnum(), 'diagnostic root')


def create_plan(root, experiment='lo-offset'):
    check_root(root)
    c.require(experiment in EXPERIMENTS, 'registered LO experiment')
    schema = EXPERIMENTS[experiment]
    c.require(not root.exists(), 'new diagnostic root required')
    available = shutil.disk_usage(root.parent).free
    c.require(available > 64*1024*1024, 'diagnostic disk reserve')
    generation = time.time_ns()//1000000
    run_id = uuid.uuid4().hex
    points = []
    for index, tag in enumerate(tags_for(schema)):
        gen = generation + index
        rx = dict(sweep_id=f'cablelo-{tag}-{gen}', session_generation=gen,
            frequencies=dict(kind='centers', centers_hz=[c.CENTER]), sample_rate_hz=c.RATE,
            rf_bandwidth_hz=c.BW, gain_db=40, settle_ms=500, frame_samples=c.RX_SAMPLES,
            aggregate_frames=1, point_timeout_ms=1000, detection_threshold_db=12.)
        points.append(dict(tag=tag, rx=rx, tx=None if index in (0,5) else c.lo_reference(run_id,index-1,schema=schema)[0],
            result_path=str(root/tag), agx_staging=str(root.parent/f'{root.name}-tx{index}'),
            p201_staging=f'/tmp/sdr-agent-dev/agx-sweep-{gen}-0'))
    plan = dict(schema=schema, run_id=run_id, software=software(),
        tx_identity=campaign.transport_module().identity('agx'),
        connection='User confirmed B210 RF A TX/RX ->20dB50ohm attenuator +15cm SMA ->P201 RX1',
        points=points, maximum_tx_seconds=16, maximum_tx_samples=sum(p['tx']['tx_samples'] for p in points if p['tx']),
        maximum_rx_bytes=len(points)*c.RX_SAMPLES*4, free_bytes=available, reserve_bytes=64*1024*1024,
        dwell_seconds=c.RX_SAMPLES/c.RATE, expected_wall_seconds=120, deadline_seconds=360,
        rx_deadline_seconds=15, helper_watchdog_seconds=55, maximum_component_peak_counts=512,
        analysis='Prefix Hann peak searches; held-out fixed bands and tone+LO fit; stopped bracketing controls',
        stop='SIGINT/SIGTERM runner; dedicated Controller generation cancel; identified helper INT and finite feed',
        model_windows=0, dataset_rows=0, recognizer_available=False)
    if schema == c.LO_GAIN_PAIR_SCHEMA:
        plan['pair_criteria'] = gain_pair_criteria()
    root.mkdir(mode=0o700)
    c.save(root/'plan.json', plan)
    print(json.dumps(plan), flush=True)


def preflight(bg, transport):
    password = Path('/home/jetson/.config/sdrharness/p201-root.password')
    c.require(password.is_file() and not password.is_symlink() and password.stat().st_mode & 0o777 == 0o600,
        'protected password file')
    with socket.create_connection(('192.168.1.10',43110),timeout=3):
        pass
    bg.idle()
    pid = bg.ssh('pidof sdrd').split()
    c.require(len(pid)==1, 'single sdrd')
    c.require(bg.ssh(f'readlink /proc/{pid[0]}/exe').strip()=='/sd/sdr-agent/current/sdrd', 'daemon executable')
    c.require(sum(':43110 ' in line for line in bg.ssh('netstat -lnt').splitlines())==1, 'single listener')
    bg.ssh('test -f /sd/sdr-agent/current/sdrd.conf && test -f /sd/sdr-agent/current/S60sdrd')
    daemon_hash=bg.ssh('sha256sum /sd/sdr-agent/current/sdrd').split()[0]
    c.require(daemon_hash=='83a661a892b8ab71de3f4e7d64064c9c65030623dc7245eb3d3a1420a696ba4f', 'daemon hash')
    c.require(c.file_hash(bg.BINARY)=='24b8340dd5c56bcf643a44e1eadbd11450e3b5e528d2ec72dc26103e9f23e25f', 'Controller hash')
    before=bg.ssh(bg.STATE)
    state=dict(zip(before.splitlines()[::2],before.splitlines()[1::2]))
    c.require(all(v=='0' for k,v in state.items() if k.endswith(('_en','/enable'))), 'radio idle')
    health=campaign.document_health(bg)
    c.require(health['healthy'] and health['rx_input']['front_panel_port']=='RX1', 'healthy RX1')
    return dict(radio=before, daemon_pid=pid, daemon_sha256=daemon_hash,
        controller_sha256=c.file_hash(bg.BINARY), health=health, b210=transport.preflight())


def capture(root, point, bg, transport, baseline):
    dest=Path(point['result_path']); remote=Path(point['agx_staging']); rxp=point['rx']; txp=point['tx']
    c.require(dest.parent==root and not dest.exists(), 'fresh point')
    c.require(shutil.disk_usage(root).free>32*1024*1024, 'point disk reserve')
    bg.idle(); transport.preflight(); bg.restoration(baseline['radio'])
    bg.ssh('test ! -e '+shlex.quote(point['p201_staging']))
    dest.mkdir(mode=0o700); (dest/'rx').mkdir()
    c.save(dest/'rx-plan.json',rxp)
    audit=dict(status='failed',point=point,started_unix_ns=time.time_ns(),free_bytes=shutil.disk_usage(root).free,
        maximum_rx_bytes=c.RX_SAMPLES*4,restored=False)
    c.save(dest/'audit.json',audit)
    tx=None; rx=None; owner=None; staged=False
    try:
        if txp is not None:
            expected, waveform=c.lo_reference(txp['run_id'],txp['batch'],schema=txp['schema'])
            c.require(txp==expected, 'registered tone case')
            c.save(dest/'tx-plan.json',txp); (dest/'packet.fc32').write_bytes(waveform.tobytes())
            transport.run(f'test ! -e {remote} && mkdir -m 700 {remote}'); staged=True
            transport.put([SCRIPTS/'rml2018a_campaign.py',SCRIPTS/'rml2018a-nx-tx.py',
                dest/'packet.fc32',dest/'tx-plan.json'],remote)
            tx=transport.spawn(f'cd {remote} && export PYTHONDONTWRITEBYTECODE=1 TMPDIR={remote} XDG_CACHE_HOME={remote} '
                f'&& echo OWNER $$ && exec timeout --signal=INT --kill-after=3s 58s python3 -B '
                f'{remote}/rml2018a-nx-tx.py --directory {remote}')
            first=campaign.read_line(tx,10).decode().strip().split()
            c.require(len(first)==2 and first[0]=='OWNER' and first[1].isdigit(), 'TX owner')
            owner=int(first[1]); audit['owner_pid']=owner
            ready=json.loads(campaign.read_line(tx,35)); audit['tx_ready']=ready
            c.require(ready['event']=='ready' and ready['batch']==txp['batch'] and
                ready['payload_sha256']==txp['payload_sha256'], 'TX readiness')
            tx.stdin.write(b'GO\n'); tx.stdin.flush()
            c.require(json.loads(campaign.read_line(tx,3))['event']=='tx_start', 'TX acknowledgement')
        rx=subprocess.Popen([str(bg.BINARY),'--mode','sweep','--sdrd','192.168.1.10:43110',
            '--sigmf-directory',str(dest/'rx')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            out,err=rx.communicate(json.dumps(rxp).encode(),timeout=15)
            (dest/'rx-stderr.log').write_bytes(err)
            c.require(rx.returncode==0, 'RX failed: '+err.decode()[-1000:])
            c.save(dest/'report.json',json.loads(out))
        except BaseException:
            bg.command([bg.BINARY,'--mode','cancel','--sdrd','192.168.1.10:43110',
                '--session-generation',str(rxp['session_generation'])],timeout=6)
            raise
        raw,seal=campaign.native_check(dest,rxp); audit['seal']=seal
        audit['component_peak_counts']=float(max(abs(raw.real).max(),abs(raw.imag).max()))
        audit['component_rms_counts']=float(np.sqrt(np.mean(abs(raw)**2)/2))
        c.require(audit['component_peak_counts']<=512, 'registered component peak gate')
        bg.restoration(baseline['radio'])
        if tx is not None:
            out,err=tx.communicate(timeout=15)
            audit['tx_stdout']=out.decode(); audit['tx_stderr']=err.decode()
            c.require(tx.returncode==0, 'TX helper failure')
            transport.get([remote/'tx-summary.json',remote/'tx-uhd.log'],dest)
            receipt=campaign.document(dest/'tx-summary.json')
            c.require(receipt['status']=='fed_complete' and receipt['bytes_written']==txp['tx_samples']*8
                and receipt['child_stopped'], 'TX completion')
            log=(dest/'tx-uhd.log').read_text()
            for label,wanted in [('Actual TX Rate',2.1),('Actual TX Freq',2455.),('Actual TX Gain',float(txp['tx_gain_db'])),
                ('Actual TX Bandwidth',1.5),('Setting TX LO Offset',txp['lo_offset_hz']/1e6)]:
                values=re.findall(re.escape(label)+r': ([\d.+-]+)',log)
                c.require(len(values)==1 and abs(float(values[0])-wanted)<1e-6, 'UHD readback '+label)
            c.require('LO: locked' in log, 'TX unlocked')
            audit['uhd_tail_markers']=log.split('Done!')[-1].strip()
        audit['status']='captured'
    except BaseException as error:
        audit['error']=f'{type(error).__name__}: {error}'
        raise
    finally:
        try:
            campaign.stop_tx(transport,tx,owner,remote)
        finally:
            if rx is not None and rx.poll() is None:
                rx.terminate()
                try: rx.communicate(timeout=8)
                except subprocess.TimeoutExpired: rx.kill(); rx.communicate(timeout=3)
            try:
                audit['radio_after']=bg.restoration(baseline['radio'])
                c.require(bg.ssh('pidof sdrd').split()==baseline['daemon_pid'], 'same daemon')
                bg.ssh('test ! -e '+shlex.quote(point['p201_staging']))
                if staged:
                    link=campaign.module('lo_link','validate-b210-p201-link.py')
                    transport.run(link.remote_absence_command(remote,owner,audit.get('tx_ready',{}).get('child_pid')))
                    for name in ('tx-summary.json','tx-uhd.log'):
                        if not (dest/name).exists() and transport.run(f'if test -f {remote}/{name}; then echo yes; fi').strip()=='yes':
                            transport.get([remote/name],dest)
                    audit['removed_staging']=campaign.remote_cleanup(transport,remote)
                audit['b210_after']=transport.preflight()
                audit['restored']=True
            finally:
                audit['elapsed_seconds']=(time.time_ns()-audit['started_unix_ns'])/1e9
                c.save(dest/'audit.json',audit)
    if txp:
        c.require(c.file_hash(dest/'packet.fc32')==txp['payload_sha256'], 'source cleanup identity')
        (dest/'packet.fc32').unlink()
        audit['removed_source_bytes']=txp['payload_bytes']; c.save(dest/'audit.json',audit)
    print(json.dumps(dict(event='captured',tag=point['tag'],peak=audit['component_peak_counts'],restored=True)),flush=True)


def acquire(root):
    check_root(root)
    plan=campaign.document(root/'plan.json')
    c.require(plan['schema'] in EXPERIMENTS.values() and plan['software']==software() and
        plan['tx_identity']==campaign.transport_module().identity('agx'), 'sealed software/runtime')
    c.require([p['tag'] for p in plan['points']]==list(tags_for(plan['schema'])), 'fixed point order')
    if plan['schema'] == c.LO_GAIN_PAIR_SCHEMA:
        c.require(plan.get('pair_criteria') == gain_pair_criteria(), 'registered pair criteria')
    for index,point in enumerate(plan['points']):
        c.require(Path(point['result_path'])==root/point['tag'] and
            Path(point['agx_staging'])==root.parent/f'{root.name}-tx{index}', 'point paths')
        c.require(point['tx']==(None if index in (0,5) else c.lo_reference(plan['run_id'],index-1,schema=plan['schema'])[0]), 'TX plan')
        rx=point['rx']
        expected=dict(sweep_id=f'cablelo-{point["tag"]}-{rx["session_generation"]}',session_generation=rx['session_generation'],
            frequencies=dict(kind='centers',centers_hz=[c.CENTER]),sample_rate_hz=c.RATE,rf_bandwidth_hz=c.BW,
            gain_db=40,settle_ms=500,frame_samples=c.RX_SAMPLES,aggregate_frames=1,point_timeout_ms=1000,detection_threshold_db=12.)
        c.require(rx==expected and type(rx['session_generation']) is int and rx['session_generation']>0 and
            point['p201_staging']==f'/tmp/sdr-agent-dev/agx-sweep-{rx["session_generation"]}-0', 'registered RX plan')
    with (root/'started.json').open('x') as stream:
        json.dump(dict(pid=os.getpid(),plan_sha256=c.file_hash(root/'plan.json'),time_ns=time.time_ns()),stream)
    bg=campaign.module('lo_bg','validate-p201-termination-background.py')
    transport=campaign.transport_module().Transport('agx',bg)
    baseline=preflight(bg,transport); c.save(root/'preflight.json',baseline)
    receipt=dict(status='failed',model_windows=0,dataset_rows=0)
    signal.alarm(360)
    try:
        for point in plan['points']:capture(root,point,bg,transport,baseline)
        receipt['status']='completed'
    finally:
        signal.alarm(0)
        for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM):signal.signal(sig,signal.SIG_IGN)
        receipt['radio_restored']=bg.restoration(baseline['radio'])==baseline['radio']
        receipt['after']=preflight(bg,transport)
        c.require(receipt['after']==baseline, 'complete device restoration')
        receipt['temporary_paths_absent']=all(not Path(p['agx_staging']).exists() for p in plan['points'])
        for point in plan['points']:bg.ssh('test ! -e '+shlex.quote(point['p201_staging']))
        c.require(receipt['temporary_paths_absent'], 'AGX staging remains')
        c.save(root/'postflight.json',receipt)


def spectrum(z):
    window=np.hanning(len(z))
    power=abs(np.fft.fft(z*window))**2/(len(z)*np.sum(window**2))
    return np.fft.fftfreq(len(z),1/c.RATE),power


def peak(z, expected, radius):
    frequency,power=spectrum(z)
    indices=np.flatnonzero(abs(frequency-expected)<=radius)
    k=int(indices[np.argmax(power[indices])])
    c.require(k not in (indices[0],indices[-1]), 'spectral peak at search boundary')
    v=np.log(np.maximum(power[[(k-1)%len(z),k,(k+1)%len(z)]],1e-30))
    delta=float(.5*(v[0]-v[2])/(v[0]-2*v[1]+v[2]))
    c.require(abs(delta)<=.5, 'spectral peak interpolation')
    return float(frequency[k]+delta*c.RATE/len(z))


def line_metrics(raw, controls, txp):
    """Frequency estimates use only prefix; report power/error on held-out samples."""
    split=32768
    tone=peak(raw[:split],txp['tone_hz'],17000)
    cfo=tone-txp['tone_hz']
    line=peak(raw[:split],txp['lo_offset_hz']+cfo,1000)
    n=np.arange(len(raw))
    tones=np.column_stack([np.exp(2j*np.pi*f*n/c.RATE) for f in (tone,line)])
    coefficients=np.linalg.lstsq(tones[:split],raw[:split],rcond=None)[0]
    predictions=tones*coefficients
    sl=slice(split,None)
    def power(z):return float(np.mean(abs(z)**2))
    def band(z,f):
        frequency,p=spectrum(z[sl]);return float(p[abs(frequency-f)<=1000].sum())
    desired=band(raw,tone);lo=band(raw,line)
    contrasts={tag:10*np.log10(max(lo,1e-30)/max(band(z,line),1e-30)) for tag,z in controls.items()}
    return dict(tone_hz=tone,cfo_hz=cfo,lo_candidate_hz=line,
        lo_minus_expected_hz=line-(txp['lo_offset_hz']+cfo),
        heldout_tone_power_counts2=desired,heldout_lo_power_counts2=lo,
        tone_to_lo_db=float(10*np.log10(desired/lo)),stopped_lo_contrast_db=contrasts,
        tone_only_error_counts2=power(raw[sl]-predictions[sl,0]),
        tone_and_lo_error_counts2=power(raw[sl]-predictions[sl].sum(axis=1)),
        prefix_samples=split,heldout_samples=len(raw)-split,band_half_width_hz=1000,
        applied_to_model_or_production=False)


def analyze(root):
    plan=campaign.document(root/'plan.json')
    raws={}
    for point in plan['points']:
        dest=root/point['tag'];raw,seal=campaign.native_check(dest,point['rx'])
        audit=campaign.document(dest/'audit.json')
        c.require(audit['status']=='captured' and audit['restored'] and seal==audit['seal'],'sealed capture')
        raws[point['tag']]=raw
    controls={tag:raws[tag] for tag in ('before','after')}
    cases={point['tag']:line_metrics(raws[point['tag']],controls,point['tx'])
        for point in plan['points'] if point['tx']}
    if plan['schema'] == c.LO_GAIN_PAIR_SCHEMA:
        result=dict(schema='b210-cable-lo-gain-pair-audit-v1',plan_sha256=c.file_hash(root/'plan.json'),
            cases=cases,comparison=gain_pair_comparison(cases),model_windows=0,production_changes=0,
            limitation='Paired clean tones only; not modulated payload fidelity, physical SINR or RF timestamp validation')
        c.save(root/'analysis.json',result)
        print(json.dumps(result),flush=True)
        return result
    first=cases['positive'];negative=cases['negative'];half=cases['half-amplitude'];repeat=cases['positive-repeat']
    pairs={}
    for tag,value in (('negative',negative),('half-amplitude',half),('positive-repeat',repeat)):
        pairs[tag]={name:float(10*np.log10(value[key]/first[key])) for name,key in
            (('tone_power_change_db','heldout_tone_power_counts2'),('lo_power_change_db','heldout_lo_power_counts2'))}
    result=dict(schema='b210-cable-lo-attribution-v1',plan_sha256=c.file_hash(root/'plan.json'),cases=cases,
        changes_from_positive=pairs,observed_lo_shift_hz=negative['lo_candidate_hz']-first['lo_candidate_hz'],
        expected_lo_shift_hz=-500000,model_windows=0,production_changes=0,
        limitation='Tone-source attribution; RF tune register calibration, modulation fidelity and physical SINR not established')
    c.save(root/'analysis.json',result)
    print(json.dumps(result),flush=True)
    return result


def gain_pair_comparison(cases):
    limits=gain_pair_criteria()
    pairs=[]
    for index in (1,2):
        a=cases[f'baseline{index}'];b=cases[f'paired{index}']
        signal=float(10*np.log10(b['heldout_tone_power_counts2']/a['heldout_tone_power_counts2']))
        suppression=float(10*np.log10(a['heldout_lo_power_counts2']/b['heldout_lo_power_counts2']))
        pairs.append(dict(pair=index,tone_change_db=signal,lo_suppression_db=suppression,
            tone_to_lo_improvement_db=b['tone_to_lo_db']-a['tone_to_lo_db'],
            passed=bool(abs(signal)<=limits['maximum_abs_tone_change_db'] and suppression>=limits['minimum_lo_suppression_db'])))
    return dict(pairs=pairs,both_pairs_passed=all(p['passed'] for p in pairs),
        maximum_abs_tone_change_db=limits['maximum_abs_tone_change_db'],minimum_lo_suppression_db=limits['minimum_lo_suppression_db'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['plan','acquire','analyze'])
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--experiment',choices=list(EXPERIMENTS),help='Plan creation only; acquisition uses the sealed plan')
    args=parser.parse_args()
    def stop(sig,frame):raise RuntimeError(f'diagnostic stop signal {sig}')
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM):signal.signal(sig,stop)
    if args.command=='plan':create_plan(args.root,args.experiment or 'lo-offset')
    else:
        if args.experiment is not None:parser.error('--experiment is only accepted for plan creation')
        {'acquire':acquire,'analyze':analyze}[args.command](args.root)
