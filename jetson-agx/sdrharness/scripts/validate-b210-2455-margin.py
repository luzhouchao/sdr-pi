#!/usr/bin/env python3
"""Preregistered 2455-MHz ABBA source-margin comparison; production stays unavailable."""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import signal
import numpy as np

if not __debug__:raise RuntimeError('validation assertions required')
SCRIPTS=Path(__file__).parent
spec=importlib.util.spec_from_file_location('margin_repair',SCRIPTS/'repair-b210-lo-leakage.py')
repair=importlib.util.module_from_spec(spec);spec.loader.exec_module(repair)
lo,live=repair.lo,repair.live
ROOT=Path('/var/tmp/sdrharness-dev/b210-margin-907o')
CASES=(('low1',.2),('high1',.3),('high2',.3),('low2',.2))
HASHES={.2:lo.SOURCE_HASH,.3:'4210142a62664b856a1ea9716e520b7e50c8a0c5167a4930b3d235161e6885d1'}
PARENT=Path('/var/tmp/sdrharness-dev/b210-reject-zero-907m')

def feature(tag):return ROOT.parent/f'b210-margin-{tag}-907o'

def derive(parent,peak):
    if peak not in HASHES or len(parent)!=8192 or lo.hashlib.sha256(parent).hexdigest()!=lo.SOURCE_HASH:
        raise ValueError('registered immutable 1024 parent/peak required')
    multiplier=1. if peak==.2 else 1.5
    v=np.frombuffer(parent,dtype='<f4').reshape(1024,2)
    out=np.asarray(v*np.float32(multiplier),dtype='<f4')
    assert np.isfinite(out).all() and float(np.max(np.hypot(out[:,0].astype(float),out[:,1].astype(float))))<=peak+1e-6
    payload=out.tobytes();assert lo.hashlib.sha256(payload).hexdigest()==HASHES[peak]
    return payload

def validate_plan(root,peak):
    p=live.document(root/'transmission-plan.json');payload=live.read(root/'train-tile.fc32')
    for key,value in dict(schema_version=4,diagnostic_contract='b210_2455_margin_v1',center_hz=2455000000,
                          tx_lo_offset_hz=250000,tx_requested_lo_hz=2455250000,complex_peak=peak,
                          parent_payload_sha256=lo.SOURCE_HASH,source_gain_multiplier=1. if peak==.2 else 1.5,
                          payload_sha256=HASHES[peak],payload_bytes=8192,source_unit_samples=1024,rows=[102400],
                          tx_unit_count=20480,tx_samples=20971520,tx_nominal_seconds=10,uhd_spb=1024,
                          rate_sps=2100000,bandwidth_hz=1500000,tx_gain_db=70,tx_channel=0,tx_antenna='TX/RX',
                          class_id=0,dataset_nominal_snr_db=30,split='train',locked_test_read=False,
                          source_iq_sha256='3c2c5d5606a7d1a8721511afddd49ca8c2183968d59b38a4e099754646cf0922').items():assert p[key]==value,key
    assert p['parent_amplitude_scale']==0.07039332889300712
    assert p['amplitude_scale']==p['parent_amplitude_scale']*p['source_gain_multiplier']
    assert payload==derive(live.read(feature('low1')/'train-tile.fc32'),peak)
    return p

def export():
    # Parent package is inventoried, immutable and remains in place; no HDF access.
    plan=live.document(PARENT/'transmission-plan.json');parent=live.read(PARENT/'train-tile.fc32')
    assert plan['payload_sha256']==lo.SOURCE_HASH
    for tag,peak in CASES:
        root=feature(tag);assert root.resolve()==root and root.is_dir()
        payload=derive(parent,peak)
        p=dict(plan,schema_version=4,diagnostic_contract='b210_2455_margin_v1',center_hz=2455000000,
               tx_lo_offset_hz=250000,tx_requested_lo_hz=2455250000,complex_peak=peak,
               payload_sha256=HASHES[peak],parent_payload_sha256=lo.SOURCE_HASH,
               source_gain_multiplier=1. if peak==.2 else 1.5,
               parent_amplitude_scale=plan['amplitude_scale'],
               amplitude_scale=plan['amplitude_scale']*(1. if peak==.2 else 1.5),
               derivation='float32 multiply of retained 1024 source; unchanged order and period')
        with (root/'train-tile.fc32').open('xb') as stream:stream.write(payload)
        lo.save(root/'transmission-plan.json',p);validate_plan(root,peak)


def seal_case(root,peak):
    validate_plan(root,peak)
    seal=live.validate_capture_root(root,'rml',single_source_sha256=HASHES[peak],expected_center_hz=2455000000)
    tx=live.document(root/'tx-summary.json')
    assert (tx['center_hz'],tx['complex_peak'],tx['tx_lo_offset_hz'],tx['tx_requested_lo_hz'])==(2455000000,peak,250000,2455250000)
    log=live.read(root/'tx-uhd.log').decode()
    for label,value in [('Setting TX LO Offset',.25),('Actual TX Freq',2455.),('Actual TX Rate',2.1),('Actual TX Bandwidth',1.5),('Actual TX Gain',70.)]:
        found=lo.re.findall(lo.re.escape(label)+r': ([\d.+-]+)',log)
        assert len(found)==1 and abs(float(found[0])-value)<1e-6,label
    seal['source_hashes']={name:lo.hashlib.sha256(live.read(root/name)).hexdigest() for name in ('transmission-plan.json','train-tile.fc32','tx-summary.json','tx-uhd.log')}
    return seal


def prepare():
    seal=live.document(ROOT/'seal.json')
    assert live.validate_capture_root(feature('tone'),'tone',expected_center_hz=2455000000)==seal['tone']
    tone=live.match.tone_metrics(feature('tone'));assert live.match.assess_tone(tone)['passed']
    report=dict(schema_id='b210_2455_abba_margin_v1',analysis_numpy=np.__version__,filter_contract=repair.filter_contract(),
                model_inputs={},cases={},seal=seal,model_start=32768,recognizer_available=False,independent_labels=0,
                production_profile_compatible=False,tone=tone)
    tensors={}
    for tag,peak in CASES:
        root=feature(tag);assert seal_case(root,peak)==seal['cases'][tag]
        v=np.frombuffer(live.read(root/'train-tile.fc32'),dtype='<f4').reshape(1024,2);source=v[:,0].astype(float)+1j*v[:,1].astype(float)
        captures={p:live.match.read_iq(root,p)[0] for p in ('baseline','during-tx','after-tx')}
        result,inputs=repair.evaluate(source,captures,tone['frequency_difference_hz'],250000)
        result.update(complex_peak=peak,link_evidence=live.document(root/'link-summary.json'),tx_evidence=live.document(root/'tx-summary.json'))
        report['cases'][tag]=result
        for name,data in inputs.items():tensors[tag+'_'+name]=data
    report['model_inputs']={key:lo.hashlib.sha256(value.tobytes()).hexdigest() for key,value in tensors.items()}
    report['all_fixed_model_blocks_passed']=all(c['model_control_passed'] for c in report['cases'].values())
    return report,tensors


def acquire(binary):
    # Complete preflight before any tone or RML operation.
    assert not any((feature(tag)/'link-summary.json').exists() for tag in ('tone',*(tag for tag,_ in CASES)))
    for tag,peak in CASES:
        validate_plan(feature(tag),peak)
        v=np.frombuffer(live.read(feature(tag)/'train-tile.fc32'),dtype='<f4').reshape(1024,2)
        assert repair.source_retention(v[:,0].astype(float)+1j*v[:,1].astype(float))['power_fraction']>=.99
    contract=repair.filter_contract();assert contract['coefficients_sha256']=='d0e12014bedae088b71366497299adc3a1be0a45cf622e9cbb346d4ea0c8c8be'
    lo.acquire(binary,root=ROOT,cases=CASES,feature_path=feature,center_hz=2455000000,validate_source=validate_plan,seal_source=seal_case)

def unaligned_statistics(report):
    background=live.affine.module('margin_background','diagnose-b210-background.py')
    return {tag:dict(reason='prefix alignment unusable; no channel prediction or model admission',
                     statistics=background.stats(live.match.read_iq(feature(tag),'during-tx')[0]))
            for tag,c in report['cases'].items() if not c['pointwise']['alignment']['usable']}


def verify_retained():
    manifest=live.document(live.affine.ROOT/'docs/evidence/B210_2455_MARGIN_EVIDENCE_2026-09-07.json')
    audit=live.document(live.affine.ROOT/'docs/evidence/B210_2455_MARGIN_AUDIT_2026-09-07.json')
    expected={r['path'] for r in manifest['files']}
    assert {str(p) for name in manifest['roots'] for p in Path(name).rglob('*') if p.is_file()}==expected
    for row in manifest['files']:
        data=live.read(Path(row['path']));assert len(data)==row['bytes'] and lo.hashlib.sha256(data).hexdigest()==row['sha256']
    report,tensors=prepare();assert all(audit[k]==v for k,v in report.items())
    assert unaligned_statistics(report)==audit['unaligned_statistics']
    assert set(tensors)==set(audit['inference']['results'])
    for key,data in tensors.items():assert lo.hashlib.sha256(data.tobytes()).hexdigest()==audit['inference']['results'][key]['input_sha256']
    print(json.dumps(dict(sealed_analysis_and_model_inputs_reproduced=True,qualified_cases=[k for k,c in report['cases'].items() if c['model_control_passed']],
                         model_reexecuted=False,rf_operations=0,retained_files=len(expected))))


def plot(destination):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    # Plot stored parameters with the system plotting runtime; model preparation
    # remains byte-reproduced in its pinned NumPy environment.
    report=live.document(ROOT/'prepared.json')
    assert live.validate_capture_root(feature('tone'),'tone',expected_center_hz=2455000000)==report['seal']['tone']
    fig,axes=plt.subplots(2,4,figsize=(16,8),constrained_layout=True)
    for col,(tag,peak) in enumerate(CASES):
        assert seal_case(feature(tag),peak)==report['seal']['cases'][tag]
        case=report['cases'][tag];fit=case['pointwise']['alignment']
        raw=live.match.read_iq(feature(tag),'during-tx')[0];filtered=repair.reject(raw)
        starts=np.arange(128,65535-128,128);times=starts/2100000*1000
        for v,offset,label,color in ((raw,0,'RX raw','#b2182b'),(filtered,128,'Fixed FIR','#2166ac')):
            axes[0,col].plot(times,[repair.point.rms(v[k-offset:min(k+128,65535-128)-offset]) for k in starts],label=label,color=color,lw=.8)
        axes[0,col].axvspan(32768/2100000*1000,36864/2100000*1000,color='gray',alpha=.2)
        axes[0,col].set(xlabel='Capture time (ms)',ylabel='128-sample ADC RMS',title=tag+' / peak '+str(peak))
        n=np.arange(32768,32768+192)
        axes[1,col].plot(n,raw[n].real,label='RX raw I',color='#b2182b',lw=.6)
        axes[1,col].plot(n,filtered[n-128].real,label='Fixed FIR I',color='#2166ac',lw=.9)
        if fit['usable']:
            v=np.frombuffer(live.read(feature(tag)/'train-tile.fc32'),dtype='<f4').reshape(1024,2);source=v[:,0].astype(float)+1j*v[:,1].astype(float)
            all_n=np.arange(65535);h=complex(*case['pointwise']['models']['scalar_robust']['coefficients'][0])
            predicted=repair.reject(h*source[(all_n-fit['lag'])%1024]*np.exp(2j*np.pi*fit['total_frequency_hz']*all_n/2100000))
            axes[1,col].plot(n,predicted[n-128].real,label='Source prediction I',color='#1b9e77',lw=.9)
        axes[1,col].set(xlabel='Original sample index',ylabel='I (ADC units)',title='Fixed model gate '+('PASS' if case['model_control_passed'] else 'FAIL'))
        for axis in axes[:,col]:axis.grid(alpha=.2);axis.legend(fontsize=7)
    fig.suptitle('2455-MHz ABBA: all captures retained; first 192 points of the fixed model block shown')
    fig.savefig(destination,dpi=150);plt.close(fig)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--export',action='store_true');g.add_argument('--acquire',type=Path);g.add_argument('--prepare',action='store_true');g.add_argument('--infer',action='store_true');g.add_argument('--plot',type=Path);g.add_argument('--verify-retained',action='store_true')
    a=p.parse_args()
    if a.export:export()
    elif a.acquire:acquire(a.acquire)
    elif a.prepare:lo.save(ROOT/'prepared.json',prepare()[0])
    elif a.plot:plot(a.plot)
    elif a.verify_retained:verify_retained()
    else:
        def abort(signum,frame):raise RuntimeError(f'stop signal {signum}')
        for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,abort)
        asyncio.run(repair.infer(root=ROOT,prepare_function=prepare,max_inputs=16))
