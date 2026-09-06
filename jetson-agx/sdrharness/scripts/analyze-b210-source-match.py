#!/usr/bin/env python3
"""Exploratory link evidence only; does not alter recognizer RF-v1 or admission."""
if not __debug__:
    raise RuntimeError('optimized Python disables validation')

import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

RATE = 2100000
PERIOD = 4096


def read_iq(directory, tag):
    files = list((directory/tag).glob('*.sigmf-data'))
    assert len(files)==1 and files[0].resolve().parent==directory/tag
    raw=files[0].read_bytes()
    assert len(raw)==65535*4
    iq=np.frombuffer(raw,dtype='<i2').reshape(-1,2).astype(float)
    return iq[:,0]+1j*iq[:,1], hashlib.sha256(raw).hexdigest()


def tone_metrics(directory):
    results={}
    spectra={}
    for tag in ['baseline','during-tx','after-tx']:
        z,digest=read_iq(directory,tag)
        window=np.hanning(len(z))
        power=abs(np.fft.fft((z-z.mean())*window))**2/(32768**2*window.sum()**2)
        freq=np.fft.fftfreq(len(z),1/2500000)
        search=np.flatnonzero(abs(freq-100000)<5000)
        index=search[np.argmax(power[search])]
        spectra[tag]=power
        results[tag]=dict(iq_sha256=digest,peak_offset_hz=float(freq[index]),
            target_region_peak_dbfs=float(10*np.log10(power[index])),
            spectral_median_dbfs=float(10*np.log10(np.median(power[abs(freq)>5000]))))
        if tag=='during-tx':observed_index=index
    for tag in results:
        results[tag]['same_observed_bin_dbfs']=float(10*np.log10(spectra[tag][observed_index]))
    return dict(cases=results,frequency_difference_hz=results['during-tx']['peak_offset_hz']-100000)


def source_bandwidth(reference):
    power=abs(np.fft.fft(reference))**2
    freq=abs(np.fft.fftfreq(len(reference),1/RATE))
    order=np.argsort(freq)
    limit=freq[order[np.searchsorted(np.cumsum(power[order])/power.sum(),.99)]]
    return int(np.ceil(limit/1000)*1000)


def envelope_correlations(iq,reference,frequency_difference,half_width):
    assert len(iq)==65535 and len(reference)==PERIOD
    corrected=iq*np.exp(-2j*np.pi*frequency_difference*np.arange(len(iq))/RATE)
    filtered=np.fft.ifft(np.fft.fft(corrected)*(abs(np.fft.fftfreq(len(iq),1/RATE))<=half_width))
    source=np.fft.ifft(np.fft.fft(reference)*(abs(np.fft.fftfreq(PERIOD,1/RATE))<=half_width))
    target=abs(source)-np.mean(abs(source))
    envelope=abs(filtered[:15*PERIOD].reshape(15,PERIOD))
    envelope-=envelope.mean(axis=1,keepdims=True)
    cc=np.fft.ifft(np.fft.fft(envelope,axis=1)*np.fft.fft(target).conj(),axis=1).real
    cc/=np.sqrt((envelope**2).sum(axis=1)[:,None]*(target**2).sum())
    assert np.isfinite(cc).all()
    return cc


# Fixed before RX40 control acquisition; engineering source checks only.
CONTROL_LIMITS = dict(tone_control_margin_db=20., tone_spectral_margin_db=20.,
                      during_correlation_minimum=.5, off_correlation_absolute_maximum=.2,
                      source_control_margin_minimum=.3)


def assess_tone(tone):
    cases=tone['cases'];during=cases['during-tx']
    differences=[during['same_observed_bin_dbfs']-cases[tag]['same_observed_bin_dbfs']
                 for tag in ('baseline','after-tx')]
    spectral=during['same_observed_bin_dbfs']-during['spectral_median_dbfs']
    values=[*differences,spectral,tone['frequency_difference_hz']]
    if not np.isfinite(values).all():raise ValueError('nonfinite tone evidence')
    return dict(passed=min(differences)>=CONTROL_LIMITS['tone_control_margin_db']
                and spectral>=CONTROL_LIMITS['tone_spectral_margin_db'],
                control_margins_db=differences,spectral_margin_db=spectral)


def assess_controls(result):
    tone=assess_tone(result['tone']);cases=result['cases']
    during=cases['during-tx']['later_eight_fixed_lag_median']
    off=[abs(cases[tag]['later_eight_fixed_lag_median']) for tag in ('baseline','after-tx')]
    if not np.isfinite([during,*off]).all():raise ValueError('nonfinite source evidence')
    source_pass=(during>=CONTROL_LIMITS['during_correlation_minimum']
                 and max(off)<=CONTROL_LIMITS['off_correlation_absolute_maximum']
                 and during-max(off)>=CONTROL_LIMITS['source_control_margin_minimum'])
    return dict(schema_id='b210_rx40_engineering_controls_v1',limits=CONTROL_LIMITS.copy(),
                tone=tone,source_passed=source_pass,passed=bool(tone['passed'] and source_pass),
                during_correlation=during,maximum_off_absolute_correlation=max(off),
                source_control_margin=during-max(off),independent_labels=0,
                recognizer_available=False,rf_v1_50db_acceptance=False)


def analyze(root,tone_directory):
    tone=tone_metrics(tone_directory)
    raw_tile=(root/'train-tile.fc32').read_bytes()
    plan=json.loads((root/'transmission-plan.json').read_text())
    assert len(raw_tile)==32768 and hashlib.sha256(raw_tile).hexdigest()==plan['payload_sha256']
    assert plan['split']=='train' and plan['locked_test_read'] is False
    tile=np.frombuffer(raw_tile,dtype='<f4').reshape(-1,2)
    reference=tile[:,0]+1j*tile[:,1]
    half_width=source_bandwidth(reference)
    # The band comes from source IQ alone; frequency difference comes from the
    # separate tone. This is retrospective engineering analysis, not a new
    # independent acceptance split or a production calibration/rejection rule.
    correlations={};hashes={}
    for tag in ['baseline','during-tx','after-tx']:
        iq,hashes[tag]=read_iq(root,tag)
        correlations[tag]=envelope_correlations(iq,reference,tone['frequency_difference_hz'],half_width)
    lag=int(np.median(correlations['during-tx'][:7].argmax(axis=1)))
    cases={}
    for tag,cc in correlations.items():
        cases[tag]=dict(iq_sha256=hashes[tag],fixed_lag=lag,
            later_eight_fixed_lag_correlations=list(map(float,cc[7:,lag])),
            later_eight_fixed_lag_median=float(np.median(cc[7:,lag])),
            all_window_best_lag_median=float(np.median(cc.max(axis=1))),
            all_window_best_lags=list(map(int,cc.argmax(axis=1))))
    result=dict(schema_version=1,tone=tone,source_99_percent_half_width_hz=half_width,
        alignment_method='median best lag in first seven during-TX windows; apply unchanged to last eight and both TX-off controls',
        interpretation='exploratory source-specific RF link evidence, not model accuracy or independent RF admission',
        raw_broadband_test_replaced=False,recognizer_preprocess_modified=False,cases=cases)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--tone-directory',type=Path,help='Separate existing tone feature; no IQ copy required')
    p.add_argument('--assess-controls',action='store_true',help='Apply preregistered RX40 engineering gates')
    a=p.parse_args();root=a.directory
    assert root.resolve()==root and root.parent==Path('/var/tmp/sdrharness-dev')
    tone_directory=a.tone_directory or root/'tone'
    assert tone_directory.resolve()==tone_directory
    result=analyze(root,tone_directory)
    if a.assess_controls:result['engineering_controls']=assess_controls(result)
    (root/'source-matched-analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
