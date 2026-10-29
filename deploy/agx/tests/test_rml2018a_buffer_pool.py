"""Receive memory ownership under asynchronous processing and durable writes."""
import itertools
from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from rml2018a_buffer_pool import BufferPool


def iq():
    return np.frombuffer(bytes(32),dtype='<i2').reshape(-1,2)


class BufferPoolTests(unittest.TestCase):
    def test_every_completion_order_retains_until_all_three_gates(self):
        for order in itertools.permutations(('raw','gpu','commit')):
            pool=BufferPool(2,16);ticket=pool.admit(iq(),1)
            actions={'raw':lambda:pool.raw_done(ticket,'a'*64),
                     'gpu':lambda:pool.gpu_done(ticket),
                     'commit':lambda:pool.processed_committed(8)}
            for i,action in enumerate(order):
                actions[action]()
                self.assertEqual(ticket.iq is None,i==2)
            proof=pool.snapshot()['released'][0]
            self.assertGreaterEqual(proof['released_ns'],max(proof[k] for k in
                ('raw_done_ns','gpu_done_ns','processed_commit_ns')))

    def test_cross_block_dependency_and_capacity_never_evict(self):
        pool=BufferPool(1,16);ticket=pool.admit(iq(),1)
        pool.raw_done(ticket,'b'*64);pool.gpu_done(ticket)
        pool.processed_committed(7)
        with self.assertRaises(ValueError):pool.admit(iq(),2)
        self.assertIsNotNone(ticket.iq)
        pool.processed_committed(8)
        second=pool.admit(iq(),2)
        self.assertEqual(second.offset,8)
        self.assertEqual(pool.snapshot()['peak_buffers'],1)

    def test_failed_consumer_retains_buffer_and_rejects_stale_callbacks(self):
        pool=BufferPool(2,16);ticket=pool.admit(iq(),1)
        pool.raw_done(ticket,'c'*64);pool.processed_committed(8)
        self.assertEqual(pool.snapshot()['held_buffers'],1)
        with self.assertRaises(ValueError):pool.raw_done(ticket,'c'*64)
        pool.gpu_done(ticket)
        with self.assertRaises(ValueError):pool.gpu_done(ticket)
        with self.assertRaises(ValueError):pool.processed_committed(7)
        with self.assertRaises(ValueError):pool.processed_committed(17)

    def test_mutable_input_and_sample_budget_rejected(self):
        pool=BufferPool(2,8)
        with self.assertRaises(ValueError):pool.admit(iq().copy(),1)
        pool.admit(iq(),1)
        with self.assertRaises(ValueError):pool.admit(iq(),2)


if __name__=='__main__':unittest.main()
