#!/usr/bin/env python3
"""Read archived 100MHz–6GHz summaries; compare frequency patterns, never run RF/models."""
import collections
import hashlib
import io
import json
from pathlib import Path
import time
import numpy as np
import pandas as pd

SOURCE = Path('/home/jetson/agent/data/datasets/realtime_100_6000_A_20260816T111550Z_600s_256kfft')
ROOT = Path('/var/tmp/sdrharness-dev/historical-background-20260909f')
REPO = Path(__file__).resolve().parents[3]
FREQ = np.r_[np.arange(2400500000,2484000000,1000000),np.arange(5150500000,5850000000,1000000)]
METRICS = ['mean_power_db','noise_floor_db','occupancy_rate','peak_power_db']


def run():
    assert ROOT.resolve()==ROOT and not ROOT.exists()
    ROOT.mkdir(mode=0o700)
    (ROOT/'scratch').mkdir(mode=0o700)
    manifest = []
    def read(path):
        assert path.resolve()==path and path.is_relative_to(SOURCE) and path.is_file()
        before=path.stat();data=path.read_bytes();after=path.stat()
        assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
        manifest.append(dict(path=str(path),bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
        return data
    paths=sorted(SOURCE.glob('runs/*/*/*.json'))
    assert len(paths)==1586, 'historical inventory changed; review scope'
    matrix=np.full((len(paths),len(FREQ),len(METRICS)),np.nan,dtype=np.float64)
    records=[];quality=collections.Counter();frame_quality=collections.Counter();config_counts=collections.Counter()
    raw_counts=[];duplicate_counts=[];missing=0
    columns=['channel_center_freq_hz','channel_width_hz','coverage_ratio','quality_flags',*METRICS]
    start=time.monotonic()
    for i,path in enumerate(paths):
        meta=json.loads(read(path))
        sdr=meta['sdr_config'];welch=meta['welch_config'];sweep=meta['sweep_config']
        assert sdr['sample_rate_hz']==30720000 and sdr['rf_bandwidth_hz']==30000000 and sdr['gain_db']==60
        assert welch['nfft']==262144 and meta['subband_feature_config']['width_hz']==1000000
        assert sweep['start_freq_hz']==100000000 and sweep['stop_freq_hz']==6000000000 and sweep['window_count']==219
        csv_path=Path(meta['outputs']['subband_csv_path']);assert csv_path.parent==path.parent
        frame_path=Path(meta['outputs']['csv_path']);assert frame_path.parent==path.parent
        data=pd.read_csv(io.BytesIO(read(csv_path)),usecols=columns)
        raw_counts.append(len(data))
        quality.update(data['quality_flags'].fillna('').value_counts().to_dict())
        selected=data[data.channel_center_freq_hz.isin(FREQ)].copy()
        valid=(selected.coverage_ratio>=.8)&(selected.channel_width_hz==1000000)&selected.quality_flags.isna()
        valid &= np.isfinite(selected[METRICS]).all(axis=1)
        missing += int((~valid).sum())
        selected=selected[valid]
        duplicate_counts.append(len(selected)-selected.channel_center_freq_hz.nunique())
        # Adjacent 30MHz windows overlap: give each physical sweep/subband one vote.
        grouped=selected.groupby('channel_center_freq_hz')[METRICS].median().reindex(FREQ)
        matrix[i]=grouped.to_numpy()
        frames=pd.read_csv(io.BytesIO(read(frame_path)),usecols=['sample_count_complex','capture_seconds_nominal','quality_flags','backend'])
        frame_quality.update(frames.quality_flags.fillna('').value_counts().to_dict())
        assert len(frames)==219
        configs=dict(sample_rate_hz=sdr['sample_rate_hz'],rf_bandwidth_hz=sdr['rf_bandwidth_hz'],gain_db=sdr['gain_db'],
            nfft=welch['nfft'],backend_config=welch['backend'],actual_backends=sorted(frames.backend.unique().tolist()),
            antenna_id=meta['antenna_id'],location_id=meta['location_id'],settle_sec=sweep['settle_sec'],
            samples_per_window=sorted(frames.sample_count_complex.unique().tolist()),nominal_seconds=sorted(frames.capture_seconds_nominal.unique().tolist()))
        config_counts[json.dumps(configs,sort_keys=True)] += 1
        records.append(dict(run_id=meta['run_id'],metadata_path=str(path),started_utc=meta['started_utc'],finished_utc=meta['finished_utc'],
            utc_day=meta['started_utc'][:10],backend=welch['backend'],device_id=meta['device_id'],antenna_id=meta['antenna_id'],location_id=meta['location_id']))
        if i%100==0:print(f'{i+1}/{len(paths)} historical sweeps read; {time.monotonic()-start:.1f}s',flush=True)
    assert len(set(x['run_id'] for x in records))==1586
    assert np.isfinite(matrix).all(), 'missing selected frequency data'
    summary=dict(schema_id='historical_background_comparison_v1',source=str(SOURCE),run_count=len(records),records=records,
        first_started_utc=min(x['started_utc'] for x in records),last_started_utc=max(x['started_utc'] for x in records),
        raw_subband_rows=sum(raw_counts),per_file_raw_rows=sorted(set(raw_counts)),
        selected_invalid_rows=missing,selected_overlap_rows_collapsed=sum(duplicate_counts),
        quality_flags=dict(quality),frame_quality_flags=dict(frame_quality),
        configs=[dict(count=n,config=json.loads(k)) for k,n in config_counts.items()],
        source_files=len(manifest),source_bytes=sum(x['bytes'] for x in manifest),
        aggregation='median overlapping records within each physical sweep/1MHz subband; then quantiles across sweeps',
        historical_mean_power_definition='arithmetic mean of PSD dB bins; not integrated power, dBm or ADC RMS',
        historical_occupancy_definition='fraction of frequency bins > local subband PSD 20th percentile +10dB; not time duty',
        comparison_boundary='frequency-pattern comparison only; antenna/session/gain/BW/time/metrics differ',
        rf_operations=0,model_calls=0,locked_test_reads=0,numpy=np.__version__,pandas=pd.__version__,
        frequencies_hz=FREQ.tolist(),metrics=METRICS,groups={})
    for name,mask in [('all',np.ones(len(records),dtype=bool)),*[(day,np.array([x['utc_day']==day for x in records])) for day in sorted({x['utc_day'] for x in records})]]:
        values=matrix[mask]
        summary['groups'][name]=dict(sweeps=int(mask.sum()),p50=np.median(values,axis=0).tolist(),p95=np.percentile(values,95,axis=0).tolist())
    # A compact temporary matrix allows independent verification/plotting without rereading GBs.
    np.savez_compressed(ROOT/'scratch/matrix.npz',values=matrix,frequencies_hz=FREQ,days=np.array([x['utc_day'] for x in records]))
    (ROOT/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    (ROOT/'source-manifest.jsonl').write_text(''.join(json.dumps(x,separators=(',',':'))+'\n' for x in manifest))
    print(json.dumps(dict(completed=len(records),bytes_read=summary['source_bytes'],overlap_rows=summary['selected_overlap_rows_collapsed'],seconds=time.monotonic()-start)),flush=True)


if __name__=='__main__': run()
