#!/usr/bin/env python3
"""绘制固定逐点I/Q对照；临时数组由有哈希的既有证据生成，绘图后清理。"""
from pathlib import Path
import json
import hashlib
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path('/var/tmp/sdrharness-dev/b210-residual-907v')
DOCS = Path(__file__).resolve().parents[3]/'docs'
PAIRS = [('r0c05', 'r1c05', '8PSK'), ('r0c11', 'r1c11', '128APSK'),
         ('r1c13', 'r0c13', '32QAM'), ('r2c19', 'r1c19', 'AM-DSB-WC')]
with np.load(ROOT/'pointwise-display.npz', allow_pickle=False) as archive:
    metrics = json.loads((ROOT/'pointwise.json').read_text())
    for bad, good, label in PAIRS:
        fig, axes = plt.subplots(3, 2, figsize=(14, 9), constrained_layout=True)
        error_limit = 1.05*max(float(abs(archive[tag+'_received']-archive[tag+'_source']).max()) for tag in (bad, good))
        for col, (tag, status) in enumerate(((bad, 'Prediction mismatch'), (good, 'Same-class successful control'))):
            x, y = archive[tag+'_source'], archive[tag+'_received']
            assert hashlib.sha256(x.astype('<c16').tobytes()).hexdigest() == metrics[tag]['source_sha256']
            assert hashlib.sha256(y.astype('<c16').tobytes()).hexdigest() == metrics[tag]['received_sha256']
            n = np.arange(192)
            for row, component, component_name in ((0, np.real, 'I'), (1, np.imag, 'Q')):
                axes[row, col].plot(n, component(x[:192]), color='#2879ad', lw=1.2, label='Original source, matched start + FIR')
                axes[row, col].plot(n, component(y[:192]), color='#cf573f', lw=.8, marker='.', markersize=2,
                                    label='Received, prefix-only alignment')
                axes[row, col].set(xlabel='Sample within fixed 4096-point block', ylabel=component_name+' / source RMS')
            axes[0, col].set_title(f'{tag}: {status}')
            axes[0, col].legend(fontsize=7)
            axes[2, col].plot(np.arange(4096), abs(y-x), color='#555555', lw=.6)
            axes[2, col].axvspan(0, 191, alpha=.15, color='#2879ad', label='I/Q zoom above')
            for boundary in (1024, 2048, 3072):
                axes[2, col].axvline(boundary, color='gray', ls=':', lw=.6)
            axes[2, col].set(xlabel='Every sample in fixed block (raw offset 32768)', ylabel='Absolute complex difference', ylim=(0, error_limit))
            axes[2, col].legend(fontsize=7)
            for axis in axes[:, col]: axis.grid(alpha=.2)
        fig.suptitle(f'Point-by-point comparison: {label} (operator-provided name reference)\n'
                     'One common source RMS; all alignment parameters fixed from earlier 16384 samples')
        fig.savefig(DOCS/f'B210_RESIDUAL_POINTS_{bad}_2026-09-07.png', dpi=150)
        plt.close(fig)
