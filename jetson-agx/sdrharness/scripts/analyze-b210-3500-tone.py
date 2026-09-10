#!/usr/bin/env python3
"""Read-only 3500-MHz tone trial validation and reproducible signal assessment."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import numpy as np

ROOT=Path('/var/tmp/sdrharness-dev/b210-3500-spring-20260910a')
REPO=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('tone_match',Path(__file__).with_name('analyze-b210-source-match.py'))
match=importlib.util.module_from_spec(spec);spec.loader.exec_module(match)


def prepare(expected_tx_gain=0, expected_rx_gain=20, expected_center_hz=3500000000):
    audit=json.loads((ROOT/'link-summary.json').read_text())
    assert audit['status']=='transport_completed_pending_signal_analysis'
    assert type(expected_tx_gain) is int and type(expected_rx_gain) is int
    assert type(expected_center_hz) is int and expected_center_hz in (2440000000,3500000000)
    assert (expected_tx_gain,expected_rx_gain) in (((70,50),) if expected_center_hz == 2440000000 else ((0,20),(10,20),(20,20),(70,50)))
    assert audit['center_hz']==expected_center_hz and audit['rx_gain_db']==expected_rx_gain and audit['tx_gain_db']==expected_tx_gain
    assert audit['remote_tx_stopped'] and not audit['restoration_errors'] and audit['tx_exit_code']==0
    assert audit['radio_before']==audit['radio_after']
    log=(ROOT/'tx-uhd.log').read_text()
    for label,value in [('Actual TX Rate',2.5),('Actual TX Freq',expected_center_hz/1e6),('Actual TX Gain',float(expected_tx_gain)),('Actual TX Bandwidth',500000.)]:
        values=re.findall(re.escape(label)+r': ([\d.+-]+)',log)
        assert len(values)==1 and float(values[0])==value,label
    assert 'LO: locked' in log and '--nsamps 25000000' in audit['tx_command']
    rows={};hashes={};iq={}
    for index,tag in enumerate(('baseline','during-tx','after-tx')):
        report=json.loads((ROOT/f'{tag}-report.json').read_text());plan=audit['plans'][index]
        assert report['sweep_id']==plan['sweep_id'] and report['session_generation']==plan['session_generation']
        assert report['backend']=='agx_iq_software_aggregate' and len(report['points'])==1
        point=report['points'][0]
        for k,v in dict(requested_center_hz=expected_center_hz,sample_rate_hz=2500000,rf_bandwidth_hz=1000000,
            captured_samples=65535,dropped_samples=0,overflow=False,clipped_samples=0,status_flags=0,
            point_index=0,session_generation=audit['generation']+index).items():assert point[k]==v,k
        assert abs(point['actual_center_hz']-expected_center_hz)<=2
        assert point['health']==dict(healthy=True,flags=0,source='iio_adapter')
        assert point['timeout']['limit_ms']==1000 and not point['timeout']['timed_out']
        assert point['rx_input']['verified'] and point['rx_input']['front_panel_port']=='RX1'
        assert point['rx_input']['logical_channel']=='RX0' and point['rx_input']['rf_port_select']=='A_BALANCED'
        assert point['request_id']>0 and point['sequence']>0
        dataset=report['dataset'];assert dataset['bytes']==262140 and dataset['datatype']=='ci16_le' and dataset['format']=='sigmf'
        data,meta=Path(dataset['data_path']),Path(dataset['metadata_path'])
        assert data.resolve().parent==meta.resolve().parent==ROOT/tag
        metadata=json.loads(meta.read_text());assert metadata['global']['core:sample_rate']==2500000
        assert metadata['global']['core:datatype']=='ci16_le'
        assert metadata['captures']==[{'core:sample_start':0,'core:frequency':expected_center_hz,'sdrharness:point_index':0,
            'sdrharness:rf_bandwidth_hz':1000000,'sdrharness:gain_db':expected_rx_gain}]
        z,digest=match.read_iq(ROOT,tag);iq[tag]=z
        rms=np.array([np.sqrt(np.mean(abs(z[i:i+128])**2)) for i in range(0,len(z),128)])
        rows[tag]=dict(request_id=point['request_id'],sequence=point['sequence'],session_generation=point['session_generation'],
            raw_rms_p50=float(np.median(rms)),raw_rms_max=float(rms.max()),band_power_dbfs=point['band_power_dbfs'],iq_sha256=digest)
        for p in (data,meta,ROOT/f'{tag}-report.json'):hashes[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    tone=match.tone_metrics(ROOT)
    result=dict(schema_id='b210_3500_tone_analysis_v1' if expected_center_hz == 3500000000 else 'b210_2440_return_tone_analysis_v1',tone=tone,assessment=match.assess_tone(tone),native=rows,hashes=hashes,
        thresholds=match.CONTROL_LIMITS,tx_log_sha256=hashlib.sha256(log.encode()).hexdigest(),
        tx_bandwidth_hz=500000,uhd_bandwidth_log_label='example prints MHz after Hz numeric value; --bw help specifies Hz',
        uhd_tail_markers=log.split('Done!')[-1].strip(),continuous_tx_proven=False,
        candidate_frequency_is_verified_cfo=False,normalization='legacy tone FFT uses32768; differences in dB only, no calibrated dBm',
        model_calls=0,independent_labels=0,recognizer_available=False)
    return result,iq


def plot(iq):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(12,4),constrained_layout=True)
    for tag,z in iq.items():
        w=np.hanning(len(z));freq=np.fft.fftfreq(len(z),1/2500000)
        power=abs(np.fft.fft((z-z.mean())*w))**2/w.sum()**2
        mask=abs(freq-100000)<5000
        axes[0].plot(freq[mask]/1000,10*np.log10(np.maximum(power[mask],1e-30)),label=tag,lw=.8)
        rms=[np.sqrt(np.mean(abs(z[i:i+128])**2)) for i in range(0,len(z),128)]
        axes[1].plot(np.arange(len(rms))*128/2500000*1000,rms,label=tag,lw=.8)
    axes[0].set(xlabel='RX baseband offset (kHz)',ylabel='Hann-bin power (dB ADC²)',title='Registered +100kHz search region')
    axes[1].set(xlabel='Time inside separate capture (ms)',ylabel='128-sample ADC RMS',title='Stopped / TX / stopped (not simultaneous)')
    for ax in axes:ax.grid(alpha=.2);ax.legend()
    fig.suptitle('3500 MHz | TX gain0, RX gain20 | tone qualification failed')
    fig.savefig(REPO/'docs/evidence/B210_3500_TONE_2026-09-10.png',dpi=150);plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--verify',action='store_true');p.add_argument('--plot',action='store_true');args=p.parse_args()
    result,iq=prepare()
    if args.verify:assert result==json.loads((ROOT/'analysis.json').read_text());print('native association and exact analysis replay passed')
    elif not args.plot:(ROOT/'analysis.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['assessment']))
    if args.plot:plot(iq)
