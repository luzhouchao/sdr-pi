"""Finite all-row RF campaign contract. No radio/model side effects on import."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np

SCHEMA = 'rml2018a-all-row-rf-v2'
# Freeze pilot generation independently of record schema/frequency changes so
# archived v1 frames remain reproducible for read-only diagnostics.
PILOT_SCHEMA = 'rml2018a-all-row-rf-v1'
RATE = 2100000
CENTER = 2455000000
BW = 1500000
RX_SAMPLES = 65535
ROWS_PER_BATCH = 24
GUARD = 256
MARKER = 1024
TX_SECONDS = 4
REPO = Path(__file__).resolve().parents[3]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        import os
        os.fsync(stream.fileno())
    temp.replace(path)


def marker(run_id, batch):
    # Batch-specific QPSK pilot, pulse width4 and two equal512-sample halves.
    bits = np.unpackbits(np.frombuffer(hashlib.shake_256(
        f'{PILOT_SCHEMA}:{run_id}:{batch}'.encode()).digest(32), dtype=np.uint8))
    chips = ((bits[::2].astype(float) * 2 - 1) +
             1j * (bits[1::2].astype(float) * 2 - 1)) / np.sqrt(2)
    return np.tile(np.repeat(chips, 4), 2) * .2


def packet(iq, run_id, batch):
    iq = np.asarray(iq)
    require(iq.ndim == 3 and iq.shape[1:] == (1024, 2) and
            0 < len(iq) <= ROWS_PER_BATCH and np.isfinite(iq).all(), 'bad source rows')
    z = iq[..., 0].astype(float) + 1j * iq[..., 1].astype(float)
    peaks = abs(z).max(axis=1)
    require((peaks > 0).all(), 'zero source row')
    scales = .2 / peaks
    z *= scales[:, None]
    frame = np.concatenate((np.zeros(GUARD), marker(run_id, batch),
                            z.ravel(), np.zeros(GUARD))).astype('<c8')
    require(len(frame) * 2 <= RX_SAMPLES and abs(frame).max() <= .200001, 'packet bound')
    return frame, scales


def tx_plan(frame, run_id, batch, rows):
    units = math.floor(RATE * TX_SECONDS / len(frame))
    return dict(schema=SCHEMA, run_id=run_id, batch=batch, rows=list(map(int, rows)),
                center_hz=CENTER, rate_sps=RATE, bandwidth_hz=BW, tx_gain_db=70,
                tx_channel=0, tx_antenna='TX/RX', serial='2508504', lo_offset_hz=250000,
                payload_bytes=frame.nbytes, payload_sha256=digest(frame.tobytes()),
                packet_samples=len(frame), repeats=units, tx_samples=units * len(frame),
                max_seconds=TX_SECONDS, complex_peak=.2)


def validate_tx(plan, payload):
    require(isinstance(plan.get('run_id'), str) and 0 < len(plan['run_id']) <= 128 and
            type(plan.get('batch')) is int and 0 <= plan['batch'] < 106496, 'batch identity')
    for k, v in dict(schema=SCHEMA, center_hz=CENTER, rate_sps=RATE, bandwidth_hz=BW,
                     tx_gain_db=70, tx_channel=0, tx_antenna='TX/RX', serial='2508504',
                     lo_offset_hz=250000, max_seconds=TX_SECONDS, complex_peak=.2).items():
        require(plan.get(k) == v, 'unregistered TX ' + k)
    rows = plan['rows']
    require(isinstance(rows, list) and 0 < len(rows) <= ROWS_PER_BATCH and
            all(type(r) is int and 0 <= r < 2555904 for r in rows) and
            len(set(rows)) == len(rows), 'invalid row ids')
    n = GUARD * 2 + MARKER + len(rows) * 1024
    require(plan['packet_samples'] == n and len(payload) == plan['payload_bytes'] == n * 8,
            'TX byte budget')
    require(plan['repeats'] == RATE * TX_SECONDS // n and
            plan['tx_samples'] == n * plan['repeats'], 'TX sample budget')
    require(digest(payload) == plan['payload_sha256'], 'TX payload hash')
    z = np.frombuffer(payload, dtype='<c8')
    require(np.isfinite(z).all() and abs(z).max() <= .200001, 'TX finite peak')
    require(np.allclose(z[GUARD:GUARD+MARKER], marker(plan['run_id'], plan['batch']),
                        rtol=0, atol=1e-7), 'TX marker identity')


def synchronize(raw, run_id, batch, row_count):
    """Marker-only timing/CFO fit; never searches on model labels/predictions."""
    z = np.asarray(raw, dtype=np.complex128)
    require(z.shape == (RX_SAMPLES,) and np.isfinite(z).all(), 'RX shape')
    require(0 < row_count <= ROWS_PER_BATCH, 'RX row bound')
    original = z
    # Fixed pilot detector filter only. The model receives unfiltered payload IQ.
    # Rejects out-of-pilot-band tones without selecting a notch from received data.
    taps = np.arange(129) - 64
    fir = (2*500000/RATE)*np.sinc((2*500000/RATE)*taps)*np.hamming(129)
    fir /= fir.sum()
    z = np.convolve(z, fir, mode='same')
    ref = np.convolve(marker(run_id, batch), fir, mode='same')
    n = np.arange(len(z))
    cumulative = np.concatenate(([0.], np.cumsum(abs(z)**2)))
    energy = cumulative[MARKER:] - cumulative[:-MARKER]
    fft_size = 1 << (len(z)+MARKER-2).bit_length()
    kernel = np.fft.fft(ref[::-1].conj(), fft_size)

    def correlate(values):
        return np.fft.ifft(np.fft.fft(values, fft_size)*kernel)[MARKER-1:len(z)]
    valid = len(z) - MARKER + 1
    denom = np.sqrt(np.maximum(energy[:valid] * np.vdot(ref, ref).real, 1e-30))
    best = (-1., 0, 0.)
    for hz in range(-2500, 2501, 500):
        corrected = z * np.exp(-2j*np.pi*hz*n/RATE)
        corr = correlate(corrected)[:valid]
        scores = abs(corr) / denom
        at = int(np.argmax(scores))
        if scores[at] > best[0]:
            best = (float(scores[at]), at, float(hz))
    score, at, hz = best
    require(score >= .55, f'marker_not_found:{score:.6f}')
    y = z * np.exp(-2j*np.pi*hz*n/RATE)
    pilot = y[at:at+MARKER]
    # Ignore filter edge transients at each half when estimating residual CFO.
    residual = np.angle(np.vdot(pilot[64:448], pilot[576:960])) * RATE / (2*np.pi*512)
    hz += float(residual)
    require(abs(hz) <= 3000, 'CFO outside registered search')
    y = z * np.exp(-2j*np.pi*hz*n/RATE)
    corr = correlate(y)[:valid]
    scores = abs(corr) / denom
    at = int(np.argmax(scores)); score = float(scores[at])
    require(score >= .65, f'marker_quality:{score:.6f}')
    gain = np.vdot(ref, y[at:at+MARKER]) / np.vdot(ref, ref)
    payload_marker = at
    frame_samples = GUARD*2 + MARKER + row_count*1024
    if at + MARKER + row_count*1024 > len(z):
        # Identical finite repeated frames: a clean trailing pilot can anchor the
        # previous complete payload, without pretending the partial tail is full.
        payload_marker -= frame_samples
    require(payload_marker >= 0, 'no complete repeated payload')
    start = payload_marker + MARKER
    selected = original[start:start+row_count*1024] * np.exp(
        -2j*np.pi*hz*n[start:start+row_count*1024]/RATE-1j*np.angle(gain))
    require(len(selected) == row_count*1024, 'incomplete packet')
    return selected.reshape(row_count, 1024), dict(marker_score=score, marker_offset=at,
        payload_marker_offset=payload_marker, payload_marker_score=float(scores[payload_marker]),
        estimated_cfo_hz=hz, phase_rotation_rad=float(-np.angle(gain)),
        detector_filter=dict(kind='129-tap Hamming FIR', cutoff_hz=500000, payload_filtered=False),
        method='batch-specific pilot timing/CFO/common phase; unfiltered payload; no DC subtraction or label fitting')


def normalize_window(z):
    z = np.asarray(z, dtype=np.complex128)
    require(z.shape == (1024,) and np.isfinite(z).all(), 'model row shape')
    rms = np.sqrt(np.mean(abs(z)**2))
    require(rms > 0 and np.isfinite(rms), 'model zero RMS')
    return np.ascontiguousarray(np.stack((z.real, z.imag)) / rms, dtype=np.float32)


def receive_quality(receive_status):
    """Do not infer total SINR from noisy dataset X, its Z label or coherence.

    X already includes source-generation impairments. RX-minus-X residuals
    describe additional link error, not total signal/(interference+noise).
    No calibrated component separation estimator is implemented here.
    """
    require(receive_status in ('synchronized', 'sync_failed'), 'receive quality status')
    return dict(rx_sinr_db=None, rx_sinr_status='not_measured',
        rx_sinr_reason=('no_clean_reference_or_validated_component_estimator'
                        if receive_status == 'synchronized' else 'payload_not_synchronized'),
        rx_sinr_method=None, rx_sinr_measurement_bandwidth_hz=None,
        rx_sinr_reference_plane='received_payload_before_rms',
        rx_payload_filter='none', rx_sample_rate_hz=RATE, rx_rf_bandwidth_hz=BW)


def batch_rows(total, batch):
    require(type(batch) is int and 0 <= batch < math.ceil(total / ROWS_PER_BATCH), 'batch index')
    return list(range(batch * ROWS_PER_BATCH, min(total, (batch+1)*ROWS_PER_BATCH)))


def budget(total):
    require(type(total) is int and 0 < total <= 2555904, 'dataset rows')
    batches = math.ceil(total / ROWS_PER_BATCH)
    return dict(rows=total, batches=batches, rows_per_batch=ROWS_PER_BATCH,
                maximum_rx_iq_bytes=batches*RX_SAMPLES*4,
                maximum_tx_seconds=batches*TX_SECONDS,
                maximum_transient_packet_bytes=(GUARD*2+MARKER+ROWS_PER_BATCH*1024)*8,
                metadata_and_predictions_reserve_bytes=batches*131072,
                estimated_wall_seconds_unvalidated=batches*10,
                warning='wall estimate includes per-batch radio/SSH setup; replace with pilot measurement')
