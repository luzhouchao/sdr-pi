"""Offline-only candidate: add a verified preceding guard to the existing fit.

No source reference, label, SNR, model output, or RF access. The caller retains
its validated baseline when this candidate cannot be accepted. Original guard
frequency search and all tone/pilot gates are unchanged.
"""
import numpy as np
import rml2018a_guard_tone as guard

FRAME_SAMPLES=17920
CONTEXT_SAMPLES=65535
MARKER_OFFSET=448
PAYLOAD_OFFSET=MARKER_OFFSET+1024
PAYLOAD_SAMPLES=16*1024


def cancel(context, cfo_hz, *, frame_index, previous_spacing_samples, frequency_fit=None):
    """Context starts 448 ADC samples before the known current pilot."""
    if frame_index==0:
        return None,dict(status='baseline_fallback',reason='no_preceding_transmitted_frame')
    if previous_spacing_samples!=FRAME_SAMPLES:
        return None,dict(status='baseline_fallback',reason='preceding_frame_spacing_not_exact')
    z=np.asarray(context)
    if z.shape!=(CONTEXT_SAMPLES,) or not np.iscomplexobj(z) or not np.isfinite(z).all():
        raise ValueError('finite complete complex ADC context required')
    corrected,proposal=guard.cancel(z,dict(marker_offset=MARKER_OFFSET,payload_marker_offset=MARKER_OFFSET,
        estimated_cfo_hz=float(cfo_hz)),16,pilot_only=True,frequency_fit=frequency_fit)
    if proposal['status']!='applied':
        return None,dict(status='baseline_fallback',reason=proposal['reason'],proposal=proposal)
    return corrected[PAYLOAD_OFFSET:PAYLOAD_OFFSET+PAYLOAD_SAMPLES],dict(status='applied',reason=None,proposal=proposal)
