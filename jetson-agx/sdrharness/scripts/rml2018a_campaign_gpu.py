"""Bounded offline payload DSP; no radio, model, or GPU initialization on import.

CUDA uses FP64 reductions and FP32 normalized outputs, without autocast. The
caller owns the existing GpuLease and disk/receive lifecycle. This is an
explicit experimental backend, not a change to frozen RF-v1 input hashes.
"""
import numpy as np

import rml2018a_campaign as c

MAX_BATCH = 8192
SNR_ROWS = 98304
ROWS_PER_BLOCK = 1024
BLOCKS_PER_SNR = SNR_ROWS // ROWS_PER_BLOCK


def snr_block_rows(snr_db, block):
    c.require(type(block) is int and 0 <= block < BLOCKS_PER_SNR, 'SNR block index')
    return snr_rows(snr_db, block*ROWS_PER_BLOCK, ROWS_PER_BLOCK)


def snr_rows(snr_db, start=0, count=SNR_ROWS):
    """Original row IDs, class-major within one complete original-Z group."""
    c.require(type(snr_db) is int and snr_db in range(-20, 31, 2), 'source Z group')
    c.require(type(start) is int and type(count) is int and
              0 <= start < SNR_ROWS and 0 < count <= SNR_ROWS-start, 'SNR row range')
    q = np.arange(start, start+count, dtype=np.int64)
    return q//4096*106496 + (snr_db+20)//2*4096 + q%4096


def windows(value, window_samples=1024):
    c.require(type(window_samples) is int and window_samples in (128,1024), 'native window length')
    value = np.asarray(value)
    c.require(value.ndim == 2 and value.shape[1] == window_samples and
              0 < len(value) <= MAX_BATCH and np.iscomplexobj(value), 'bounded complex windows')
    c.require(np.isfinite(value).all(), 'finite windows')
    return np.ascontiguousarray(value, dtype=np.complex128)


class PayloadBatch:
    def __init__(self, device='cuda', *, window_samples=1024):
        c.require(device in ('cpu', 'cuda'), 'payload device')
        c.require(type(window_samples) is int and window_samples in (128,1024), 'native window length')
        self.window_samples = window_samples
        self.device = device
        if device == 'cuda':
            import torch
            c.require(torch.cuda.is_available(), 'CUDA unavailable')
            self.torch = torch

    def normalize(self, value):
        """复数[N,L]转float32[N,2,L]；L显式固定为128或1024，保留载波。"""
        z = windows(value, self.window_samples)
        if self.device == 'cpu':
            rms = np.sqrt(np.mean(abs(z)**2, axis=1))
            c.require(np.isfinite(rms).all() and (rms > 0).all(), 'model zero/nonfinite RMS')
            return np.ascontiguousarray(np.stack((z.real, z.imag), axis=1)/rms[:, None, None], dtype=np.float32)
        t = self.torch
        with t.inference_mode():
            x = t.from_numpy(z).to('cuda')
            rms = x.abs().square().mean(dim=1).sqrt()
            c.require(bool((t.isfinite(rms) & (rms > 0)).all().item()), 'model zero/nonfinite RMS')
            out = t.stack((x.real, x.imag), dim=1)/rms[:, None, None]
            return out.float().cpu().numpy()

    def quality(self, reference, received, source_snr_db):
        """Synchronized rows only. Missing/sync-failed rows keep the CPU contract.

        The vectorized reductions return the same fields/rejection order as
        receive_quality. Numerical agreement must be checked before admitting
        a new backend; near-threshold rounding is not a reason to loosen gates.
        """
        x, y = windows(reference, self.window_samples), windows(received, self.window_samples)
        snr = np.asarray(source_snr_db, dtype=np.float64)
        c.require(x.shape == y.shape and snr.shape == (len(x),) and
                  np.isfinite(snr).all() and ((snr >= -20) & (snr <= 30)).all(), 'batch quality inputs/Z')
        if self.device == 'cpu':
            return [c.receive_quality('synchronized', a, b, float(z), window_samples=self.window_samples) for a, b, z in zip(x, y, snr)]
        t = self.torch
        with t.inference_mode():
            x, y = t.from_numpy(x).to('cuda'), t.from_numpy(y).to('cuda')
            xp, yp = x.abs().square().mean(1), y.abs().square().mean(1)
            # Substitutions only prevent NaNs on rejected rows, not acceptance.
            x = x/t.where(xp > 0, xp, 1.).sqrt()[:, None]
            y = y/t.where(yp > 0, yp, 1.).sqrt()[:, None]
            x, y = x.reshape(-1, 2, self.window_samples//2), y.reshape(-1, 2, self.window_samples//2)
            xc, yc = x-x.mean(2, keepdim=True), y-y.mean(2, keepdim=True)
            energy = (xc.conj()*xc).real.sum(2)
            original = (x.conj()*x).real.sum(2)
            identifiable = ((energy >= 1e-4*original) & (energy > 1e-12)).all(1)
            gain = (xc.conj()*yc).sum(2)/t.where(energy > 0, energy, 1.)
            prediction = gain[:, :, None]*x.flip(1)
            predicted = prediction.abs().square().mean(2)
            residual = (y.flip(1)-prediction).abs().square().mean(2)
            signal, error = predicted.mean(1), residual.mean(1)
            disagreement = (gain[:, 0]-gain[:, 1]).abs()/gain.abs().square().mean(1).sqrt().clamp_min(1e-15)
            ratio = residual.max(1).values/residual.min(1).values.clamp_min(1e-12)
            packed = t.stack((xp, yp, identifiable.double(), signal, error, disagreement, ratio,
                              predicted[:, 0], predicted[:, 1], residual[:, 0], residual[:, 1]), 1).cpu().numpy()
        rows = []
        for values, z in zip(packed, snr):
            xp, yp, identifiable, signal, error, disagreement, ratio, p0, p1, e0, e1 = map(float, values)
            out = c.receive_quality('synchronized', window_samples=self.window_samples)
            reason = ('zero_reference_or_receive_power' if xp <= 0 or yp <= 0 else
                      'reference_not_identifiable' if not identifiable else
                      'reference_not_detectable' if signal <= 1e-12 else None)
            if reason is None:
                fraction = 1./(1.+10.**(float(z)/10.))
                noise, desired = signal*fraction, signal*(1.-fraction)
                value = float(10*np.log10(desired/(noise+error)))
                out['rx_sinr_diagnostics'] = dict(received_power_adc_squared=yp,
                    predicted_reference_power_relative=signal, link_error_power_relative=error,
                    nominal_source_noise_power_relative=noise, nominal_desired_power_relative=desired,
                    gain_disagreement=disagreement, residual_power_ratio=ratio,
                    fold_predicted_powers_relative=[p0, p1], fold_error_powers_relative=[e0, e1],
                    reference_residual_db=float(10*np.log10(signal/error)) if error > 1e-12 else None,
                    source_snr_db=float(z), source_noise_fraction=fraction)
                reason = ('gain_not_stable_across_halves' if disagreement > .25 else
                          'residual_not_stationary_across_halves' if ratio > 4. else
                          'reference_below_estimator_range' if signal < .1*error else None)
                if reason is None:
                    out.update(rx_sinr_db=value, rx_sinr_status='estimated', rx_sinr_reason=None)
            if reason is not None:
                out.update(rx_sinr_status='invalid', rx_sinr_reason=reason)
            rows.append(out)
        return rows
