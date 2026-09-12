"""Experimental guard-tone validation, separate from v1 total-residual gating.

No guard is discarded, no validation refit, no source payload access. A block
uncertainty margin checks the predicted coherent tone while leaving broadband
residual in the IQ. The margin is empirical, not a calibrated confidence bound.
"""
import numpy as np
import rml2018a_campaign as c
import rml2018a_lo_cancellation as v1

METHOD = 'guard-tone-block-margin-v1'
PLANE = 'received_payload_after_guard_tone_block_margin_before_rms'


def contract():
    return dict(method=METHOD, frequency_fit='unchanged v1 training guards and pilot prior',
        validation='every training and heldout guard half; eight contiguous24-sample block phasors',
        maximum_relative_tone_error_margin=float(np.sqrt(.1)), block_standard_error_multiplier=4,
        minimum_complete_guards=2, minimum_tone_margin_db=10,
        unchanged_v1_total_residual_gate_db=10, v1_results_preserved=True,
        maximum_amplitude_spread=.25, maximum_phase_spread_rad=.25,
        maximum_pilot_residual_cfo_hz=25, minimum_pilot_half_coherence=.95,
        source_payload_used=False, discarded_guards=0, validation_refit=False,
        failure_action='unchanged raw IQ with explicit reason',
        limitations=['new empirical tone-error criterion, not equivalent to v1 total-power suppression',
            'block standard error is not a calibrated confidence bound under arbitrary correlated interference',
            'guard-only validation cannot detect payload-only LO changes',
            'does not remove broadband noise, source noise, or payload distortion'])


def cancel(raw, sync, row_count=24):
    z = np.asarray(raw, dtype=np.complex128)
    _, old = v1.cancel(z, sync, row_count)
    info = dict(method=METHOD, status='skipped', reason=None, contract=contract(),
                v1=old, halves=[], corrected_samples_sha256=None)

    def skip(reason):
        info['reason'] = reason
        return z.copy(), info

    if old['status'] != 'applied' and old['reason'] != 'guard_holdout_not_predictable':
        return skip('v1_'+old['reason'])
    amplitude = complex(old['amplitude_real'], old['amplitude_imag'])
    frequency = old['frequency_hz']
    if abs(amplitude) < 1e-12:
        return skip('tone_not_identifiable')
    heldout_amplitudes = []
    for start, stop in old['guard_intervals']:
        for kind, at in (('training', start), ('heldout', start+192)):
            n = np.arange(at, at+192)
            demodulated = z[n]*np.exp(-2j*np.pi*frequency*n/c.RATE)
            blocks = demodulated.reshape(8, 24).mean(axis=1)
            observed = blocks.mean()
            stderr = float(np.sqrt(np.sum(abs(blocks-observed)**2)/(7*8)))
            margin = float((abs(observed-amplitude)+4*stderr)/abs(amplitude))
            info['halves'].append(dict(start=at, stop=at+192, kind=kind,
                observed_amplitude=[float(observed.real),float(observed.imag)],
                standard_error=stderr, relative_error_margin=margin,
                total_residual_power_counts2=float(np.mean(abs(demodulated-amplitude)**2))))
            if kind == 'heldout': heldout_amplitudes.append(observed)
    info['maximum_relative_error_margin'] = max(h['relative_error_margin'] for h in info['halves'])
    if info['maximum_relative_error_margin'] > np.sqrt(.1):
        return skip('guard_tone_error_margin')
    observed = np.asarray(heldout_amplitudes)
    if np.ptp(abs(observed))/abs(amplitude) > .25 or max(abs(np.angle(observed/amplitude))) > .25:
        return skip('guard_tone_not_stable')
    n = np.arange(len(z))
    corrected = z-amplitude*np.exp(2j*np.pi*frequency*n/c.RATE)
    # Independent pilot half check is required even when v1 stopped at its
    # total-power gate before reaching this check.
    t = np.arange(129)-64
    fir = (2*500000/c.RATE)*np.sinc(2*500000/c.RATE*t)*np.hamming(129); fir /= fir.sum()
    filtered = np.convolve(corrected, fir, mode='same')*np.exp(-2j*np.pi*sync['estimated_cfo_hz']*n/c.RATE)
    at = sync.get('marker_offset', sync['payload_marker_offset'])
    c.require(type(at) is int and 0 <= at <= len(z)-c.MARKER, 'complete anchor pilot')
    a, b = filtered[at+64:at+448], filtered[at+576:at+960]
    coherence = float(abs(np.vdot(a,b))/max(np.linalg.norm(a)*np.linalg.norm(b),1e-30))
    residual = float(np.angle(np.vdot(a,b))*c.RATE/(2*np.pi*512))
    info.update(pilot_half_coherence=coherence, pilot_residual_cfo_hz=residual)
    if coherence < .95 or abs(residual) > 25:
        return skip('pilot_does_not_confirm_frequency_prior')
    info.update(status='applied', corrected_samples_sha256=c.digest(corrected.astype('<c16').tobytes()))
    return corrected, info


def quality(source, received, source_z, info):
    result = c.receive_quality('synchronized', source, received, source_z)
    c.validate_receive_quality(result, source_z)
    result.update(rx_sinr_reference_plane=PLANE,
                  rx_interference_cancellation=METHOD if info['status']=='applied' else 'none_skipped')
    return result
