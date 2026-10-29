"""Experimental many-frame CUDA guard fitting, with unchanged CPU validation.

Only training guards enter CUDA. No source IQ, labels, model or RF access.
The caller owns the persistent CUDA context and GPU lease. Not auto-selected.
"""
from dataclasses import dataclass
import numpy as np
import rml2018a_campaign as c
import rml2018a_lo_cancellation as lo


@dataclass(frozen=True)
class FrequencyFit:
    training_sha256: str
    indices_sha256: str
    prior_hz: float
    frequency_hz: object
    backend: str = 'cuda-fp64-batched-guard-search-v1-experimental'

    def verify(self,training,indices,prior):
        c.require(self.prior_hz==prior and self.training_sha256==c.digest(training.astype('<c16').tobytes())
                  and self.indices_sha256==c.digest(indices.astype('<i8').tobytes()),'guard fit input identity')
        return self.frequency_hz


class GuardBatch:
    def __init__(self,torch):
        self.torch=torch
        # Reused small search grids, no per-frame GPU/context initialization.
        self.offsets=torch.arange(-30,31,device='cuda',dtype=torch.float64)

    def fit(self,raws,syncs,row_count=16, *, window_samples=1024):
        c.require(len(raws)==len(syncs) and 0<len(raws)<=128,'bounded guard batch')
        values=[];indices=[];priors=[]
        for raw,sync in zip(raws,syncs):
            z=np.asarray(raw,dtype=np.complex128)
            c.require(z.shape==(c.RX_SAMPLES,) and np.isfinite(z).all(),'guard batch native IQ')
            intervals=lo.guard_intervals(sync['payload_marker_offset'],row_count,window_samples=window_samples)
            c.require(len(intervals)>=2,'complete guard batch')
            n=np.concatenate([np.arange(a,a+192) for a,b in intervals])
            hz=sync['estimated_cfo_hz']
            c.require(np.isfinite(hz) and abs(hz)<=c.CFO_LIMIT_HZ,'guard batch CFO')
            values.append(z[n]);indices.append(n);priors.append(250000+hz)
        c.require(all(len(x)==len(indices[0]) for x in indices),'uniform guard training lengths')
        t=self.torch
        with t.inference_mode():
            samples=t.from_numpy(np.stack(values)).cuda()
            n=t.from_numpy(np.stack(indices)).cuda()
            center=t.tensor(priors,device='cuda',dtype=t.float64)
            def project(frequencies):
                return (samples[:,None,:]*t.exp(-2j*np.pi*frequencies[:,:,None]*n[:,None,:]/c.RATE)).mean(2).abs()
            frequencies=center[:,None]+self.offsets[None,:]
            best=project(frequencies).argmax(1)
            selected=frequencies.gather(1,best[:,None])[:,0]
            low,high=selected-1,selected+1
            for _ in range(50):
                left,right=low+(high-low)/3,high-(high-low)/3
                projections=project(t.stack((left,right),1))
                choose_left=projections[:,0]>projections[:,1]
                low,high=t.where(choose_left,low,left),t.where(choose_left,right,high)
            # One transfer for all frames, including boundary rejection state.
            result=t.stack(((low+high)/2,((best==0)|(best==60)).double()),1).cpu().numpy()
        return [FrequencyFit(c.digest(v.astype('<c16').tobytes()),c.digest(n.astype('<i8').tobytes()),float(p),
                             None if boundary else float(f))
                for v,n,p,(f,boundary) in zip(values,indices,priors,result)]
