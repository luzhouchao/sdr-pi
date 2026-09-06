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


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',type=Path,required=True)
    a=p.parse_args();root=a.directory
    assert root.resolve()==root and root.parent==Path('/var/tmp/sdrharness-dev')
    tone=tone_metrics(root/'tone')
    tile=np.fromfile(root/'train-tile.fc32',dtype='<f4').reshape(-1,2)
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
    (root/'source-matched-analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
