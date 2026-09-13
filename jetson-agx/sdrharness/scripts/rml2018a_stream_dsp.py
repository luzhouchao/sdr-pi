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
    def __init__(self, run_id, source, gpu, guard_backend='cpu', *, source_loader=None, total_blocks=2):
        c.require(type(total_blocks) is int and total_blocks in (2,96,192),'finite stream block count')
        c.require((source_loader is None and source.shape==(2048,1024) and total_blocks==2) or
                  (source is None and callable(source_loader)),'finite stream decoder source')
        self.source_loader=source_loader;self.total_frames=total_blocks*64
        self.sample_base=0;self.peak_samples=0
        c.require(guard_backend in ('cpu','cuda-batch'),'stream guard backend')
        self.guard_batch=None
        if guard_backend=='cuda-batch':
            from rml2018a_guard_gpu import GuardBatch
            self.guard_batch=GuardBatch(gpu.torch)
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
                # CUDA scalar indexing can call item() inside Python's GIL.
                # gather keeps the index on CUDA so RX/writer threads can run.
                frequency=hz.gather(0,t.div(flat,valid,rounding_mode='floor'))[0]
                candidates.append(t.stack((score,(flat[0]%valid).double(),
                    frequency)))
            winners=t.stack(candidates)
            winner=winners[:,0].argmax().reshape(1,1).expand(1,3)
            best=winners.gather(0,winner).cpu().numpy()[0]
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
        if self.frame==self.total_frames:return []
        z=iq[:,0].astype(np.float64)+1j*iq[:,1].astype(np.float64)
        self.samples=np.concatenate((self.samples,z))
        self.peak_samples=max(self.peak_samples,len(self.samples))
        c.require(len(self.samples)<=16*1024**2,'decoder finite RAM limit')
        if self.marker is None:
            if len(self.samples)<1048576:return []
            self.find_first()
        outputs=[]
        while self.frame<self.total_frames:
            predicted=self.marker if self.frame==0 else self.marker+FRAME_SAMPLES
            if predicted+65535+128>len(self.samples):break
            started=time.time_ns();at,hz,phase,score=self.track(predicted)
            origin=at-256;c.require(origin>=0,'complete leading guard')
            raw=self.samples[origin:origin+65535]
            sync=dict(marker_offset=256,payload_marker_offset=256,estimated_cfo_hz=hz)
            if self.guard_batch is None:
                corrected,info=guard.cancel(raw,sync,16,pilot_only=True)
            else:
                corrected=info=None
            positions=np.arange(at+1024,at+1024+16*1024)
            rotation=np.exp(-2j*np.pi*hz*positions/c.RATE+1j*phase)
            received=self.samples[positions]*rotation
            guarded=None if corrected is None else (corrected[1280:1280+16*1024]*rotation).reshape(16,1024)
            self.parts.append((received.reshape(16,1024),guarded,positions[::1024]+self.sample_base,origin))
            global_phase=phase if self.sample_base==0 else phase+2*np.pi*hz*self.sample_base/c.RATE
            self.records.append(dict(frame=self.frame,marker_offset=at+self.sample_base,cfo_hz=hz,phase_rotation_rad=global_phase,
                marker_score=score,guard=info,started_ns=started,finished_ns=time.time_ns()))
            self.marker=at;self.hz=hz;self.frame+=1
            if self.frame%64==0:
                if self.guard_batch is not None:
                    # Track pilots sequentially, then fit64 independent training
                    # guard sets together. CPU validation gates remain per frame.
                    raws=[self.samples[p[3]:p[3]+65535] for p in self.parts]
                    syncs=[dict(marker_offset=256,payload_marker_offset=256,estimated_cfo_hz=r['cfo_hz']) for r in self.records]
                    fits=self.guard_batch.fit(raws,syncs,16)
                    for k,(raw,sync,fit) in enumerate(zip(raws,syncs,fits)):
                        corrected,info=guard.cancel(raw,sync,16,pilot_only=True,frequency_fit=fit)
                        r=self.records[k];received,_,starts,origin=self.parts[k]
                        positions=np.arange(starts[0],starts[0]+16*1024)
                        rotation=np.exp(-2j*np.pi*r['cfo_hz']*positions/c.RATE+1j*r['phase_rotation_rad'])
                        guarded=(corrected[1280:1280+16*1024]*rotation).reshape(16,1024)
                        self.parts[k]=(received,guarded,starts,origin)
                        r['guard']=info;r['finished_ns']=time.time_ns()
                block=self.frame//64-1
                if self.source_loader is None:reference,snr=self.source[block*1024:(block+1)*1024],30
                else:reference,snr=self.source_loader(block)
                c.require(reference.shape==(1024,1024) and snr in range(-20,31,2),'source block shape/Z')
                received=np.concatenate([p[0] for p in self.parts]);guarded=np.concatenate([p[1] for p in self.parts])
                starts=np.concatenate([p[2] for p in self.parts]).astype('<i8')
                inputs={tag:self.gpu.normalize(value) for tag,value in dict(source=reference,raw=received,guard=guarded).items()}
                raw_q=self.gpu.quality(reference,received,np.full(1024,snr))
                guard_q=self.gpu.quality(reference,guarded,np.full(1024,snr))
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
                    release_before=None if self.frame==self.total_frames else self.sample_base+max(0,at+FRAME_SAMPLES-384)))
                self.parts=[];self.records=[]
                if self.source_loader is not None:
                    # Keep the next pilot/guard halo. Returned tensors and the
                    # caller's immutable RX arena retain all uncommitted data.
                    trim=max(0,at+FRAME_SAMPLES-384)
                    self.samples=self.samples[trim:].copy();self.marker-=trim;self.sample_base+=trim
                break  # Publish this block before tracking a later possibly bad frame.
        return outputs
