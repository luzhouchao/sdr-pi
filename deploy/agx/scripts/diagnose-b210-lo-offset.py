#!/usr/bin/env python3
"""Registered single-source TX LO comparison; no classifier or production DSP."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess

import numpy as np

if not __debug__:raise RuntimeError('validation assertions required')
SCRIPTS=Path(__file__).parent
spec=importlib.util.spec_from_file_location('lo_point',SCRIPTS/'diagnose-b210-1024-pointwise.py')
point=importlib.util.module_from_spec(spec);spec.loader.exec_module(point)
live=point.live
ROOT=Path('/var/tmp/sdrharness-dev/b210-lo-906l')
CASES=(('a0',0),('p250',250000),('b0',0),('m250',-250000),('c0',0))
SOURCE_HASH='c8e3d54629eb7dde75e6a49554090f570522e7b438d2602dce85a18cd1d771f9'
NX=live.link_tool.NX

def feature(tag):return ROOT.parent/f'b210-lo-{tag}-906l'
def save(path,value):
    with path.open('x') as stream:json.dump(value,stream,indent=2,allow_nan=False);stream.write('\n')
def command(args):return subprocess.run(list(map(str,args)),check=True,capture_output=True,text=True,timeout=200).stdout

def validate_plan(root,offset):
    p=live.document(root/'transmission-plan.json')
    for k,v in dict(schema_version=3,diagnostic_contract='b210_1024_lo_offset_v1',tx_lo_offset_hz=offset,
                    tx_requested_lo_hz=2440000000+offset,rows=[102400],source_unit_samples=1024,
                    tx_unit_count=20480,payload_bytes=8192,uhd_spb=1024,tx_samples=20971520,
                    tx_nominal_seconds=10,class_id=0,dataset_nominal_snr_db=30,split='train',locked_test_read=False,
                    center_hz=2440000000,rate_sps=2100000,bandwidth_hz=1500000,tx_gain_db=70,
                    complex_peak=.2,tx_channel=0,tx_antenna='TX/RX',payload_sha256=SOURCE_HASH,
                    source_iq_sha256='3c2c5d5606a7d1a8721511afddd49ca8c2183968d59b38a4e099754646cf0922').items():
        assert p[k]==v,k
    assert type(offset) is int and offset in (-250000,0,250000)
    assert hashlib.sha256(live.read(root/'train-tile.fc32')).hexdigest()==SOURCE_HASH
    return p

def seal_case(root,offset):
    validate_plan(root,offset)
    seal=live.validate_capture_root(root,'rml',single_source_sha256=SOURCE_HASH)
    tx=live.document(root/'tx-summary.json')
    assert tx['tx_lo_offset_hz']==offset and tx['tx_requested_lo_hz']==2440000000+offset
    log=live.read(root/'tx-uhd.log').decode()
    for label,wanted in [('Setting TX LO Offset',offset/1e6),('Actual TX Freq',2440.),
                         ('Actual TX Rate',2.1),('Actual TX Bandwidth',1.5),('Actual TX Gain',70.)]:
        values=re.findall(re.escape(label)+r': ([\d.+-]+)',log)
        assert len(values)==1 and abs(float(values[0])-wanted)<1e-6,label
    seal['source_hashes']={name:hashlib.sha256(live.read(root/name)).hexdigest() for name in
                           ('transmission-plan.json','train-tile.fc32','tx-summary.json','tx-uhd.log')}
    return seal

def extra_line(source,raw,controls,fit,offset):
    """Prefix-only peak estimate and raw-domain source/carrier/DC/LO fit."""
    if type(offset) is not int or offset not in (-250000,250000):raise ValueError('separated registered LO required')
    if np.shape(raw)!=(point.COUNT,) or not np.isfinite(raw).all():raise ValueError('complete finite RX required')
    if np.shape(source)!=(1024,) or not np.isfinite(source).all():raise ValueError('finite single source required')
    if set(controls)!={'baseline','after-tx'} or any(np.shape(z)!=(point.COUNT,) or not np.isfinite(z).all() for z in controls.values()):
        raise ValueError('two complete finite stopped controls required')
    if not np.isfinite(fit['total_frequency_hz']) or abs(fit['total_frequency_hz'])>5200:raise ValueError('invalid source CFO')
    n=np.arange(point.FIT);expected=fit['total_frequency_hz']+offset
    freq=np.fft.fftfreq(point.FIT,1/point.RATE)
    power=abs(np.fft.fft(raw[:point.FIT]*np.hanning(point.FIT)))**2
    candidates=np.flatnonzero(abs(freq-expected)<=1000)
    k=int(candidates[np.argmax(power[candidates])])
    values=np.log(np.maximum(power[[k-1,k,k+1]],1e-30))
    denominator=values[0]-2*values[1]+values[2]
    delta=float(.5*(values[0]-values[2])/denominator) if denominator < -1e-12 else 0.
    peak=float(freq[k]+delta*point.RATE/point.FIT)
    interior=bool(k not in (candidates[0],candidates[-1]) and abs(delta)<=.5)
    def spectral_band(z):
        spectrum=abs(np.fft.fft(z[:point.FIT]*np.hanning(point.FIT)))**2
        return float(spectrum[abs(freq-peak)<=500].sum())
    powers={tag:spectral_band(z) for tag,z in dict(controls,**{'during-tx':raw}).items()}
    contrast={tag:float(10*np.log10(max(powers['during-tx'],1e-30)/max(powers[tag],1e-30))) for tag in controls}
    n=np.arange(point.COUNT)
    matrix=np.column_stack((point.design_matrix(source,fit,(0,),point.COUNT),np.exp(2j*np.pi*peak*n/point.RATE)))
    models={}
    for robust in (False,True):
        coefficients,metrics=point.solve_channel(matrix[:point.FIT],raw[:point.FIT],robust)
        error=raw-matrix@coefficients
        metrics.update(prefix_residual_rms=point.rms(error[:point.FIT]),heldout_residual_rms=point.rms(error[point.FIT:]))
        models['robust' if robust else 'ols']=metrics
    return dict(expected_hz=expected,peak_hz=peak,peak_minus_expected_hz=peak-expected,interior_peak=interior,
                stopped_contrast_db=contrast,line_observed=bool(interior and min(contrast.values())>=20),
                models=models,fit_samples=point.FIT,applied_to_production=False)

def analyze():
    seal=live.document(ROOT/'seal.json')
    assert live.validate_capture_root(feature('tone'),'tone')==seal['tone']
    tone=live.match.tone_metrics(feature('tone'));assert live.match.assess_tone(tone)['passed']
    report=dict(schema_id='b210_1024_lo_offset_audit_v1',tone=tone,cases={},seal=seal,
                model_windows=0,independent_labels=0,recognizer_available=False,cleanup={'verified':False})
    for tag,offset in CASES:
        root=feature(tag);assert seal_case(root,offset)==seal['cases'][tag]
        v=np.frombuffer(live.read(root/'train-tile.fc32'),dtype='<f4').reshape(1024,2)
        source=v[:,0].astype(float)+1j*v[:,1].astype(float)
        captures={t:live.match.read_iq(root,t)[0] for t in ('baseline','during-tx','after-tx')}
        controls={t:captures[t] for t in ('baseline','after-tx')}
        result,arrays=point.compare(source,captures['during-tx'],controls,tone['frequency_difference_hz'],live.match.source_bandwidth(source))
        result['tx_lo_offset_hz']=offset
        if arrays is not None and offset:result['separated_lo_line']=extra_line(source,captures['during-tx'],controls,result['alignment'],offset)
        result['link_evidence']=live.document(root/'link-summary.json')
        result['tx_evidence']=live.document(root/'tx-summary.json')
        report['cases'][tag]=result
    return report

def acquire(binary, *, root=ROOT, cases=CASES, feature_path=feature, center_hz=2440000000,
            validate_source=validate_plan, seal_source=seal_case):
    assert root.resolve()==root and root.is_dir()
    assert 1<=len(cases)<=5 and len({tag for tag,_ in cases})==len(cases)
    assert center_hz in (2440000000,2455000000)
    for tag,value in cases:
        validate_source(feature_path(tag),value)
        assert not (feature_path(tag)/'link-summary.json').exists() and not (feature_path(tag)/'link-started.json').exists()
    save(root/'matrix-started.json',dict(cases=cases,max_rx_bytes=786420*(1+len(cases)),max_nominal_tx_seconds=10*(1+len(cases)),free_bytes=shutil.disk_usage(root).free))
    assert shutil.disk_usage(root).free>64*1024*1024
    for tag,offset in (('tone',0),*cases):
        case_root=feature_path(tag)
        assert case_root.resolve()==case_root and case_root.is_dir()
        if tag!='tone':validate_source(case_root,offset)
        args=['timeout','--signal=TERM','--kill-after=20s','180s','python3',SCRIPTS/'validate-b210-p201-link.py',
              '--directory',case_root,'--controller',binary,'--mode','tone' if tag=='tone' else 'rml','--rx-gain-db','40','--center-hz',str(center_hz)]
        with (case_root/'runner.log').open('x') as log:
            subprocess.run(list(map(str,args)),stdout=log,stderr=subprocess.STDOUT,check=True,timeout=205)
        if tag=='tone':
            live.validate_capture_root(case_root,'tone',expected_center_hz=center_hz)
            result=live.match.tone_metrics(case_root);save(root/'tone-check.json',dict(metrics=result,assessment=live.match.assess_tone(result)))
            assert live.match.assess_tone(result)['passed'],'tone gate failed'
        else:
            for name in ('tx-summary.json','tx-uhd.log'):
                command(['scp','-F','/home/jetson/.ssh/config',f'nx:{case_root}/{name}',case_root/name])
            seal_source(case_root,offset)
        print(json.dumps({'completed':tag}),flush=True)
    save(root/'seal.json',dict(tone=live.validate_capture_root(feature_path('tone'),'tone',expected_center_hz=center_hz),cases={tag:seal_source(feature_path(tag),off) for tag,off in cases}))

def plot(report,destination):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(3,1,figsize=(11,10),constrained_layout=True)
    for tag,offset in CASES:
        assert seal_case(feature(tag),offset)==report['seal']['cases'][tag], 'plot input changed'
        raw=live.match.read_iq(feature(tag),'during-tx')[0]
        frequency=np.fft.fftshift(np.fft.fftfreq(point.FIT,1/point.RATE))
        power=abs(np.fft.fftshift(np.fft.fft(raw[:point.FIT]*np.hanning(point.FIT))))**2
        axes[0].plot(frequency/1000,10*np.log10(np.maximum(power/(np.hanning(point.FIT).sum()**2),1e-20)),lw=.7,label=tag)
        result=report['cases'][tag]
        if 'segments' not in result:continue
        rows=result['segments'];time=np.array([r['start'] for r in rows])/point.RATE*1000
        axes[1].plot(time,[r['residual_rms'] for r in rows],lw=.7,label=tag)
        axes[2].plot(time,[r['local_phase_difference_rad'] for r in rows],lw=.7,label=tag)
    axes[0].set(xlim=(-300,300),xlabel='RX baseband frequency (kHz)',ylabel='Prefix spectrum (dB ADC²)',title='Same 1024 source; TX LO offset is the only requested setting changed')
    axes[1].set(xlabel='Capture time (ms)',ylabel='Fixed M0 residual RMS (ADC)')
    axes[2].set(xlabel='Capture time (ms)',ylabel='Local phase error (rad)')
    for axis in axes:axis.grid(alpha=.2);axis.legend(ncol=5)
    for axis in axes[1:]:axis.axvline(point.FIT/point.RATE*1000,color='black',ls='--',lw=.7)
    fig.savefig(destination,dpi=150);plt.close(fig)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--acquire',type=Path);p.add_argument('--analyze',action='store_true')
    a=p.parse_args()
    if a.acquire:acquire(a.acquire)
    elif a.analyze:save(ROOT/'analysis.json',analyze())
    else:p.error('choose acquire or analyze')
