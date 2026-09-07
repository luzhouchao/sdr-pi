"""Pinned 72-source diagnostic contract, also usable on NX without NumPy."""
import hashlib
import json
import math
import struct

MANIFEST_SHA256 = '8d873847234bb48d4235348a6f3ae543d3f881c61ba2390ca018e6da7e5d7d32'
CONTRACT = 'b210_24class_3row_1024_v1'
TRAIN_SHA256 = '0426197a7ba17a4091a37d481bb8cd887a04d06406525978fdc7f669d4d2fa21'


def validate(root):
    raw = (root / 'multiclass-manifest.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == MANIFEST_SHA256, 'unregistered source matrix'
    manifest = json.loads(raw)
    plan = json.loads((root / 'transmission-plan.json').read_text())
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    assert len(manifest['cases']) == 72
    assert canonical(plan) in {canonical(p) for p in manifest['cases']}, 'case differs from pinned manifest'
    for key, value in dict(schema_version=5, diagnostic_contract=CONTRACT,
                           source_unit_samples=1024, payload_bytes=8192, tx_unit_count=20480,
                           uhd_spb=1024, tx_samples=20971520, tx_nominal_seconds=10,
                           complex_peak=.2, tx_gain_db=70, center_hz=2455000000,
                           tx_lo_offset_hz=250000, tx_requested_lo_hz=2455250000,
                           rate_sps=2100000, bandwidth_hz=1500000, tx_channel=0,
                           tx_antenna='TX/RX', split='train', locked_test_read=False,
                           dataset_nominal_snr_db=30, train_member_sha256=TRAIN_SHA256,
                           name_status='provisional', recognizer_available=False).items():
        assert type(plan[key]) is type(value) and plan[key] == value, key
    c = plan['class_id']
    assert type(c) is int and 0 <= c < 24
    assert len(plan['rows']) == 1 and type(plan['rows'][0]) is int
    assert (c * 26 + 25) * 4096 <= plan['rows'][0] < (c + 1) * 26 * 4096
    payload = (root / 'train-tile.fc32').read_bytes()
    assert len(payload) == 8192 and hashlib.sha256(payload).hexdigest() == plan['payload_sha256']
    samples = list(struct.iter_unpack('<ff', payload))
    assert all(math.isfinite(i) and math.isfinite(q) for i, q in samples)
    peak = max(math.hypot(i, q) for i, q in samples)
    assert abs(peak - .2) < 1e-7, 'physical payload peak differs'
    return plan
