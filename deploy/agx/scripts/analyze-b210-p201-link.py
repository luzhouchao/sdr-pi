#!/usr/bin/env python3
"""Bounded signal-evidence analysis; no classifier or dataset access."""
if not __debug__:
    raise RuntimeError('optimized Python would disable validation; refusing to run')

import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def metrics(path, reference):
    assert path.stat().st_size == 65535 * 4
    raw = path.read_bytes()
    iq = np.frombuffer(raw, dtype='<i2').reshape(-1, 2).astype(np.float64)
    z = iq[:, 0] + 1j * iq[:, 1]
    z -= z.mean()
    period = len(reference)
    a, b = z[:-period], z[period:]
    repetition = np.vdot(a,b) / np.sqrt(np.vdot(a,a).real*np.vdot(b,b).real)
    blocks = z[:15*period].reshape(15,period)
    envelope = np.abs(blocks)
    envelope -= envelope.mean(axis=1,keepdims=True)
    target = np.abs(reference)-np.abs(reference).mean()
    cc = np.fft.ifft(np.fft.fft(envelope,axis=1)*np.fft.fft(target).conj(),axis=1).real
    cc /= np.sqrt((envelope**2).sum(axis=1)[:,None]*(target**2).sum())
    return dict(iq_sha256=hashlib.sha256(raw).hexdigest(),samples=len(z),
                periodic_correlation_abs=float(abs(repetition)),
                periodic_phase_radians=float(np.angle(repetition)),
                envelope_correlation_max=float(cc.max()),
                envelope_correlation_median=float(np.median(cc.max(axis=1))),
                envelope_lags=list(map(int,cc.argmax(axis=1))))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',type=Path,required=True)
    a=p.parse_args();root=a.directory
    assert root.resolve()==root and root.parent==Path('/var/tmp/sdrharness-dev')
    tile=np.fromfile(root/'train-tile.fc32',dtype='<f4').reshape(-1,2)
    reference=tile[:,0]+1j*tile[:,1]
    assert len(reference)==4096
    result=dict(schema_version=1,method='period-4096 complex autocorrelation and cyclic envelope matched correlation',
                interpretation='engineering link evidence, not independent RF class accuracy or admission',cases={})
    for tag in ['baseline','during-tx','after-tx']:
        report=json.loads((root/f'{tag}-report.json').read_text())
        path=Path(report['dataset']['data_path'])
        assert path.resolve().parent==root/tag
        result['cases'][tag]=metrics(path,reference)
        result['cases'][tag]['band_power_dbfs']=report['points'][0]['band_power_dbfs']
    during=result['cases']['during-tx']
    controls=[result['cases'][tag] for tag in ['baseline','after-tx']]
    # These engineering discrimination checks do not define production reject thresholds.
    result['waveform_detected']=(during['periodic_correlation_abs']>.5 and
        during['envelope_correlation_median']>.5 and
        all(c['periodic_correlation_abs']<.1 and c['envelope_correlation_median']<.2 for c in controls))
    (root/'signal-analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
