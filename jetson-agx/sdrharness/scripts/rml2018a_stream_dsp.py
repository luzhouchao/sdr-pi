"""Finite experimental16-row pilot frames grouped into1024-row GPU jobs.

Payload is unfiltered. Pilot-only FIR/CFO search uses existing bounds and
thresholds. Guard cancellation keeps its existing contract; no model is used.
"""
import time
import numpy as np
import rml2018a_campaign as c
import rml2018a_campaign_gpu as g
import rml2018a_guard_tone as guard

FRAME_ROWS = 16
FRAME_SAMPLES = 2*c.GUARD+c.MARKER+FRAME_ROWS*1024
FRAMES_PER_BLOCK = 64


def packet(source, run_id):
    c.require(source.shape == (2048,1024) and np.isfinite(source).all(), 'finite2048 source windows')
    peak = .2*np.sqrt(10.)
    scales = peak/np.max(abs(source),axis=1)
    parts = []
    for frame in range(128):
        x = source[frame*16:(frame+1)*16]*scales[frame*16:(frame+1)*16,None]
        parts.extend((np.zeros(256), c.marker(run_id,frame)*np.sqrt(10.), x.ravel(), np.zeros(256)))
    return np.concatenate(parts).astype('<c8'), scales


class Decoder:
    def __init__(self, run_id, source, gpu):
        c.require(source.shape == (2048,1024), 'finite stream decoder scope')
        self.run_id=run_id; self.source=source; self.gpu=gpu; self.samples=np.empty(0,np.complex128)
        self.frame=0; self.marker=None; self.hz=None; self.parts=[]; self.records=[]
        t=np.arange(129)-64
        self.fir=(2*500000/c.RATE)*np.sinc(2*500000/c.RATE*t)*np.hamming(129);self.fir/=self.fir.sum()

    def find_first(self):
        """Same59 CFO hypotheses in bounded CUDA batches, one initial search."""
        t=self.gpu.torch
        z=np.convolve(self.samples[:1048576],self.fir,mode='same')
        ref=np.convolve(c.marker(self.run_id,0),self.fir,mode='same')
        fft_size=1<<(len(z)+1022).bit_length();valid=len(z)-1024+1
        energy=np.concatenate(([0.],np.cumsum(abs(z)**2)))
        window_energy=energy[1024:]-energy[:-1024]
        # FFT roundoff over an exact-zero preamble must not become a huge
        # normalized score through the denominator floor. Reject such windows.
        identifiable=window_energy>max(float(window_energy.max())*1e-12,1e-30)
        denom=np.sqrt(np.maximum(window_energy*np.vdot(ref,ref).real,1e-30))
        candidates=[]
        with t.inference_mode():
            signal=t.from_numpy(z).cuda(); n=t.arange(len(z),device='cuda',dtype=t.float64)
            kernel=t.fft.fft(t.from_numpy(ref[::-1].conj().copy()).cuda(),n=fft_size)
            denominator=t.from_numpy(denom).cuda()
            candidate=t.from_numpy(identifiable).cuda()
            frequencies=list(range(-c.CFO_SEARCH_MAX_HZ,c.CFO_SEARCH_MAX_HZ+1,500))
            for k in range(0,len(frequencies),4):
                hz=t.tensor(frequencies[k:k+4],device='cuda',dtype=t.float64)
                corrected=signal[None,:]*t.exp(-2j*np.pi*hz[:,None]*n[None,:]/c.RATE)
                corr=t.fft.ifft(t.fft.fft(corrected,n=fft_size,dim=1)*kernel[None,:],dim=1)[:,1023:1023+valid]
                scores=corr.abs()/denominator[None,:]
                scores=t.where(candidate[None,:],scores,0.)
                # Keep batch winners on CUDA. One host synchronization after
                # all59 hypotheses, instead of two scalar synchronizations/batch.
                flat=scores.argmax().reshape(1)
                score=scores.reshape(-1).gather(0,flat)[0]
                candidates.append(t.stack((score,(flat[0]%valid).double(),
                    hz[flat[0]//valid])))
            winners=t.stack(candidates)
            best=winners[winners[:,0].argmax()].cpu().numpy()
        c.require(best[0]>=.55,'stream first marker not found')
        self.marker=int(best[1]);self.hz=float(best[2])

    def track(self, predicted):
        lo=max(0,predicted-128);hi=predicted+1024+128
        n=np.arange(lo,hi)
        local=np.convolve(self.samples[max(0,lo-64):hi+64],self.fir,mode='same')
        trim=lo-max(0,lo-64);local=local[trim:trim+len(n)]
        ref=np.convolve(c.marker(self.run_id,self.frame),self.fir,mode='same')
        def locate(hz):
            values=local*np.exp(-2j*np.pi*hz*n/c.RATE)
            corr=np.correlate(values,ref,mode='valid')
            energy=np.concatenate(([0.],np.cumsum(abs(values)**2)))
            scores=abs(corr)/np.sqrt(np.maximum((energy[1024:]-energy[:-1024])*np.vdot(ref,ref).real,1e-30))
            at=int(np.argmax(scores));return values,at,float(scores[at])
        values,at,score=locate(self.hz)
        c.require(score>=.55,'stream tracked marker below coarse gate')
        pilot=values[at:at+1024]
        hz=self.hz+float(np.angle(np.vdot(pilot[64:448],pilot[576:960]))*c.RATE/(2*np.pi*512))
        c.require(abs(hz)<=c.CFO_LIMIT_HZ,'stream CFO bound')
        values,at,score=locate(hz);c.require(score>=.65,'stream tracked marker below final gate')
        gain=np.vdot(ref,values[at:at+1024])/np.vdot(ref,ref)
        return lo+at,hz,float(-np.angle(gain)),score

    def feed(self, iq):
        """Called while RX continues; returns zero or more full1024-row results."""
        if self.frame==128:return []
        z=iq[:,0].astype(np.float64)+1j*iq[:,1].astype(np.float64)
        self.samples=np.concatenate((self.samples,z))
        c.require(len(self.samples)<=16*1024**2,'decoder finite RAM limit')
        if self.marker is None:
            if len(self.samples)<1048576:return []
            self.find_first()
        outputs=[]
        while self.frame<128:
            predicted=self.marker if self.frame==0 else self.marker+FRAME_SAMPLES
            if predicted+65535+128>len(self.samples):break
            started=time.time_ns();at,hz,phase,score=self.track(predicted)
            origin=at-256;c.require(origin>=0,'complete leading guard')
            raw=self.samples[origin:origin+65535]
            sync=dict(marker_offset=256,payload_marker_offset=256,estimated_cfo_hz=hz)
            corrected,info=guard.cancel(raw,sync,16,pilot_only=True)
            positions=np.arange(at+1024,at+1024+16*1024)
            rotation=np.exp(-2j*np.pi*hz*positions/c.RATE+1j*phase)
            received=self.samples[positions]*rotation
            guarded=corrected[1280:1280+16*1024]*rotation
            self.parts.append((received.reshape(16,1024),guarded.reshape(16,1024),positions[::1024]))
            self.records.append(dict(frame=self.frame,marker_offset=at,cfo_hz=hz,phase_rotation_rad=phase,
                marker_score=score,guard=info,started_ns=started,finished_ns=time.time_ns()))
            self.marker=at;self.hz=hz;self.frame+=1
            if self.frame%64==0:
                block=self.frame//64-1;reference=self.source[block*1024:(block+1)*1024]
                received=np.concatenate([p[0] for p in self.parts]);guarded=np.concatenate([p[1] for p in self.parts])
                starts=np.concatenate([p[2] for p in self.parts]).astype('<i8')
                inputs={tag:self.gpu.normalize(value) for tag,value in dict(source=reference,raw=received,guard=guarded).items()}
                raw_q=self.gpu.quality(reference,received,np.full(1024,30.))
                guard_q=self.gpu.quality(reference,guarded,np.full(1024,30.))
                quality=[]
                guard_hashes=[c.digest(__import__('json').dumps(r['guard'],sort_keys=True).encode()) for r in self.records]
                for k in range(1024):
                    r=self.records[k//16]
                    guard_q[k].update(rx_sinr_reference_plane=guard.PLANE,
                        rx_interference_cancellation=guard.METHOD if r['guard']['status']=='applied' else 'none_skipped')
                    quality.append(dict(raw=raw_q[k],guard=guard_q[k],sync=dict(status='synchronized',frame=r['frame'],
                        marker_score=r['marker_score'],cfo_hz=r['cfo_hz'],phase_rotation_rad=r['phase_rotation_rad']),
                        guard_diagnostics_sha256=guard_hashes[k//16]))
                outputs.append(dict(block=block,inputs=inputs,masks={t:np.ones(1024,bool) for t in inputs},
                    sample_starts=starts,sample_counts=np.full(1024,1024,dtype='<i8'),quality=quality,
                    frames=self.records,finished_ns=time.time_ns(),
                    release_before=None if self.frame==128 else max(0,at+FRAME_SAMPLES-384)))
                self.parts=[];self.records=[]
                break  # Publish this block before tracking a later possibly bad frame.
        return outputs
