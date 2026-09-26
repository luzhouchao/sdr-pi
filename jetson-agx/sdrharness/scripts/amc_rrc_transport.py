"""Bounded experimental RRC sample transport; no hardware or model access.

Source IQ is used only by the transmitter. The receiver knows run/frame IDs,
window shape and pilots, but accepts no source IQ, labels or source SNR.
"""
import hashlib
import json
import numpy as np
import rml2018a_campaign as c
from rml2018a_stream_dsp import packet as native_packet

FACTOR = 4
DELAY = 64
METHOD = 'amc-rrc4-beta025-span32-v1'
MAX_CAPTURE = 12*1048576
SEARCH_SAMPLES = 131072


def taps():
    t = np.arange(-64, 65)/4
    beta = .25
    h = np.empty_like(t)
    for i, v in enumerate(t):
        if v == 0:
            h[i] = 1+beta*(4/np.pi-1)
        elif abs(v) == 1/(4*beta):
            h[i] = beta/np.sqrt(2)*((1+2/np.pi)*np.sin(np.pi/(4*beta))+
                                   (1-2/np.pi)*np.cos(np.pi/(4*beta)))
        else:
            h[i] = (np.sin(np.pi*v*(1-beta))+4*beta*v*np.cos(np.pi*v*(1+beta)))/(
                np.pi*v*(1-(4*beta*v)**2))
    return h/np.linalg.norm(h)


def interpolate(x):
    x = np.asarray(x)
    c.require(x.ndim == 1 and 0 < len(x) <= 4*1024**2 and np.isfinite(x).all(),
              'bounded finite transport waveform')
    z = np.zeros(4*(len(x)-1)+1, np.complex128)
    z[::4] = x
    return np.convolve(z, taps())


def contract(frame_payload_samples=None):
    c.require(frame_payload_samples is None or type(frame_payload_samples) is int and frame_payload_samples in (2048, 16384),
              'registered common RRC payload')
    value = dict(method=METHOD, factor=4, rolloff=.25, taps=129,
                taps_sha256=hashlib.sha256(taps().tobytes()).hexdigest(),
                tx_group_delay_rf_samples=64, rx_group_delay_rf_samples=64,
                adc_support_count_formula='4*(L-1)+129', rate_hz=c.RATE,
                guard_edge_exclusion_rf_samples=128, sinr='not_validated')
    if frame_payload_samples is not None:
        value.update(method=METHOD+('/payload16384-v2' if frame_payload_samples == 16384 else '/payload2048-v3'),
                     frame_payload_samples=frame_payload_samples, rows_per_frame_formula=str(frame_payload_samples)+'/L',
                     frame_rf_samples=4*(1536+frame_payload_samples))
    return value


def transmit(source, run_id, *, frame_payload_samples=None):
    profile = contract(frame_payload_samples)
    source = np.asarray(source)
    c.require(source.ndim == 2 and source.shape[1] in (128, 1024), 'native shape')
    original, scales = native_packet(source, run_id, window_samples=source.shape[1],
                                    total_rows=len(source), frame_payload_samples=frame_payload_samples)
    z = interpolate(original)
    gain = .2*np.sqrt(10)/max(abs(z))
    z = (z*gain).astype('<c8')
    return z, dict(contract=profile, row_scales=scales.tolist(), global_gain=float(gain),
                   native_packet_samples=len(original), tx_samples=len(z),
                   tx_sha256=hashlib.sha256(z.tobytes()).hexdigest())


def pilot(run_id, frame):
    # Sample centers on RF grid, with both edge regions excluded during sync.
    return interpolate(c.marker(run_id, frame))[64:64+4096]


def locate(z, reference, lo, hi, frequencies):
    """FFT normalized correlation; candidate starts [lo, hi), no payload access."""
    lo = max(0, int(lo)); hi = min(int(hi), len(z)-len(reference)+1)
    c.require(hi > lo, 'complete pilot search')
    values = z[lo:hi+len(reference)-1]
    power = np.r_[0., np.cumsum(abs(values)**2)]
    energy = power[len(reference):]-power[:-len(reference)]
    norm = np.sqrt(np.maximum(energy*np.vdot(reference, reference).real, 1e-30))
    valid = energy > max(float(energy.max())*1e-12, 1e-30)
    size = 1 << (len(values)+len(reference)-2).bit_length()
    kernel = np.fft.fft(reference[::-1].conj(), size)
    n = np.arange(lo, lo+len(values))
    best = (0., lo, 0.)
    for hz in frequencies:
        v = values*np.exp(-2j*np.pi*hz*n/c.RATE)
        corr = np.fft.ifft(np.fft.fft(v, size)*kernel)[len(reference)-1:len(values)]
        score = np.where(valid, abs(corr)/norm, 0.)
        at = int(score.argmax())
        if score[at] > best[0]:
            best = (float(score[at]), at+lo, float(hz))
    return best


def track(z, run_id, frame, predicted, hz):
    ref = pilot(run_id, frame)
    score, start, _ = locate(z, ref[128:-128], predicted, predicted+257, [hz])
    at = start-128
    c.require(score >= .55 and at >= 0 and at+4096 <= len(z), 'pilot coarse gate')
    n = np.arange(at, at+4096)
    p = z[n]*np.exp(-2j*np.pi*hz*n/c.RATE)
    a, b = p[256:1792], p[2304:3840]
    hz += float(np.angle(np.vdot(a, b))*c.RATE/(2*np.pi*2048))
    c.require(abs(hz) <= c.CFO_LIMIT_HZ, 'transport CFO limit')
    score, start, _ = locate(z, ref[128:-128], at, at+257, [hz])
    at = start-128
    c.require(score >= .65, 'pilot final gate')
    n = np.arange(at+128, at+3968)
    observed = z[n]*np.exp(-2j*np.pi*hz*n/c.RATE)
    phase = float(-np.angle(np.vdot(ref[128:-128], observed)))
    return at, hz, phase, score


def cancel(z, marker, length, hz, *, frame_payload_samples=None):
    """Fit RF-domain guards, validate heldout halves and independent pilot.

    Both true quiet intervals exclude full TX tails plus a 128-point margin.
    The signal is not notched and payload samples are not fitting inputs.
    """
    profile = contract(frame_payload_samples)
    payload_samples = 16*length if frame_payload_samples is None else frame_payload_samples
    origin = marker-1088
    payload_end = origin+4*(1280+payload_samples)
    intervals = [(origin+128, origin+896), (payload_end+128, payload_end+896)]
    info = dict(method=profile['method']+'/guard-tone', status='skipped', reason=None,
                guard_intervals=[list(v) for v in intervals], source_payload_used=False)

    def skip(reason):
        info['reason'] = reason
        return None, info

    if any(a < 0 or b > len(z) for a, b in intervals):
        return skip('incomplete_quiet_guards')
    train = np.concatenate([np.arange(a, a+384) for a, _ in intervals])
    center = 250000+hz

    def projection(f):
        return np.mean(z[train]*np.exp(-2j*np.pi*f*train/c.RATE))

    frequencies = center+np.arange(-30, 31)
    scores = np.array([abs(projection(f)) for f in frequencies])
    # Sparse guards have closely spaced frequency aliases. Refine EVERY local
    # maximum before comparing: a 1-Hz grid can rank an alias above the true peak.
    candidates = []
    for best in range(1, 60):
        if scores[best] < scores[best-1] or scores[best] < scores[best+1]:
            continue
        low, high = frequencies[best]-1, frequencies[best]+1
        for _ in range(40):
            left, right = low+(high-low)/3, high-(high-low)/3
            if abs(projection(left)) > abs(projection(right)):
                high = right
            else:
                low = left
        f = float((low+high)/2)
        candidates.append((abs(projection(f)), f))
    if not candidates:
        return skip('frequency_at_prior_boundary')
    _, f = max(candidates)
    # Within-guard phase slopes independently disambiguate separated guards.
    # Separate intercepts prevent the long silent gap from supplying cycle count.
    local_time = (np.arange(8)*48+23.5)/c.RATE
    local_time -= local_time.mean()
    slopes = []; residuals = []
    for a, _ in intervals:
        n = np.arange(a, a+384)
        phasors = (z[n]*np.exp(-2j*np.pi*center*n/c.RATE)).reshape(8, 48).mean(1)
        if min(abs(phasors)) < 1e-12:
            return skip('guard_phase_not_identifiable')
        angles = np.unwrap(np.angle(phasors)); angles -= angles.mean()
        slope = float(np.dot(local_time, angles)/np.dot(local_time, local_time))
        slopes.append(slope)
        residuals.extend(angles-slope*local_time)
    slope_mean = float(np.mean(slopes))
    variance = float(np.dot(residuals, residuals)/12)
    se_hz = float(np.sqrt(variance/(2*np.dot(local_time, local_time)))/(2*np.pi))
    local_frequency = center+slope_mean/(2*np.pi)
    ambiguity_spacing = c.RATE/(intervals[1][0]-intervals[0][0])
    info.update(within_guard_frequency_hz=local_frequency, within_guard_frequency_se_hz=se_hz,
                frequency_alias_spacing_hz=ambiguity_spacing, refined_frequency_peaks=len(candidates))
    if 4*se_hz >= ambiguity_spacing/2 or abs(f-local_frequency) > max(1., 4*se_hz):
        return skip('guard_frequency_alias_not_resolved')
    amplitude = projection(f)
    if abs(amplitude) < 1e-12:
        return skip('tone_not_identifiable')
    margins = []; heldout = []
    for a, b in intervals:
        for offset in (0, 384):
            n = np.arange(a+offset, a+offset+384)
            blocks = (z[n]*np.exp(-2j*np.pi*f*n/c.RATE)).reshape(8, 48).mean(1)
            observed = blocks.mean()
            stderr = np.sqrt(np.sum(abs(blocks-observed)**2)/56)
            margins.append(float((abs(observed-amplitude)+4*stderr)/abs(amplitude)))
            if offset:
                heldout.append(observed)
    observed = np.asarray(heldout)
    info.update(frequency_hz=f, amplitude=[float(amplitude.real), float(amplitude.imag)],
                maximum_relative_error_margin=max(margins),
                heldout_phase_spread_rad=float(max(abs(np.angle(observed/amplitude)))),
                heldout_amplitude_spread=float(np.ptp(abs(observed))/abs(amplitude)))
    if max(margins) > np.sqrt(.1):
        return skip('guard_tone_error_margin')
    if info['heldout_phase_spread_rad'] > .25 or info['heldout_amplitude_spread'] > .25:
        return skip('guard_tone_not_stable')
    n = np.arange(marker, marker+4096)
    if n[-1] >= len(z):
        return skip('incomplete_pilot')
    p = (z[n]-amplitude*np.exp(2j*np.pi*f*n/c.RATE))*np.exp(-2j*np.pi*hz*n/c.RATE)
    a, b = p[256:1792], p[2304:3840]
    coherence = float(abs(np.vdot(a, b))/max(np.linalg.norm(a)*np.linalg.norm(b), 1e-30))
    residual = float(np.angle(np.vdot(a, b))*c.RATE/(2*np.pi*2048))
    info.update(pilot_half_coherence=coherence, pilot_residual_cfo_hz=residual)
    if coherence < .95 or abs(residual) > 25:
        return skip('pilot_does_not_confirm_frequency_prior')
    info['status'] = 'applied'
    return (f, amplitude), info


def quality(status, frame_payload_samples=None):
    # RRC noise correlation and dataset Z semantics need a separate calibration.
    method = contract(frame_payload_samples)['method']
    return dict(rx_sinr_db=None, rx_sinr_status='not_measured',
                rx_sinr_reason='rrc_noise_and_source_z_contract_not_validated' if status == 'synchronized'
                else 'payload_not_synchronized', rx_sinr_method=method+'/conditional-pending',
                rx_sample_rate_hz=c.RATE/4, rx_adc_sample_rate_hz=c.RATE,
                rx_payload_filter=method, rx_sinr_reference_plane='matched_decimated_before_rms')


def validate_quality(q, frame_payload_samples=None):
    expected = quality('synchronized', frame_payload_samples)
    c.require(isinstance(q, dict) and all(q.get(k) == v for k, v in expected.items() if k != 'rx_sinr_reason')
              and q.get('rx_sinr_reason') in (expected['rx_sinr_reason'], 'payload_not_synchronized'),
              'RRC pending SINR contract')


class Decoder:
    """Finite stream buffering; sample offsets are always original ADC offsets.

    No convolution state is reset at input chunk boundaries: each decoded
    payload reads its full 129-tap halo from the immutable buffered RF stream.
    """
    def __init__(self, run_id, window_samples, rows, *, frame_payload_samples=None):
        c.require(isinstance(run_id, str) and 0 < len(run_id) <= 128, 'run ID')
        c.require(window_samples in (128, 1024) and type(rows) is int and 1 <= rows <= 8192,
                  'finite native decoder shape')
        self.run_id = run_id; self.length = window_samples; self.rows = rows
        self.profile = contract(frame_payload_samples)
        self.frame_payload_samples = frame_payload_samples
        self.rows_per_frame = 16 if frame_payload_samples is None else frame_payload_samples//window_samples
        self.frame_samples = 4*(1536+self.rows_per_frame*window_samples)
        self.total_frames = (rows+self.rows_per_frame-1)//self.rows_per_frame
        self.samples = np.empty(0, np.complex128)
        self.frame = 0; self.marker = None; self.hz = None; self.search = 0
        self.frames = []; self.closed = False
        self.inputs = {t:np.full((rows, 2, window_samples), np.nan, '<f4') for t in ('raw', 'guard')}
        self.masks = {t:np.zeros(rows, bool) for t in self.inputs}
        self.starts = np.full(rows, -1, '<i8'); self.counts = np.zeros(rows, '<i8')
        self.quality = [dict(raw=quality('missing', self.frame_payload_samples), guard=quality('missing', self.frame_payload_samples),
                             sync=dict(status='missing')) for _ in range(rows)]

    def feed(self, values, *, final=False):
        c.require(not self.closed, 'decoder already finalized')
        z = np.asarray(values)
        if z.ndim == 2 and z.shape[1] == 2 and z.dtype == np.dtype('<i2'):
            z = z[:, 0].astype(float)+1j*z[:, 1].astype(float)
        c.require(z.ndim == 1 and np.iscomplexobj(z) and np.isfinite(z).all()
                  and len(self.samples)+len(z) <= MAX_CAPTURE, 'bounded ADC stream')
        self.samples = np.r_[self.samples, z]
        if self.marker is None:
            while len(self.samples)-self.search >= SEARCH_SAMPLES or (final and len(self.samples)-self.search >= 4096):
                stop = min(len(self.samples), self.search+SEARCH_SAMPLES)
                ref = pilot(self.run_id, 0)[128:-128]
                score, start, hz = locate(self.samples[:stop], ref, self.search,
                                          stop-len(ref)+1, range(-c.CFO_SEARCH_MAX_HZ, c.CFO_SEARCH_MAX_HZ+1, 250))
                if score >= .55:
                    self.marker = start-128; self.hz = hz
                    break
                self.search += SEARCH_SAMPLES-4096
            if self.marker is None:
                if final:
                    self.closed = True
                return []
        emitted = []
        while self.frame < self.total_frames:
            predicted = self.marker
            origin = predicted-1088
            if origin+self.frame_samples+256 > len(self.samples):
                if not final:
                    break
                if origin+self.frame_samples > len(self.samples):
                    break
            record = dict(frame=self.frame, status='failed', reason=None)
            try:
                at, hz, phase, score = track(self.samples, self.run_id, self.frame, predicted, self.hz)
                c.require(at >= 1088, 'complete leading RF guard')
                tone, info = cancel(self.samples, at, self.length, hz, frame_payload_samples=self.frame_payload_samples)
                coarse_hz = hz
                if tone is not None:
                    # The validated guard prediction removes LO bias from the
                    # pilot only; raw/guard payloads share this fixed correction.
                    pn = np.arange(at, at+4096)
                    clean = self.samples[pn]-tone[1]*np.exp(2j*np.pi*tone[0]*pn/c.RATE)
                    p = clean*np.exp(-2j*np.pi*hz*pn/c.RATE)
                    residual = float(np.angle(np.vdot(p[256:1792], p[2304:3840]))*c.RATE/(2*np.pi*2048))
                    hz += residual
                    c.require(abs(hz) <= c.CFO_LIMIT_HZ, 'refined transport CFO limit')
                    ref = pilot(self.run_id, self.frame)
                    p = clean*np.exp(-2j*np.pi*hz*pn/c.RATE)
                    phase = float(-np.angle(np.vdot(ref[128:-128], p[128:-128])))
                first = at+4096
                count = self.rows_per_frame*self.length
                support_start = first-64
                support_count = 4*(count-1)+129
                c.require(support_start+support_count <= len(self.samples), 'complete matched-filter halo')
                n = np.arange(support_start, support_start+support_count)
                rotation = np.exp(-2j*np.pi*hz*n/c.RATE+1j*phase)
                raw = self.samples[n]
                guard = raw if tone is None else raw-tone[1]*np.exp(2j*np.pi*tone[0]*n/c.RATE)
                begin = self.frame*self.rows_per_frame; end = min(begin+self.rows_per_frame, self.rows)
                pending = {}
                for tag, samples in [('raw', raw), ('guard', guard)]:
                    recovered = np.convolve(samples*rotation, taps(), mode='valid')[::4].reshape(self.rows_per_frame, self.length)[:end-begin]
                    rms = np.sqrt(np.mean(abs(recovered)**2, axis=1))
                    c.require(np.all(rms > 0) and np.isfinite(rms).all(), 'nonzero recovered rows')
                    normalized = recovered/rms[:, None]
                    pending[tag] = (normalized, rms)
                for tag, (normalized, rms) in pending.items():
                    self.inputs[tag][begin:end, 0] = normalized.real
                    self.inputs[tag][begin:end, 1] = normalized.imag
                    self.masks[tag][begin:end] = True
                self.starts[begin:end] = support_start+np.arange(end-begin)*4*self.length
                self.counts[begin:end] = 4*(self.length-1)+129
                record.update(status='synchronized', marker_rf_sample=at, cfo_hz=hz,
                              phase_rotation_rad=phase, marker_score=score, pilot_cfo_before_guard_hz=coarse_hz, guard=info)
                for row in range(begin, end):
                    raw_quality = dict(quality('synchronized', self.frame_payload_samples), normalization_rms=float(pending['raw'][1][row-begin]))
                    guard_quality = dict(quality('synchronized', self.frame_payload_samples), normalization_rms=float(pending['guard'][1][row-begin]))
                    self.quality[row] = dict(raw=raw_quality, guard=guard_quality,
                        sync=dict(status='synchronized', frame=self.frame, marker_score=score, cfo_hz=hz),
                        guard_status=info['status'], guard_reason=info['reason'],
                        first_native_center_rf_sample=int(self.starts[row]+64), rf_stride=4)
                self.marker = at; self.hz = hz
            except ValueError as e:
                record['reason'] = str(e)
            self.frames.append(record); emitted.append(record)
            self.frame += 1; self.marker += self.frame_samples
        if final:
            self.closed = True
        return emitted

    def result(self):
        c.require(self.closed, 'finalize ADC before publishing')
        return dict(inputs=self.inputs, masks=self.masks, sample_starts=self.starts,
                    sample_counts=self.counts, quality=self.quality, frames=self.frames,
                    missing_frames=list(range(self.frame, self.total_frames)),
                    transport=self.profile, adc_samples=len(self.samples))
