#!/usr/bin/env python3
"""Export a 1024-sample train unit; retain explicit legacy four-row reproduction."""
if not __debug__:
    raise RuntimeError('optimized Python would disable validation; refusing to run')

import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile
import h5py
import numpy as np

ROOT = Path(__file__).resolve().parents[3]


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--extended', action='store_true', help='registered ten-second 70-dB retry, peak 0.2')
    units=parser.add_mutually_exclusive_group()
    units.add_argument('--single-row', dest='single_row', action='store_true', default=True,
                       help='Default: version 2, one 1024-sample row and complete repeated units')
    units.add_argument('--legacy-four-row', dest='single_row', action='store_false',
                       help='Explicit historical version-1 reproduction; new captures default to 1024 samples')
    return parser


def main():
    args = argument_parser().parse_args()
    directory = args.directory
    if directory.resolve() != directory or directory.parent != Path('/var/tmp/sdrharness-dev'):
        raise ValueError('exact feature directory required')
    plan = json.loads((ROOT / 'jetson-agx/sdrharness/config/amc/rf-preprocess-v1-selection-plan.json').read_text())
    split = ROOT / plan['pinned_inputs']['split']['path']
    # Read only train.npy. Never deserialize or select test indices.
    with zipfile.ZipFile(split) as archive:
        train = np.load(io.BytesIO(archive.read('train.npy')), allow_pickle=False)
    digest = hashlib.sha256(np.asarray(train, dtype='<i8').tobytes()).hexdigest()
    assert digest == plan['data_access']['allowed_split_member_sha256']['train_le_i64']
    # RML block indexing is checked against the selected rows' Y and Z below.
    rows = np.sort(train[(train >= 25 * 4096) & (train < 26 * 4096)])[:4]
    assert len(rows) == 4 and len(set(map(int, rows))) == 4
    if args.single_row:
        assert args.extended, 'single-row contract requires the registered extended gain/amplitude'
        rows=rows[:1]
        assert list(map(int,rows))==[102400]
    dataset = ROOT / plan['pinned_inputs']['dataset']['path']
    with h5py.File(dataset, 'r') as h5:
        iq = np.asarray(h5['X'][rows], dtype='<f4')
        labels = np.asarray(h5['Y'][rows])
        snr = np.asarray(h5['Z'][rows]).reshape(-1)
    assert iq.shape == (len(rows), 1024, 2) and np.isfinite(iq).all()
    assert (labels.argmax(axis=1) == 0).all() and (snr == 30).all()
    complex_iq = iq[..., 0].astype(np.float64) + 1j * iq[..., 1].astype(np.float64)
    peak = 0.2 if args.extended else 0.1
    scale = peak / float(np.abs(complex_iq).max())
    payload = np.asarray(iq.reshape(-1, 2) * scale, dtype='<f4').tobytes()
    assert len(payload) == len(rows)*8192
    metadata = dict(schema_version=1,split='train',train_member_sha256=digest,
                    dataset_path=str(dataset),rows=list(map(int, rows)),class_id=0,
                    name_status='provisional',dataset_nominal_snr_db=30,
                    source_iq_sha256=hashlib.sha256(iq.tobytes()).hexdigest(),
                    payload_sha256=hashlib.sha256(payload).hexdigest(),payload_bytes=len(payload),
                    amplitude_scale=scale,complex_peak=peak,center_hz=2440000000,
                    rate_sps=2100000,bandwidth_hz=1500000,tx_gain_db=(70 if args.extended else 0),
                    tx_samples=(21000000 if args.extended else 2100000),tx_nominal_seconds=(10 if args.extended else 1),tx_channel=0,tx_antenna='TX/RX',
                    waveform='four separate train snippets concatenated and cyclically repeated',
                    physical_dataset_sample_rate_known=False,locked_test_read=False,
                    receiver_label='unknown until independently correlated and reviewed',
                    recognizer_available=False)
    if args.single_row:
        metadata.update(schema_version=2,source_unit_samples=1024,tx_unit_count=20480,
                        tx_samples=20480*1024,uhd_spb=1024,
                        waveform='one unchanged 1024-sample train snippet cyclically repeated in complete units')
    with (directory / 'train-tile.fc32').open('xb') as handle:
        handle.write(payload)
    with (directory / 'transmission-plan.json').open('x') as handle:
        json.dump(metadata,handle,indent=2);handle.write('\n')
    print(json.dumps(metadata))


if __name__ == '__main__':
    main()
