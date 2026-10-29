"""Offline source/condition schedule for a finite 2048-window pilot.

No radio or inference. Select only seed42 validation members, independently of
predictions. Three consecutive frames share 16 source rows; their condition
order is randomized to reduce drift. Final two frames are tail controls.
"""
import numpy as np

import rml2018a_campaign as c
from rml2018a_campaign_store import source_rows
from rml2018a_stream_dsp import packet, FRAME_SAMPLES

SEED = 20260926
POWER_DB = (0, -10, -20)


def schedule(validation):
    validation = np.asarray(validation)
    c.require(validation.ndim == 1 and validation.dtype == np.int64 and
              len(validation) > 0 and np.all(np.diff(validation) > 0) and
              np.all((validation >= 0) & (validation < 2555904)), 'sorted unique validation rows')
    rng = np.random.RandomState(SEED)
    selected = []
    for label in range(24):
        eligible = validation[(validation//106496 == label) &
                              (2*((validation % 106496)//4096)-20 == 30)]
        c.require(len(eligible) >= 28, '28 validation source-Z30 members per class')
        selected.extend(rng.choice(eligible, 28, replace=False).tolist())
    groups = rng.permutation(selected).reshape(42, 16)
    rows, db, group_id = [], [], []
    for group in rng.permutation(42):
        for condition in rng.permutation(3):
            rows.extend(groups[group].tolist())
            db.extend([POWER_DB[condition]]*16)
            group_id.extend([int(group)]*16)
    # These observations provide trailing context and never enter primary ACC.
    rows.extend(groups[:2].ravel().tolist())
    db.extend([0]*32)
    group_id.extend([-1]*32)
    result = dict(schema='rml2018a-interleaved-schedule-v1', seed=SEED,
                  source_snr_db=30, source_rows=rows, payload_power_db=db,
                  pair_group=group_id, primary=[True]*2016+[False]*32,
                  unique_primary_rows=672, primary_observations=2016,
                  tail_observations=32, frame_rows=16, frames=128,
                  grouping='paired raw-reference conditional estimated receive SINR; invalid separate',
                  scope='new acquisition session; reused source validation members; not locked-test')
    source_rows(result, 0)
    source_rows(result, 1)
    return result


def waveform(values, run_id, design):
    """Apply amplitude only after peak normalization; keep pilots/zeros intact."""
    c.require(design['schema'] == 'rml2018a-interleaved-schedule-v1', 'schedule schema')
    levels = np.asarray(design['payload_power_db'])
    c.require(levels.shape == (2048,) and np.isin(levels, POWER_DB).all() and
              np.all(levels.reshape(128, 16) == levels[::16, None]), 'frame amplitude schedule')
    wave, scales = packet(values, run_id)
    c.require(np.isfinite(wave).all() and np.isfinite(scales).all(), 'nonzero finite payloads')
    gain = np.power(10., levels/20.)
    frames = wave.reshape(128, FRAME_SAMPLES)
    frames[:, 1280:-256] *= gain.reshape(128, 16, 1).repeat(1024, axis=2).reshape(128, -1)
    return wave, scales*gain
