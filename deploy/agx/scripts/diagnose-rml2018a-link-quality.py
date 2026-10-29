#!/usr/bin/env python3
"""Bounded TX-off background check and sealed-IQ link diagnosis; no model/TX."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time

import h5py
import numpy as np
import rml2018a_campaign as c

SCRIPTS=Path(__file__).resolve().parent
BACKGROUND=Path('/var/tmp/sdrharness-dev/rml-link-background-20260911')
SURVEY=Path('/var/tmp/sdrharness-dev/rml-band-survey-20260911')
SURVEY_CONFIRM=Path(str(SURVEY)+'-confirm')
SURVEY_CENTERS=(2405000000,2415000000,2425000000,2435000000,2440000000,2455000000,2465000000,2478000000)


def module(name,file):
    spec=importlib.util.spec_from_file_location(name,SCRIPTS/file)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def capture(gain, *, root=None, centers=None, survey_contract=None):
    c.require(gain in (40,50),'registered background gain')
    survey=root is not None
    if survey:
        c.require(gain==40 and root in (SURVEY,SURVEY_CONFIRM),'registered survey root/gain')
        expected=list(SURVEY_CENTERS+SURVEY_CENTERS[::-1]+SURVEY_CENTERS)
        if root==SURVEY:c.require(centers==expected,'registered discovery schedule')
        else:
            candidate=json.loads((SURVEY/'selection.json').read_text())['candidate_hz']
            c.require(centers==[c.CENTER,candidate,candidate,c.CENTER,c.CENTER,candidate],'registered confirmation schedule')
    else:
        c.require(centers is None,'registered default centers')
        root=BACKGROUND if gain==50 else Path(str(BACKGROUND)+'-gain40')
        centers=[c.CENTER]*3
    r=module('link_quality_runner','rml2018a-rf-campaign.py')
    bg=r.module('link_quality_bg','validate-p201-termination-background.py')
    c.require(not root.exists() and root.resolve()==root,'fresh background root')
    password=Path('/home/jetson/.config/sdrharness/p201-root.password')
    c.require(password.is_file() and not password.is_symlink() and password.stat().st_mode&0o777==0o600,'credential mode')
    with socket.create_connection(('192.168.1.10',43110),timeout=3):pass
    nx=bg.tx_preflight();bg.idle();before=bg.ssh(bg.STATE);pid=bg.ssh('pidof sdrd').split()
    c.require(len(pid)==1,'single sdrd')
    c.require(bg.ssh('sha256sum /sd/sdr-agent/current/sdrd').split()[0]==
        '83a661a892b8ab71de3f4e7d64064c9c65030623dc7245eb3d3a1420a696ba4f','daemon identity')
    c.require(c.file_hash(bg.BINARY)=='24b8340dd5c56bcf643a44e1eadbd11450e3b5e528d2ec72dc26103e9f23e25f','Controller identity')
    bg.ssh('test -f /sd/sdr-agent/current/sdrd.conf && test -f /sd/sdr-agent/current/S60sdrd')
    c.require(bg.ssh(f'readlink /proc/{pid[0]}/exe').strip()=='/sd/sdr-agent/current/sdrd','daemon executable')
    c.require(sum(':43110 ' in line for line in bg.ssh('netstat -lnt').splitlines())==1,'single listener')
    state=dict(zip(before.splitlines()[::2],before.splitlines()[1::2]))
    c.require(all(v=='0' for k,v in state.items() if k.endswith(('_en','/enable'))),'idle masks/buffers')
    generation=time.time_ns()//1000000
    plans=[dict(sweep_id=f'link-background-{generation+i}',session_generation=generation+i,
        frequencies=dict(kind='centers',centers_hz=[center]),sample_rate_hz=c.RATE,
        rf_bandwidth_hz=c.BW,gain_db=gain,settle_ms=500,frame_samples=c.RX_SAMPLES,
        aggregate_frames=1,point_timeout_ms=1000,detection_threshold_db=12.) for i,center in enumerate(centers)]
    paths=[f'/tmp/sdr-agent-dev/agx-sweep-{p["session_generation"]}-0' for p in plans]
    maximum=len(plans)*c.RX_SAMPLES*4
    free=shutil.disk_usage(root.parent).free;c.require(free>maximum+32*1024**2,'disk budget')
    root.mkdir(mode=0o700)
    audit=dict(schema='rml-link-background-v1',script_sha256=c.file_hash(__file__),plans=plans,
        root=str(root),maximum_rx_bytes=maximum,free_bytes_before=free,
        expected_wall_seconds=len(plans)*4+15,deadline_seconds=600 if survey else 120,p201_paths=paths,nx_paths=[],
        stop='SIGINT/SIGTERM -> generation-specific cancel; finally restore exact radio state',
        radio_before=before,daemon_pid=pid[0],nx_before=nx,rows=[],restored=False,tx_operations=0,model_inferences=0,
        survey_contract=survey_contract)
    c.save(root/'audit.json',audit)
    print(json.dumps({k:audit[k] for k in ('maximum_rx_bytes','free_bytes_before','p201_paths','deadline_seconds')}),flush=True)
    def abort(sig,frame):raise RuntimeError(f'stopped:{sig}')
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM):signal.signal(sig,abort)
    signal.alarm(audit['deadline_seconds'])
    try:
        for i,plan in enumerate(plans):
            bg.idle();bg.ssh('test ! -e '+paths[i]);dest=root/f'point-{i}';dest.mkdir()
            output=dest/'rx' if gain==50 else dest
            if gain==50:output.mkdir()
            c.save(dest/('rx-plan.json' if gain==50 else 'plan.json'),plan)
            proc=subprocess.Popen([str(bg.BINARY),'--mode','sweep','--sdrd','192.168.1.10:43110',
                '--sigmf-directory',str(output)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                out,err=proc.communicate(json.dumps(plan).encode(),timeout=15)
                (dest/'stderr.log').write_bytes(err)
                if survey and proc.returncode!=0 and 'sdr_agent_error=summary_clipped:' in err.decode():
                    bg.restoration(before);bg.ssh('test ! -e '+paths[i])
                    audit['rows'].append(dict(point=i,center_hz=centers[i],status='clipped',error=err.decode().strip()))
                    c.save(root/'audit.json',audit)
                    print(json.dumps(dict(event='survey_point',point=i,center_hz=centers[i],status='clipped')),flush=True)
                    continue
                c.require(proc.returncode==0,'capture failed:'+err.decode()[-1000:]);c.save(dest/'report.json',json.loads(out))
            finally:
                if proc.poll() is None:
                    try:bg.command([bg.BINARY,'--mode','cancel','--sdrd','192.168.1.10:43110',
                        '--session-generation',str(plan['session_generation'])],timeout=6)
                    finally:
                        proc.terminate()
                        try:proc.communicate(timeout=5)
                        except subprocess.TimeoutExpired:proc.kill();proc.communicate(timeout=3)
            bg.restoration(before)
            if gain==50:raw,seal=r.native_check(dest,plan)
            else:
                original,raw=bg.bg.native(dest,plan);report=r.document(dest/'report.json')
                seal=dict(iq_path=report['dataset']['data_path'],iq_sha256=c.file_hash(report['dataset']['data_path']),
                    native_hashes=original['hashes'],request_id=original['request_id'],session_generation=original['session_generation'])
            row=dict(point=i,seal=seal,center_hz=centers[i],status='captured')
            if survey:
                stats=bg.bg.stats(raw)
                row['statistics']={key:stats[key] for key in ('raw','filtered','peak_segment')}
                row['round']=i//(8 if root==SURVEY else 2)
                print(json.dumps(dict(event='survey_point',point=i,center_hz=centers[i],statistics=row['statistics'])),flush=True)
            audit['rows'].append(row)
            bg.ssh('test ! -e '+paths[i]);c.save(root/'audit.json',audit)
    except BaseException as e:
        audit['error']=str(e)
        raise
    finally:
        signal.alarm(0)
        audit['radio_after']=bg.restoration(before);c.require(bg.ssh('pidof sdrd').split()==pid,'daemon changed')
        audit['nx_after']=bg.tx_preflight();audit['health_after']=r.document_health(bg)
        for path in paths:bg.ssh('test ! -e '+path)
        c.require(audit['health_after']['healthy'],'postflight health')
        audit['restored']=True;c.save(root/'audit.json',audit)


def select_survey(rows):
    c.require(len(rows)==24,'complete discovery required')
    c.require([r['center_hz'] for r in rows]==list(SURVEY_CENTERS+SURVEY_CENTERS[::-1]+SURVEY_CENTERS),
              'discovery schedule identity')
    ranking=[];excluded=[]
    for center in SURVEY_CENTERS:
        group=[r for r in rows if r['center_hz']==center]
        if any(r['status']!='captured' for r in group):
            excluded.append(center);continue
        ranking.append(dict(center_hz=center,
            worst_filtered_max=max(r['statistics']['filtered']['maximum'] for r in group),
            worst_filtered_p95=max(r['statistics']['filtered']['p95'] for r in group),
            worst_raw_max=max(r['statistics']['raw']['maximum'] for r in group)))
    ranking.sort(key=lambda r:(r['worst_filtered_max'],r['worst_filtered_p95'],r['worst_raw_max'],r['center_hz']))
    options=[r for r in ranking if r['center_hz']!=c.CENTER]
    c.require(bool(options),'no eligible alternative frequency')
    return dict(candidate_hz=options[0]['center_hz'],ranking=ranking,excluded_clipped_or_failed=excluded,
        rule='three successful discovery captures; minimize worst175kHz-FIR maximum, then p95, then raw maximum; baseline2455 excluded as candidate')


def confirm_survey(rows,candidate):
    c.require(candidate in SURVEY_CENTERS and candidate!=c.CENTER,'confirmation candidate')
    c.require(len(rows)==6 and [r['center_hz'] for r in rows]==[c.CENTER,candidate,candidate,c.CENTER,c.CENTER,candidate],
              'confirmation schedule identity')
    selected=[r for r in rows if r['center_hz']==candidate];baseline=[r for r in rows if r['center_hz']==c.CENTER]
    valid=all(r['status']=='captured' for r in selected)
    quiet=valid and all(0<r['statistics']['filtered']['p95']<=5 and 0<r['statistics']['filtered']['maximum']<=8 for r in selected)
    ratios=[]
    for a,b in zip(selected,baseline):
        ratios.append(float(20*np.log10(b['statistics']['filtered']['maximum']/a['statistics']['filtered']['maximum']))
            if a['status']==b['status']=='captured' and min(a['statistics']['filtered']['maximum'],b['statistics']['filtered']['maximum'])>0 else None)
    return dict(candidate_hz=candidate,baseline_hz=c.CENTER,all_candidate_captures_valid=valid,
        quiet_background_gate=quiet,criterion='each of three175kHz-FIR confirmations p95<=5 and max<=8 ADC RMS at RX40; background only, not RX SINR/recognition',
        paired_filtered_peak_reduction_db=ratios,reselection=False)


def survey():
    c.require(not SURVEY.exists() and not SURVEY_CONFIRM.exists(),'fresh survey roots')
    c.require(shutil.disk_usage(SURVEY.parent).free>30*c.RX_SAMPLES*4+64*1024**2,'overall survey budget')
    # Written before any RF action; exact per-point generations follow in audits.
    contract=dict(centers_hz=list(SURVEY_CENTERS),discovery_rounds=3,confirmation_points=6,
        maximum_points=30,maximum_rx_bytes=30*c.RX_SAMPLES*4,tx_operations=0,model_inferences=0,
        phase_deadline_seconds=600,total_phase_deadline_seconds=1200,
        ranking='worst filtered maximum, then p95, then raw maximum; require3 successful discovery captures',
        confirmation='fixed candidate vs2455 in AB/BA/AB pairs; no reselection; quiet gate p95<=5/max<=8 ADC RMS',
        scope='eight1.5MHz windows; discrete comparison, not continuous coverage or long-term occupancy',
        filter='257-tap175kHz Kaiser beta8; raw and filtered summaries both recorded')
    print(json.dumps(dict(event='survey_contract',**contract)),flush=True)
    capture(40,root=SURVEY,centers=list(SURVEY_CENTERS+SURVEY_CENTERS[::-1]+SURVEY_CENTERS),survey_contract=contract)
    a=json.loads((SURVEY/'audit.json').read_text());selection=select_survey(a['rows']);c.save(SURVEY/'selection.json',selection)
    c.save(SURVEY/'survey-contract.json',contract)
    candidate=selection['candidate_hz'];print(json.dumps(dict(event='candidate',**selection)),flush=True)
    capture(40,root=SURVEY_CONFIRM,centers=[c.CENTER,candidate,candidate,c.CENTER,c.CENTER,candidate],survey_contract=contract)
    a=json.loads((SURVEY_CONFIRM/'audit.json').read_text());result=confirm_survey(a['rows'],candidate)
    c.save(SURVEY_CONFIRM/'confirmation.json',result);print(json.dumps(dict(event='confirmation',**result)),flush=True)


def power_stats(z):
    blocks=np.mean(abs(z[:len(z)//256*256].reshape(-1,256))**2,axis=1)
    f=np.fft.fftfreq(len(z),1/c.RATE);s=abs(np.fft.fft(z*np.hanning(len(z))))**2
    peak=float(f[s.argmax()]);quiet=float(np.quantile(blocks,.1))
    return dict(block_samples=256,block_power_adc_squared=blocks.tolist(),
        block_power_p10=quiet,block_power_median=float(np.median(blocks)),block_power_max=float(blocks.max()),
        peak_over_p10_db=float(10*np.log10(blocks.max()/max(quiet,1e-30))),
        fraction_blocks_over_p10_plus10db=float(np.mean(blocks>quiet*10)),
        dominant_baseband_hz=peak,peak_plusminus2khz_hann_power_fraction=float(s[abs(f-peak)<=2000].sum()/s.sum()),
        inside_plusminus175khz_hann_power_fraction=float(s[abs(f)<=175000].sum()/s.sum()))


def analyze():
    read=lambda p:json.loads(p.read_text())
    inventory=c.REPO/'docs/evidence/RML2018A_SINR_IMPLEMENTATION_2026-09-11.json'
    parent=read(inventory)
    for package in parent['packages']:
        for item in package['files']:
            p=Path(item['path']);c.require(p.stat().st_size==item['bytes'] and c.file_hash(p)==item['sha256'],'parent evidence')
    repair=module('link_quality_fir','repair-b210-lo-leakage.py');results=[]
    for package in parent['packages']:
        root=Path(package['root']);plan=read(root/'run-plan.json')
        for index in (4267,22016):
            dest=root/f'batch-{index:07d}';a=read(dest/'audit.json');source=read(dest/'source.json')
            v=np.fromfile(a['seal']['iq_path'],dtype='<i2').reshape(-1,2);z=v[:,0].astype(float)+1j*v[:,1]
            result=dict(root=str(root),batch=index,iq_sha256=a['seal']['iq_sha256'],stats=power_stats(z),
                max_abs_adc_component=int(abs(v.astype('i4')).max()),original_status=a['status'],
                uhd_tail_markers=a['uhd_tail_markers'],tx_feed=read(dest/'tx-summary.json'),fixed_payload=None)
            if 'sync' in a:
                sy=a['sync'];start=sy['payload_marker_offset']+1024;n=np.arange(len(z))
                corrected=z*np.exp(-2j*np.pi*sy['estimated_cfo_hz']*n/c.RATE+1j*sy['phase_rotation_rad'])
                raw=corrected[start:start+24576].reshape(24,1024)
                c.require(start>=128 and start+24576<=len(z)-128,'FIR halos')
                filt=repair.reject(corrected)[start-128:start+24576-128].reshape(24,1024)
                with h5py.File(plan['source']['path'],'r') as h:iq=h['X'][source['rows']]
                c.require(c.digest(iq.tobytes())==source['original_iq_sha256'],'source hash')
                x=iq[...,0].astype(float)+1j*iq[...,1];frame,scales=c.packet(iq,plan['run_id'],index)
                c.require(c.digest(frame.tobytes())==a['tx_plan']['payload_sha256'],'frame hash')
                fx=repair.reject(np.tile(frame,3))[len(frame)-128:2*len(frame)-128][c.GUARD+c.MARKER:-c.GUARD].reshape(24,1024)/scales[:,None]
                def cc(x,y):
                    x=x-x.mean();y=y-y.mean();return float(abs(np.vdot(x,y))/max(np.linalg.norm(x)*np.linalg.norm(y),1e-30))
                rows=[]
                for k in range(24):
                    xx=x[k]-x[k].mean();lo=start+k*1024-1200;seg=corrected[lo:start+(k+1)*1024+1200]
                    corr=abs(np.correlate(seg,xx,'valid'));cs=np.r_[0,np.cumsum(abs(seg)**2)];sm=np.r_[0,np.cumsum(seg)]
                    energy=cs[1024:]-cs[:-1024]-abs(sm[1024:]-sm[:-1024])**2/1024
                    score=corr/np.sqrt(np.maximum(energy,1e-30)*np.vdot(xx,xx).real)
                    rows.append(dict(row=source['rows'][k],original_quality=a['receive_quality'][k]['rx_sinr_reason'],
                        source_tx_power=float(np.mean(abs(x[k]*scales[k])**2)),received_power=float(np.mean(abs(raw[k])**2)),
                        raw_centered_coherence=cc(x[k],raw[k]),filtered_centered_coherence=cc(fx[k],filt[k]),
                        source_filter_retention=float(np.sum(abs(fx[k])**2)/np.sum(abs(x[k])**2)),
                        source_filter_distortion=float(np.sum(abs(fx[k]-x[k])**2)/np.sum(abs(x[k])**2)),
                        diagnostic_only_best_lag=int(score.argmax())-1200,diagnostic_only_best_coherence=float(score.max())))
                result['fixed_payload']=dict(sync=sy,rows=rows,filter_contract=repair.filter_contract(),
                    timing_search='diagnostic +/-1200 only; not applied to FIR, SINR or model',
                    filtered_sinr=None,reason='Z source-noise fraction after filtering is uncalibrated; coherence comparison only')
            results.append(result)
    background_root=Path(str(BACKGROUND)+'-gain40')
    background=read(background_root/'audit.json');c.require(background['restored'],'background restore')
    off=[]
    for item in background['rows']:
        seal=item['seal'];path=Path(seal['iq_path']);c.require(c.file_hash(path)==seal['iq_sha256'],'background IQ hash')
        v=np.fromfile(path,dtype='<i2').reshape(-1,2);z=v[:,0].astype(float)+1j*v[:,1]
        off.append(dict(point=item['point'],seal=seal,stats=power_stats(z)))
    return dict(schema='rml-link-quality-diagnosis-v1',script_sha256=c.file_hash(__file__),
        parent_inventory_sha256=c.file_hash(inventory),background_audit_sha256=c.file_hash(background_root/'audit.json'),
        background_gain_db=40,failed_gain50_audit_sha256=c.file_hash(BACKGROUND/'audit.json'),
        tx_operations=0,model_inferences=0,background=off,campaigns=results,
        limitations='TX-off comparison is later/session-separated; no Wi-Fi decode or instrument-calibrated SINR; original audit bytes unchanged')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['capture-background','analyze','survey'])
    p.add_argument('--gain',type=int,choices=[40,50],default=40);args=p.parse_args()
    if args.command=='capture-background':capture(args.gain)
    elif args.command=='survey':survey()
    else:print(json.dumps(analyze(),indent=2,allow_nan=False))
