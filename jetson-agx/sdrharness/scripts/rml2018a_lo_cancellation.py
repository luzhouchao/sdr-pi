"""Experimental additive LO cancellation from packet guards, never source X.

This is an offline, buffered packet operation, not a production RF calibration.
The pilot CFO prior resolves the ~80 Hz aliases created by sparse guards.
"""
import numpy as np

import rml2018a_campaign as c

METHOD = 'pilot-anchored-guard-lo-cancellation-v1'
PLANE = 'received_payload_after_guard_lo_cancellation_before_rms'


def contract():
    return dict(method=METHOD, rate_sps=c.RATE, lo_offset_hz=250000,
        guard_edge_exclusion_samples=64, training_samples_per_guard=192,
        validation_samples_per_guard=192, minimum_complete_guards=2,
        frequency_prior='nominal TX LO offset + original known-marker CFO',
        frequency_search_halfwidth_hz=30, coarse_step_hz=1,
        minimum_guard_holdout_suppression_db=10,
        maximum_guard_amplitude_spread=.25, maximum_guard_phase_spread_rad=.25,
        maximum_corrected_pilot_residual_cfo_hz=25,
        source_payload_used_for_fit=False, labels_used_for_fit=False,
        payload_frequency_projection=False, refit_on_validation=False,
        failure_action='return unchanged original IQ with explicit reason',
        limitations=['requires correct repeated-frame timing and pilot CFO prior within30Hz of LO relation',
            'requires stable additive tone over buffered capture; guards may miss payload-only drift',
            'postprocessing quality is not a change to raw physical RF SINR',
            'not independently validated across24 classes or low source SNR'])


def guard_intervals(marker_offset, row_count, samples=c.RX_SAMPLES):
    c.require(type(marker_offset) is int and 0 <= marker_offset < samples, 'marker offset')
    c.require(type(row_count) is int and 1 <= row_count <= c.ROWS_PER_BATCH, 'row count')
    frame = 2*c.GUARD+c.MARKER+row_count*1024
    # Two256-sample guards join across a repeated-frame boundary.
    return [[at-448, at-64] for at in range(marker_offset % frame, samples+449, frame)
            if at-448 >= 0 and at-64 <= samples]


def filtered_pilot(z, fir, at, hz):
    """Equivalent FIR samples for the pilot, with the full convolution halo."""
    c.require(0 <= at <= len(z)-c.MARKER and len(fir) == 129, 'pilot FIR window')
    segment=z[max(0,at-64):min(len(z),at+c.MARKER+64)]
    segment=np.pad(segment,(max(0,64-at),max(0,at+c.MARKER+64-len(z))))
    return np.convolve(segment,fir,mode='valid')*np.exp(-2j*np.pi*hz*np.arange(at,at+c.MARKER)/c.RATE)


def cancel(raw, sync, row_count=24, *, pilot_only=False, frequency_fit=None):
    """Fit first half of guard interiors; validate later halves; subtract one tone.

    No source samples, modulation IDs, source Z, or model outputs are accepted.
    Original timing/CFO/phase are held fixed for the subsequent comparison.
    """
    z = np.asarray(raw, dtype=np.complex128)
    c.require(z.shape == (c.RX_SAMPLES,) and np.isfinite(z).all(), 'native IQ shape/finite')
    at = sync['payload_marker_offset']; hz = sync['estimated_cfo_hz']
    c.require(isinstance(hz, (int, float)) and np.isfinite(hz) and abs(hz) <= c.CFO_LIMIT_HZ,
              'finite registered pilot CFO')
    intervals = guard_intervals(at, row_count)
    c.require(at+c.MARKER+row_count*1024 <= len(z), 'complete payload')
    info = dict(method=METHOD, status='skipped', reason=None, guard_intervals=intervals,
                corrected_samples_sha256=None, parameters=contract())

    def skip(reason):
        info['reason'] = reason
        return z.copy(), info

    if len(intervals) < 2:
        return skip('insufficient_complete_guards')
    train = np.concatenate([np.arange(lo, lo+192) for lo, hi in intervals])
    heldout = np.concatenate([np.arange(lo+192, hi) for lo, hi in intervals])
    center = 250000+hz

    def project(frequency, indices=train):
        return np.mean(z[indices]*np.exp(-2j*np.pi*frequency*indices/c.RATE))

    frequencies = center+np.arange(-30,31,dtype=float)
    # Batch the short guard projections; preserve per-frequency reduction order.
    # This replaces61 Python/NumPy calls with one bounded61xguard operation.
    def projects(frequencies):
        return np.mean(z[train][None,:]*np.exp(
            -2j*np.pi*np.asarray(frequencies)[:,None]*train[None,:]/c.RATE),axis=1)

    if frequency_fit is None:
        best = int(np.argmax(abs(projects(frequencies))))
        if best in (0, len(frequencies)-1):
            return skip('frequency_at_prior_boundary')
        lo, hi = frequencies[best]-1, frequencies[best]+1
        for _ in range(50):
            left, right = lo+(hi-lo)/3, hi-(hi-lo)/3
            left_value,right_value=projects((left,right))
            if abs(left_value) > abs(right_value):
                hi = right
            else:
                lo = left
        frequency = float((lo+hi)/2)
    else:
        # Experimental batch proposal is bound to these exact training guards.
        # All heldout/pilot acceptance checks below still run on the CPU.
        frequency = frequency_fit.verify(z[train],train,center)
        info['frequency_fit_backend'] = frequency_fit.backend
        if frequency is None:return skip('frequency_at_prior_boundary')
        c.require(np.isfinite(frequency) and center-30 < frequency < center+30,'guard frequency prior')
    amplitude = project(frequency)
    indices = np.arange(len(z))
    prediction = amplitude*np.exp(2j*np.pi*frequency*indices/c.RATE)
    corrected = z-prediction
    original_power = float(np.mean(abs(z[heldout])**2))
    error_power = float(np.mean(abs(corrected[heldout])**2))
    suppression = float(10*np.log10(max(original_power,1e-30)/max(error_power,1e-30)))
    amplitudes = np.array([project(frequency, np.arange(a+192,b)) for a,b in intervals])
    spread = float(np.ptp(abs(amplitudes))/max(abs(amplitude),1e-15))
    phase_spread = float(np.max(abs(np.angle(amplitudes/amplitude)))) if abs(amplitude)>1e-15 else float(np.pi)
    info.update(frequency_hz=frequency, frequency_prior_hz=center,
        amplitude_real=float(amplitude.real), amplitude_imag=float(amplitude.imag),
        training_samples=len(train), heldout_samples=len(heldout),
        heldout_suppression_db=suppression, heldout_power_counts2=original_power,
        heldout_error_power_counts2=error_power, heldout_amplitude_spread=spread,
        heldout_phase_spread_rad=phase_spread)
    if suppression < 10:
        return skip('guard_holdout_not_predictable')
    if spread > .25 or phase_spread > .25:
        return skip('guard_tone_not_stable')
    # Independent check on the known repeated pilot; never use payload X.
    # An erroneous CFO prior one frame-alias away can predict all sparse guards.
    taps = np.arange(129)-64
    fir = (2*500000/c.RATE)*np.sinc(2*500000/c.RATE*taps)*np.hamming(129)
    fir /= fir.sum()
    pilot_offset = sync.get('marker_offset', at)
    c.require(type(pilot_offset) is int and 0 <= pilot_offset <= len(z)-c.MARKER,
              'complete anchor pilot')
    if pilot_only:
        pilot = filtered_pilot(corrected,fir,pilot_offset,hz)
    else:
        filtered = np.convolve(corrected,fir,mode='same')*np.exp(-2j*np.pi*hz*indices/c.RATE)
        pilot = filtered[pilot_offset:pilot_offset+c.MARKER]
    a,b = pilot[64:448],pilot[576:960]
    coherence = float(abs(np.vdot(a,b))/max(np.linalg.norm(a)*np.linalg.norm(b),1e-30))
    residual = float(np.angle(np.vdot(a,b))*c.RATE/(2*np.pi*512))
    info.update(corrected_pilot_residual_cfo_hz=residual, corrected_pilot_half_coherence=coherence)
    if coherence < .95 or abs(residual) > 25:
        return skip('pilot_does_not_confirm_frequency_prior')
    info.update(status='applied', corrected_samples_sha256=c.digest(corrected.astype('<c16').tobytes()))
    return corrected,info


def payload(raw, sync, row_count=24):
    """Use exactly the original synchronization, with no timing or source refit."""
    n = np.arange(len(raw)); start = sync['payload_marker_offset']+c.MARKER
    rotated = raw*np.exp(-2j*np.pi*sync['estimated_cfo_hz']*n/c.RATE+1j*sync['phase_rotation_rad'])
    return rotated[start:start+row_count*1024].reshape(row_count,1024)


def quality(reference, received, source_snr_db, cancellation):
    result = c.receive_quality('synchronized', reference, received, source_snr_db)
    c.validate_receive_quality(result,source_snr_db)
    result['rx_sinr_reference_plane'] = PLANE
    result['rx_interference_cancellation'] = METHOD if cancellation['status']=='applied' else 'none_skipped'
    # This subtracts an independently estimated additive waveform. It does not
    # apply a payload filter or redefine the source-noise fraction from Z.
    return result
