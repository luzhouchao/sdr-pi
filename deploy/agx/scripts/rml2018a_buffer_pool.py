"""Immutable receive buffers: release only after consumers and disk commits.

The processing watermark is conservative: future pilot/guard operations must
not need samples below it. No GPU disk reload or silent overflow eviction.
"""
from dataclasses import dataclass
import threading
import time
import numpy as np
import rml2018a_campaign as c


@dataclass
class Ticket:
    sequence: int
    offset: int
    samples: int
    iq: object
    received_ns: int
    raw_done_ns: int = 0
    gpu_done_ns: int = 0
    raw_sha256: str = ''


class BufferPool:
    def __init__(self, capacity, maximum_samples):
        c.require(type(capacity) is int and 0 < capacity <= 256 and
                  type(maximum_samples) is int and maximum_samples > 0, 'finite memory pool')
        self.capacity=capacity;self.maximum_samples=maximum_samples;self.next_offset=0;self.sequence=0
        self.held={};self.released=[];self.watermark=0;self.commit_ns=0;self.peak_buffers=0;self.peak_bytes=0
        self.lock=threading.Lock()

    def admit(self, iq, received_ns):
        c.require(iq.dtype==np.dtype('<i2') and iq.ndim==2 and iq.shape[1]==2 and
                  0<len(iq)<=1048576 and not iq.flags.writeable,'immutable ci16 receive block')
        with self.lock:
            c.require(len(self.held)<self.capacity,'memory pool full; stop RX without eviction')
            c.require(self.next_offset+len(iq)<=self.maximum_samples,'memory pool sample budget')
            ticket=Ticket(self.sequence,self.next_offset,len(iq),iq,received_ns)
            self.held[ticket.sequence]=ticket;self.next_offset+=len(iq);self.sequence+=1
            self.peak_buffers=max(self.peak_buffers,len(self.held))
            self.peak_bytes=max(self.peak_bytes,sum(t.samples*4 for t in self.held.values()))
            return ticket

    def raw_done(self,ticket,sha):
        with self.lock:
            c.require(self.held.get(ticket.sequence) is ticket and not ticket.raw_done_ns,'raw completion identity')
            ticket.raw_done_ns=time.time_ns();ticket.raw_sha256=sha;self._release()

    def gpu_done(self,ticket):
        with self.lock:
            c.require(self.held.get(ticket.sequence) is ticket and not ticket.gpu_done_ns,'GPU completion identity')
            ticket.gpu_done_ns=time.time_ns();self._release()

    def processed_committed(self,watermark):
        with self.lock:
            c.require(type(watermark) is int and self.watermark<=watermark<=self.maximum_samples,'processed watermark')
            self.watermark=watermark;self.commit_ns=time.time_ns();self._release()

    def _release(self):
        for key,t in list(self.held.items()):
            if t.raw_done_ns and t.gpu_done_ns and t.offset+t.samples<=self.watermark:
                self.released.append(dict(sequence=t.sequence,sample_offset=t.offset,samples=t.samples,
                    raw_done_ns=t.raw_done_ns,gpu_done_ns=t.gpu_done_ns,processed_commit_ns=self.commit_ns,
                    released_ns=time.time_ns(),raw_sha256=t.raw_sha256))
                t.iq=None;del self.held[key]

    def snapshot(self):
        with self.lock:
            return dict(capacity=self.capacity,peak_buffers=self.peak_buffers,peak_bytes=self.peak_bytes,
                held_buffers=len(self.held),released=list(self.released),committed_watermark=self.watermark)
