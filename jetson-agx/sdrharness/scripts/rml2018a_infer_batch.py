"""Explicit engineering batch adapter for the frozen RF-v1 model.

Does not alter the production worker or normalize inputs again. The caller owns
the model, GPU lease, finite budget, and cancellation between CUDA calls.
"""
import numpy as np
import rml2018a_campaign as c

BATCH_SIZES = (256, 512, 1024, 4096, 8192)
MAX_ROWS = 32768


class Graph:
    """Fixed-shape CUDA replay with unchanged FP32 weights/FP16 autocast."""
    def __init__(self, backend, size, independent=False):
        import torch
        self.input = torch.zeros((size,2,1024),device='cuda',dtype=torch.float32)
        branches=[torch.cuda.Stream() for _ in range(size)] if independent else []
        def forward():
            if not independent: return backend.model(self.input)
            origin=torch.cuda.current_stream();outputs=[]
            for i,branch in enumerate(branches):
                branch.wait_stream(origin)
                with torch.cuda.stream(branch):outputs.append(backend.model(self.input[i:i+1]))
            for branch in branches:origin.wait_stream(branch)
            return torch.cat(outputs,dim=0)
        stream = torch.cuda.Stream();stream.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(stream), torch.inference_mode(), torch.autocast('cuda',dtype=torch.float16,cache_enabled=False):
            for _ in range(2): forward()
        torch.cuda.current_stream().wait_stream(stream)
        self.graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(self.graph), torch.inference_mode(), torch.autocast('cuda',dtype=torch.float16,cache_enabled=False):
            self.output = forward()
        backend._snr_graph_warmup_windows = getattr(backend,'_snr_graph_warmup_windows',0)+size*3

    def predict(self, values):
        import torch
        host = torch.from_numpy(np.ascontiguousarray(values)).pin_memory()
        self.input[:len(values)].copy_(host,non_blocking=True)
        if len(values) < len(self.input): self.input[len(values):].zero_()
        self.graph.replay()
        return self.output[:len(values)].float().cpu().numpy()


def graph(backend, size, independent=False):
    if not hasattr(backend,'_snr_graphs'): backend._snr_graphs = {}
    key=(size,independent)
    if key not in backend._snr_graphs: backend._snr_graphs[key] = Graph(backend,size,independent)
    return backend._snr_graphs[key]


def sensitive_rows(logits):
    """Conservative FP16 quantization sensitivity; never rejects a source row.

Re-evaluate sensitive logits through a batch-one CUDA graph. This numerical
fallback does not inspect class labels or the single-window reference result.
"""
    y=logits.astype(np.float64);e=np.exp(y-y.max(axis=1,keepdims=True));p=e/e.sum(axis=1,keepdims=True)
    ulp=np.spacing(np.max(np.abs(logits),axis=1).astype(np.float16)).astype(np.float64)
    return (4*ulp[:,None]*p*(1-p)).max(axis=1)>0.0025


def close_top_two(logits):
    top=np.sort(logits,axis=1)[:,-2:]
    spacing=np.spacing(np.abs(top).astype(np.float16)).astype(np.float64)
    return top[:,1]-top[:,0]<=4*spacing.sum(axis=1)


def infer(backend, inputs, batch_size, check=lambda: None, progress=lambda n: None):
    import torch
    c.require(batch_size in BATCH_SIZES and isinstance(inputs,np.ndarray) and
              inputs.dtype == np.float32 and inputs.ndim == 3 and
              inputs.shape[1:] == (2,1024) and len(inputs) <= MAX_ROWS and np.isfinite(inputs).all(),
              'bounded batch model input')
    output = np.empty((len(inputs),24),dtype=np.float32)
    for start in range(0,len(inputs),batch_size):
        check()
        values = np.ascontiguousarray(inputs[start:start+batch_size])
        logits = graph(backend,batch_size).predict(values)
        c.require(logits.shape == (len(values),24) and np.isfinite(logits).all(), 'finite batched logits')
        close = close_top_two(logits)
        selected = np.flatnonzero(sensitive_rows(logits)|close)
        for offset in range(0,len(selected),16):
            check()
            subset=selected[offset:offset+16]
            logits[subset] = graph(backend,16,independent=True).predict(values[subset])
            progress(len(subset))
        backend._snr_fallback_windows = getattr(backend,'_snr_fallback_windows',0)+len(selected)
        output[start:start+len(values)] = logits
        progress(len(values))
    return output
