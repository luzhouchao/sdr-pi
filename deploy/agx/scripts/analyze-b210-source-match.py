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


# A separate numerical candidate. Never substitutes for v1 controls.
CENTERED_LIMITS = dict(prefix_coherence_minimum=.2, phase_rmse_maximum_rad=.2,
                       residual_frequency_maximum_hz=200., source_effective_bins_minimum=8.,
                       heldout_median_minimum=.8, heldout_minimum=.6,
                       off_maximum=.2, source_off_margin_minimum=.6, surrogate_maximum=.2)
FIT_SAMPLES = 7*PERIOD
END_SAMPLES = 15*PERIOD
SURROGATE_SEEDS = (9060701, 9060702, 9060703)
V3_SURROGATE_SEEDS = tuple(range(9060701, 9060732))
V3_SOURCE_WRONG_MARGIN = .3
V4_PHASE_NULL_FAMILY_BUDGET = 1e-4
V4_PHASE_DIRECTIONS = 16
V4_OFF_WINDOWS = 16
V4_OFF_THRESHOLD_CEILING = .5


def _complex_array(value, size):
    array = np.asarray(value, dtype=np.complex128)
    if array.shape != (size,) or not np.isfinite(array).all():
        raise ValueError('centered association requires exact finite complex arrays')
    return array


def _source_band(source, half_width):
    bins = abs(np.fft.fftfreq(PERIOD, 1/RATE)) <= half_width
    return np.fft.ifft(np.fft.fft(source)*bins)


def centered_segment(raw, start, end, frequency, half_width):
    """Slice raw samples before any FFT; keep the original time origin."""
    segment = raw[start:end]*np.exp(-2j*np.pi*frequency*np.arange(start, end)/RATE)
    bins = abs(np.fft.fftfreq(len(segment), 1/RATE)) <= half_width
    return np.fft.ifft(np.fft.fft(segment)*bins).reshape(-1, PERIOD)


def _centered_correlations(windows, source, all_lags=False):
    x = source-source.mean()
    y = windows-windows.mean(axis=1, keepdims=True)
    denominator = np.sqrt(np.sum(abs(y)**2, axis=1)*np.sum(abs(x)**2))
    if not np.isfinite(denominator).all():
        raise ValueError('nonfinite centered power')
    if all_lags:
        products = np.fft.ifft(np.fft.fft(y, axis=1)*np.fft.fft(x).conj(), axis=1)
        denominator = denominator[:, None]
    else:
        products = np.sum(y*x.conj(), axis=1)
    # Zero-power stopped-TX controls have zero correlation, not NaN.
    return np.divide(products, denominator, out=np.zeros_like(products), where=denominator>0)


def fit_centered_source(raw, source, tone_cfo, half_width):
    """Only the first seven raw windows may select lag or residual frequency."""
    prefix = centered_segment(raw, 0, FIT_SAMPLES, tone_cfo, half_width)
    reference = _source_band(source, half_width)
    correlations = _centered_correlations(prefix, reference, all_lags=True)
    lag = int(np.argmax(np.mean(abs(correlations), axis=0)))
    values = correlations[:, lag]
    phase = np.unwrap(np.angle(values))
    times = (np.arange(7)+.5)*PERIOD/RATE
    design = np.column_stack((times, np.ones(7)))
    slope, intercept = np.linalg.lstsq(design, phase, rcond=None)[0]
    rmse = float(np.sqrt(np.mean((phase-design @ [slope, intercept])**2)))
    residual = float(slope/(2*np.pi))
    minimum = float(np.min(abs(values)))
    passed = (minimum >= CENTERED_LIMITS['prefix_coherence_minimum']
              and rmse <= CENTERED_LIMITS['phase_rmse_maximum_rad']
              and abs(residual) <= CENTERED_LIMITS['residual_frequency_maximum_hz'])
    return dict(lag=lag, residual_frequency_hz=residual, phase_rmse_rad=rmse,
                prefix_minimum_coherence=minimum, passed=bool(passed),
                fit_complex_samples=FIT_SAMPLES, phase_alias_period_hz=RATE/PERIOD)


def _heldout_centered(raw, source, tone_cfo, half_width, fit):
    # A failed estimate is not an exemption for negative controls. Score them
    # with the unrefined tone frequency, preserving the prefix-selected lag.
    frequency = tone_cfo+(fit['residual_frequency_hz'] if fit['passed'] else 0.)
    windows = centered_segment(raw, FIT_SAMPLES, END_SAMPLES, frequency, half_width)
    reference = np.roll(_source_band(source, half_width), fit['lag'])
    return list(map(float, abs(_centered_correlations(windows, reference))))


def _phase_surrogate(source, seed):
    spectrum = np.fft.fft(source)
    rng = np.random.default_rng(seed)
    wrong_spectrum = abs(spectrum)*np.exp(1j*rng.uniform(-np.pi, np.pi, PERIOD))
    wrong_spectrum[0] = spectrum[0]  # Preserve genuine source DC, too.
    return np.fft.ifft(wrong_spectrum)


def _centered_surrogate(source, received, tone_cfo, half_width, seed):
    wrong = _phase_surrogate(source, seed)
    wrong_fit = fit_centered_source(received, wrong, tone_cfo, half_width)
    scores = _heldout_centered(received, wrong, tone_cfo, half_width, wrong_fit)
    return dict(seed=seed, fit=wrong_fit, heldout_coherences=scores,
                maximum_coherence=max(scores))


def assess_centered_source(reference, captures, tone_cfo, half_width):
    """Numerical source association only; no RF qualification or model input changes.

    The caller still owes raw hash/identity, tone, acquisition quality and radio
    restoration checks. This API cannot promote a live or production capability.
    """
    source = _complex_array(reference, PERIOD)
    if set(captures) != {'baseline', 'during-tx', 'after-tx'}:
        raise ValueError('both stopped-TX controls and during-TX capture are required')
    raw = {tag: _complex_array(value, 65535) for tag, value in captures.items()}
    if (not np.isfinite([tone_cfo, half_width]).all() or abs(tone_cfo)>5000
            or not 0<half_width<RATE/2):
        raise ValueError('invalid tone frequency or source bandwidth')
    band = _source_band(source, half_width)
    power = abs(np.fft.fft(band-band.mean()))**2
    # Suppress numerical DC residue in the effective-bin statistic.
    power[0] = 0
    total = float(power.sum())
    if not np.isfinite(total) or total<=0:
        raise ValueError('source has no finite non-DC power')
    weights = power/total
    effective_bins = float(1/np.sum(weights**2))
    if effective_bins < CENTERED_LIMITS['source_effective_bins_minimum']:
        raise ValueError('source is too spectrally concentrated for association')
    fit = fit_centered_source(raw['during-tx'], source, tone_cfo, half_width)
    cases = {tag: _heldout_centered(value, source, tone_cfo, half_width, fit)
             for tag, value in raw.items()}
    surrogate_results = [_centered_surrogate(source, raw['during-tx'], tone_cfo, half_width, seed)
                         for seed in SURROGATE_SEEDS]
    during_median = float(np.median(cases['during-tx']))
    during_minimum = min(cases['during-tx'])
    off_maximum = max(cases['baseline']+cases['after-tx'])
    surrogate_maximum = max(row['maximum_coherence'] for row in surrogate_results)
    checks = dict(prefix_estimate=fit['passed'],
                  during_median=during_median>=CENTERED_LIMITS['heldout_median_minimum'],
                  during_every_window=during_minimum>=CENTERED_LIMITS['heldout_minimum'],
                  stopped_controls=off_maximum<=CENTERED_LIMITS['off_maximum'],
                  source_off_margin=during_median-off_maximum>=CENTERED_LIMITS['source_off_margin_minimum'],
                  same_spectrum_wrong_sources=surrogate_maximum<=CENTERED_LIMITS['surrogate_maximum'])
    return dict(schema_id='b210_centered_source_candidate_v2', limits=CENTERED_LIMITS.copy(),
                waveform_association_passed=all(checks.values()), checks=checks, fit=fit,
                source_effective_bins=effective_bins, heldout_coherences=cases,
                during_median=during_median, during_minimum=during_minimum,
                off_maximum=off_maximum, surrogate_maximum=surrogate_maximum,
                surrogates=surrogate_results, live_rf_qualified=False, recognizer_available=False,
                independent_labels=0, production_preprocess_changed=False,
                interpretation='candidate numerical association; requires separate live RF controls')


def assess_centered_source_v3(reference, captures, tone_cfo, half_width):
    """Compare the weakest source window to 31 spectrum-matched searched nulls.

    This finite diagnostic contrast is not a calibrated hypothesis test. All
    absolute source, stopped-TX and estimator gates remain mandatory.
    """
    result = assess_centered_source(reference, captures, tone_cfo, half_width)
    result['legacy_v2_three_surrogate_passed'] = result['waveform_association_passed']
    source = _complex_array(reference, PERIOD)
    received = _complex_array(captures['during-tx'], 65535)
    result['surrogates'].extend(
        _centered_surrogate(source, received, tone_cfo, half_width, seed)
        for seed in V3_SURROGATE_SEEDS[len(SURROGATE_SEEDS):])
    result['surrogate_maximum'] = max(row['maximum_coherence'] for row in result['surrogates'])
    result['source_wrong_margin'] = result['during_minimum']-result['surrogate_maximum']
    result['limits'].pop('surrogate_maximum')
    result['limits']['source_wrong_margin_minimum'] = V3_SOURCE_WRONG_MARGIN
    result['checks'].pop('same_spectrum_wrong_sources')
    result['checks']['source_wrong_margin'] = result['source_wrong_margin']>=V3_SOURCE_WRONG_MARGIN
    result['waveform_association_passed'] = all(result['checks'].values())
    result['schema_id'] = 'b210_centered_source_candidate_v3'
    result['surrogate_count'] = len(result['surrogates'])
    result['interpretation'] = 'finite searched spectrum-matched contrast; not a p-value or live RF qualification'
    return result


def v4_heldout_windows(raw, tone_cfo, half_width, fit):
    """Independent raw-window FFTs, with a fixed capture time origin."""
    frequency = tone_cfo+(fit['residual_frequency_hz'] if fit['passed'] else 0.)
    times = np.arange(FIT_SAMPLES, END_SAMPLES).reshape(8, PERIOD)/RATE
    windows = raw[FIT_SAMPLES:END_SAMPLES].reshape(8, PERIOD)*np.exp(-2j*np.pi*frequency*times)
    bins = abs(np.fft.fftfreq(PERIOD, 1/RATE))<=half_width
    return np.fft.ifft(np.fft.fft(windows, axis=1)*bins, axis=1)


def phase_null_stopped_control(reference, windows):
    """Conditional independent-uniform Fourier-phase bound, not RF calibration.

    P(max_j |correlation_j| > threshold_j) <= family_budget only under
    the stated phase model. A large formal bound fails identifiability.
    """
    source = _complex_array(reference, PERIOD)
    noise = np.asarray(windows, dtype=np.complex128)
    if noise.shape!=(V4_OFF_WINDOWS, PERIOD) or not np.isfinite(noise).all():
        raise ValueError('sixteen finite stopped windows required')
    x_power = abs(np.fft.fft(source-source.mean()))**2
    y_power = abs(np.fft.fft(noise-noise.mean(axis=1, keepdims=True), axis=1))**2
    x_power[0] = 0
    y_power[:, 0] = 0
    x_total = float(x_power.sum())
    y_total = y_power.sum(axis=1)
    if not np.isfinite(x_total) or x_total<=0 or not np.isfinite(y_total).all():
        raise ValueError('invalid centered spectral power')
    p = x_power/x_total
    q = np.divide(y_power, y_total[:, None], out=np.zeros_like(y_power), where=y_total[:, None]>0)
    overlap = np.sum(p*q, axis=1)
    coefficient = np.log(V4_PHASE_DIRECTIONS*V4_OFF_WINDOWS/V4_PHASE_NULL_FAMILY_BUDGET)
    thresholds = np.sqrt(overlap*coefficient)/np.cos(np.pi/V4_PHASE_DIRECTIONS)
    correlations = abs(_centered_correlations(noise, source))
    rows = []
    for index, (score, threshold, variance, power) in enumerate(zip(correlations, thresholds, overlap, y_total)):
        identifiable = bool(threshold<V4_OFF_THRESHOLD_CEILING)
        rows.append(dict(case='baseline' if index<8 else 'after-tx',
                         complex_offset=FIT_SAMPLES+(index%8)*PERIOD,
                         correlation=float(score), threshold=float(threshold),
                         spectral_overlap=float(variance),
                         overlap_effective_dimension=float(1/variance) if variance>0 else None,
                         zero_centered_power=bool(power==0), identifiable=identifiable,
                         passed=bool(identifiable and score<=threshold)))
    return dict(passed=all(row['passed'] for row in rows), windows=rows,
                conditional_family_budget=V4_PHASE_NULL_FAMILY_BUDGET,
                directions=V4_PHASE_DIRECTIONS, window_count=V4_OFF_WINDOWS,
                threshold_strict_ceiling=V4_OFF_THRESHOLD_CEILING,
                null_assumption='independent uniform non-DC Fourier phases conditional on amplitudes',
                assumption_verified_for_input=False, production_calibration=False)


def assess_centered_source_v4(reference, captures, tone_cfo, half_width):
    """V4 uses raw-window FFTs and an explicit conditional stopped-noise bound."""
    result = assess_centered_source_v3(reference, captures, tone_cfo, half_width)
    result['legacy_v3_passed'] = result['waveform_association_passed']
    source = _complex_array(reference, PERIOD)
    raw = {tag: _complex_array(value, 65535) for tag, value in captures.items()}
    aligned = np.roll(_source_band(source, half_width), result['fit']['lag'])
    windows = {tag: v4_heldout_windows(value, tone_cfo, half_width, result['fit'])
               for tag, value in raw.items()}
    result['heldout_coherences'] = {tag: list(map(float, abs(_centered_correlations(value, aligned))))
                                   for tag, value in windows.items()}
    for row in result['surrogates']:
        wrong = _phase_surrogate(source, row['seed'])
        wrong_aligned = np.roll(_source_band(wrong, half_width), row['fit']['lag'])
        wrong_windows = v4_heldout_windows(raw['during-tx'], tone_cfo, half_width, row['fit'])
        row['heldout_coherences'] = list(map(float, abs(_centered_correlations(wrong_windows, wrong_aligned))))
        row['maximum_coherence'] = max(row['heldout_coherences'])
    cases = result['heldout_coherences']
    result['during_median'] = float(np.median(cases['during-tx']))
    result['during_minimum'] = min(cases['during-tx'])
    result['off_maximum'] = max(cases['baseline']+cases['after-tx'])
    result['surrogate_maximum'] = max(row['maximum_coherence'] for row in result['surrogates'])
    result['source_wrong_margin'] = result['during_minimum']-result['surrogate_maximum']
    control = phase_null_stopped_control(aligned, np.concatenate([windows['baseline'], windows['after-tx']]))
    result['stopped_phase_null'] = control
    result['checks'].update(
        during_median=result['during_median']>=CENTERED_LIMITS['heldout_median_minimum'],
        during_every_window=result['during_minimum']>=CENTERED_LIMITS['heldout_minimum'],
        stopped_controls=control['passed'],
        source_off_margin=result['during_median']-result['off_maximum']>=CENTERED_LIMITS['source_off_margin_minimum'],
        source_wrong_margin=result['source_wrong_margin']>=V3_SOURCE_WRONG_MARGIN)
    result['limits'].pop('off_maximum')
    result['limits'].update(off_phase_family_budget=V4_PHASE_NULL_FAMILY_BUDGET,
                            off_threshold_strict_ceiling=V4_OFF_THRESHOLD_CEILING)
    result['schema_id'] = 'b210_centered_source_candidate_v4'
    result['heldout_transform'] = 'independent_raw_4096_window_fft_v1'
    result['waveform_association_passed'] = all(result['checks'].values())
    result['interpretation'] = 'conditional phase-null stopped control and finite searched source contrast; not live RF qualification'
    return result


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
