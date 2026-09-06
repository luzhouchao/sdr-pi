#!/usr/bin/env python3
"""Sealed real RX controls and frozen-v4 known-source affine comparison."""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import signal

import numpy as np

if not __debug__:
    raise RuntimeError('validation requires assertions')
SCRIPTS = Path(__file__).parent
spec = importlib.util.spec_from_file_location('v4_affine', SCRIPTS/'diagnose-b210-rx-affine.py')
affine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(affine)
match = affine.fidelity.source_match
link_tool = affine.module('v4_link', 'validate-b210-p201-link.py')
FEATURE = Path('/var/tmp/sdrharness-dev/b210-v4-live-906j')
TONE = Path('/var/tmp/sdrharness-dev/b210-v4-tone-906j')
RX_IDENTITY = dict(identity_version=1,verified=True,front_panel_port='RX1',logical_channel='RX0',
                   phy_channel='voltage0',scan_i_channel='voltage0',scan_q_channel='voltage1',
                   rf_port_select='A_BALANCED',source='iio_channel_attr')


def read(path):
    assert path.resolve()==path and path.is_file() and not path.is_symlink(), str(path)
    return path.read_bytes()


def document(path):
    return json.loads(read(path))


def validate_capture_root(root, mode):
    """Bind native reports, physical identity, raw files and requested SigMF settings."""
    link = document(root/'link-summary.json')
    rate,width = (2500000,1000000) if mode=='tone' else (2100000,1500000)
    assert link['status']=='transport_completed_pending_signal_analysis'
    for key,value in dict(mode=mode,center_hz=2440000000,rate_sps=rate,bandwidth_hz=width,
                          rx_gain_db=40,tx_gain_db=70,rx_input='RX1/RX0/A_BALANCED',
                          max_rx_bytes=786420,tx_nominal_seconds=10,
                          max_tx_samples=25000000 if mode=='tone' else 21000000).items():
        assert link[key]==value, key
    assert link['feature_directory']==str(root)
    assert link['remote_tx_stopped'] is True and link['restoration_errors']==[]
    assert all(code==0 for code in link['local_process_exit_codes'])
    assert link_tool.rf.restored_state(link['radio_before'],link['radio_after'])
    if mode=='tone':
        assert link['tx_exit_code']==0
    else:
        tx = document(root/'tx-summary.json')
        assert tx['status']=='sent' and tx['bytes_written']==168000000
        assert tx['child_stopped'] is True and tx['child_exit_code']==0
        assert tx['payload_sha256']==affine.paired.SOURCE_HASH
        assert tx['uhd_log_sha256']==affine.paired.sha(read(root/'tx-uhd.log'))
        assert (tx['max_samples'],tx['rate_sps'],tx['nominal_seconds'])==(21000000,2100000,10)
        assert all(tx[key]==value for key,value in link['tx_result'].items())
    assert len(link['plans'])==3
    hashes = {'link-summary.json':affine.paired.sha(read(root/'link-summary.json'))}
    rows = []
    for index,(tag,field) in enumerate((('baseline','baseline'),('during-tx','during_tx'),('after-tx','after_tx'))):
        report = document(root/f'{tag}-report.json')
        assert report==link[field] and report['backend']=='agx_iq_software_aggregate'
        assert len(report['points'])==1
        point = report['points'][0];plan=link['plans'][index]
        generation = link['generation']+index
        assert report['session_generation']==point['session_generation']==plan['session_generation']==generation
        assert report['sweep_id']==plan['sweep_id']==f'b210-{tag}-{generation}'
        assert point['rx_input']==RX_IDENTITY
        for key,value in dict(point_index=0,requested_center_hz=2440000000,actual_center_hz=2440000000,
                              sample_rate_hz=rate,rf_bandwidth_hz=width,captured_samples=65535,
                              dropped_samples=0,overflow=False,clipped_samples=0,status_flags=0).items():
            assert point[key]==value,key
        assert point['health']==dict(healthy=True,flags=0,source='iio_adapter')
        assert point['timeout']['timed_out'] is False and point['timeout']['limit_ms']==1000
        assert type(point['request_id']) is int and point['request_id']>0
        assert type(point['sequence']) is int and point['sequence']>0
        for key,value in dict(sample_rate_hz=rate,rf_bandwidth_hz=width,gain_db=40,
                              settle_ms=500,frame_samples=65535,aggregate_frames=1,point_timeout_ms=1000).items():
            assert plan[key]==value,key
        assert plan['frequencies']==dict(kind='centers',centers_hz=[2440000000])
        dataset = report['dataset']
        assert dataset['bytes']==262140 and dataset['datatype']=='ci16_le' and dataset['format']=='sigmf'
        data,meta = Path(dataset['data_path']),Path(dataset['metadata_path'])
        assert data.parent==meta.parent==root/tag
        assert list((root/tag).glob('*.sigmf-data'))==[data]
        assert list((root/tag).glob('*.sigmf-meta'))==[meta]
        raw = read(data);assert len(raw)==262140
        metadata = document(meta)
        assert metadata['global']['core:datatype']=='ci16_le'
        assert metadata['global']['core:sample_rate']==rate
        assert metadata['global']['sdrharness:sample_layout']=='interleaved_iq'
        assert metadata['captures']==[{'core:sample_start':0,'core:frequency':2440000000,
                                      'sdrharness:point_index':0,'sdrharness:rf_bandwidth_hz':width,
                                      'sdrharness:gain_db':40}]
        for path in (data,meta,root/f'{tag}-report.json'):
            hashes[str(path.relative_to(root))]=affine.paired.sha(read(path))
        rows.append(dict(tag=tag,sweep_id=report['sweep_id'],session_generation=generation,
                         request_id=point['request_id'],sequence=point['sequence'],iq_sha256=affine.paired.sha(raw)))
    assert rows[0]['sequence']<rows[1]['sequence']<rows[2]['sequence']
    return dict(hashes=hashes,captures=rows,sdrd_pid=link['sdrd_pid'])


def inventory(root, tone):
    received = validate_capture_root(root,'rml')
    control = validate_capture_root(tone,'tone')
    assert received['sdrd_pid']==control['sdrd_pid']
    plan = document(root/'transmission-plan.json')
    assert plan['split']=='train' and plan['locked_test_read'] is False
    assert plan['rows']==[102400,102401,102403,102404] and plan['class_id']==0
    assert plan['dataset_nominal_snr_db']==30 and plan['payload_bytes']==32768
    for key,value in dict(center_hz=2440000000,rate_sps=2100000,bandwidth_hz=1500000,
                          tx_channel=0,tx_antenna='TX/RX').items():
        assert plan[key]==value,key
    assert affine.paired.sha(read(root/'train-tile.fc32'))==plan['payload_sha256']==affine.paired.SOURCE_HASH
    assert (plan['tx_samples'],plan['tx_nominal_seconds'],plan['tx_gain_db'],plan['complex_peak'])==(21000000,10,70,.2)
    source = {name:affine.paired.sha(read(root/name)) for name in
              ('train-tile.fc32','transmission-plan.json','tx-summary.json','tx-uhd.log')}
    return dict(schema_id='b210_v4_live_input_seal_v1',received=received,tone=control,source_hashes=source,
                recognizer_available=False,independent_labels=0)


def seal(root, tone):
    value = inventory(root,tone)
    with (root/'v4-input-seal.json').open('x') as output:
        json.dump(value,output,indent=2);output.write('\n')
    return value


def prepare(root, exploratory_source_failure=False):
    assert not exploratory_source_failure, 'no posthoc source-failure override in this unit'
    assert inventory(root,TONE)==document(root/'v4-input-seal.json'), 'sealed input changed'
    legacy = match.analyze(root,TONE)
    legacy['engineering_controls'] = match.assess_controls(legacy)
    tile = np.frombuffer(read(root/'train-tile.fc32'),dtype='<f4').reshape(4096,2)
    source = tile[:,0].astype(np.float64)+1j*tile[:,1].astype(np.float64)
    captures = {tag:match.read_iq(root,tag)[0] for tag in ('baseline','during-tx','after-tx')}
    cfo = legacy['tone']['frequency_difference_hz'];width=legacy['source_99_percent_half_width_hz']
    tone = match.assess_tone(legacy['tone'])
    details = dict(schema_id='b210_v4_live_affine_preparation_v1',
                   seal_sha256=affine.paired.sha(read(root/'v4-input-seal.json')),
                   legacy_envelope=legacy,tone_control=tone,source_control_passed=False,
                   engineering_source_qualified=False,recognizer_available=False,independent_labels=0,
                   production_profile_compatible=False,model_complex_offset=affine.FIT_SAMPLES)
    try:
        v4 = match.assess_centered_source_v4(source,captures,cfo,width)
    except ValueError as error:
        details['v4_unavailable_reason']=str(error)
        return details,{}
    details['v4_source']=v4
    details['engineering_source_qualified']=bool(tone['passed'] and v4['waveform_association_passed'])
    details['source_control_passed']=details['engineering_source_qualified']
    if not details['engineering_source_qualified']:
        return details,{}
    fit = v4['fit']
    reference = np.roll(match._source_band(source,width),fit['lag'])
    raw = captures['during-tx']
    prefix = match.centered_segment(raw,0,affine.FIT_SAMPLES,cfo+fit['residual_frequency_hz'],width).reshape(-1)
    try:
        coefficients = affine.fit_affine(np.tile(reference,7),prefix)
    except ValueError as error:
        details['affine_unavailable_reason']=str(error)
        return details,{}
    h,b,h0 = (affine.complex_value(coefficients[key]) for key in ('gain','bias','gain_only'))
    received = match.v4_heldout_windows(raw,cfo,width,fit)
    tone_only = match.v4_heldout_windows(raw,cfo,width,dict(passed=False))
    inputs = dict(source_band=reference,source_gain_phase=h*reference,source_with_bias=h*reference+b,
                  received_raw=raw[affine.FIT_SAMPLES:affine.FIT_SAMPLES+4096],
                  received_tone_band=tone_only[0],received_residual_band=received[0],received_debiased=received[0]-b)
    tensors = {name:affine.paired.normalize(affine.iq(value)) for name,value in inputs.items()}
    validation=[]
    for index,y in enumerate(received):
        power=float(np.mean(abs(y)**2));assert power>0
        validation.append(dict(complex_offset=affine.FIT_SAMPLES+index*4096,
            gain_only_residual_fraction=float(np.mean(abs(y-h0*reference)**2)/power),
            affine_residual_fraction=float(np.mean(abs(y-h*reference-b)**2)/power),
            centered_coherence=affine.fidelity.coherence(reference-reference.mean(),y-y.mean())))
    details.update(affine=coefficients,heldout_validation=validation,
                   model_inputs={name:dict(sha256=affine.paired.sha(data.tobytes()),bytes=data.nbytes) for name,data in tensors.items()})
    return details,tensors


def admitted_prepare(root, exploratory_source_failure=False):
    details,tensors=prepare(root,exploratory_source_failure)
    assert details['engineering_source_qualified'] and len(tensors)==7, 'source or affine gate failed; no model'
    return details,tensors


def continuity_summary(raw):
    """Posthoc fixed-window statistics, without source fitting or changed gates."""
    z=np.asarray(raw,dtype=np.complex128)
    assert z.shape==(65535,) and np.isfinite(z).all()
    rows=[]
    for index in range(15):
        y=z[index*4096:(index+1)*4096];yc=y-y.mean()
        row=dict(window=index+1,complex_offset=index*4096,
                 raw_rms=float(np.sqrt(np.mean(abs(y)**2))),raw_peak=float(np.max(abs(y))),
                 zero_complex_samples=int(np.count_nonzero(y==0)))
        if index:
            x=z[(index-1)*4096:index*4096];xc=x-x.mean()
            row['adjacent_raw_repeat_coherence']=affine.fidelity.coherence(xc,yc)
        rows.append(row)
    return dict(schema_id='b210_v4_posthoc_continuity_summary_v1',
                interpretation='fixed raw-window powers and adjacent repetition only; no new fit or qualification',
                model_windows=0,rows=rows)


def plot_failure(root,destination):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    assert inventory(root,TONE)==document(root/'v4-input-seal.json')
    prepared=document(root/'v4-affine-prepared.json')
    assert not prepared['engineering_source_qualified'], 'failure illustration only'
    summary=continuity_summary(match.read_iq(root,'during-tx')[0])
    figure,axes=plt.subplots(2,1,figsize=(9,6),constrained_layout=True)
    axes[0].plot(range(1,16),[row['raw_rms'] for row in summary['rows']],'o-',color='#b2182b')
    axes[0].set(ylabel='Raw complex RMS (ADC units)',title='All 15 complete raw windows; final partial window excluded')
    axes[1].plot(range(8,16),prepared['v4_source']['heldout_coherences']['during-tx'],'o-',color='#2166ac')
    axes[1].axhline(.6,color='#b2182b',ls='--',label='Fixed per-window minimum 0.6')
    axes[1].set(ylabel='Centered source coherence',xlabel='4096-sample capture window',ylim=(0,1.05))
    axes[1].legend()
    for axis in axes:
        axis.set_xlim(.5,15.5);axis.set_xticks(range(1,16));axis.grid(alpha=.2)
    figure.suptitle('New RX capture: source gate FAILED; no model inference')
    figure.savefig(destination,dpi=150);plt.close(figure)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--seal',action='store_true')
    modes.add_argument('--infer',action='store_true')
    modes.add_argument('--plot-failure',type=Path)
    args=parser.parse_args();assert args.directory==FEATURE and FEATURE.resolve()==FEATURE
    def stop(signum,frame):
        raise RuntimeError(f'stop signal {signum}')
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,stop)
    if args.seal:
        print(json.dumps(seal(FEATURE,TONE),indent=2))
    elif args.infer:
        asyncio.run(affine.infer(FEATURE,prepare_function=admitted_prepare,prefix_override='v4-affine'))
    elif args.plot_failure:
        print(json.dumps(plot_failure(FEATURE,args.plot_failure),indent=2))
    else:
        details,_=prepare(FEATURE)
        with (FEATURE/'v4-affine-prepared.json').open('x') as output:
            json.dump(details,output,indent=2);output.write('\n')
        print(json.dumps(details,indent=2))
