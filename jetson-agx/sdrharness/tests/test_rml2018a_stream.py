"""Stream framing and sequence-specific pilot tracking; no radio/GPU/model."""
import io
import json
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from rml2018a_stream_frames import read_frame
import rml2018a_stream_dsp as d


class StreamTests(unittest.TestCase):
    def test_binary_newlines_and_bounded_truncation(self):
        header=dict(schema_version=1,event='rx_chunk',bytes=16)
        wire=json.dumps(header).encode()+b'\n'+b'\n'*16
        self.assertEqual(read_frame(io.BytesIO(wire)),(header,b'\n'*16))
        with self.assertRaises(EOFError):read_frame(io.BytesIO(wire[:-1]))
        with self.assertRaises(ValueError):read_frame(io.BytesIO(b'x'*2049))
        header['bytes']=262148
        with self.assertRaises(ValueError):read_frame(io.BytesIO(json.dumps(header).encode()+b'\n'))

    def test_packet_contains128_distinct_pilots_and2048_original_rows_once(self):
        source=np.tile(np.exp(2j*np.pi*np.arange(1024)*.137),(2048,1))
        packet,scales=d.packet(source,'a'*32)
        self.assertEqual(len(packet),128*d.FRAME_SAMPLES)
        self.assertLessEqual(float(abs(packet).max()),.632456)
        for frame in (0,1,63,64,127):
            start=frame*d.FRAME_SAMPLES
            np.testing.assert_allclose(packet[start+256:start+1280],d.c.marker('a'*32,frame)*np.sqrt(10),atol=1e-7)
            np.testing.assert_allclose(packet[start+1280:start+1280+16*1024].reshape(16,1024),
                source[frame*16:(frame+1)*16]*scales[frame*16:(frame+1)*16,None],atol=1e-7)

    def test_tracking_uses_pilots_and_recovers_cfo_and_sample_offsets(self):
        source=np.tile(np.exp(2j*np.pi*np.arange(1024)*.137),(2048,1))
        packet,_=d.packet(source,'b'*32)
        decoder=d.Decoder('b'*32,source,None)
        n=np.arange(len(packet));decoder.samples=packet*np.exp(2j*np.pi*8300*n/d.c.RATE+.4j)
        decoder.hz=8000
        for frame in (0,1,63,64,126):
            decoder.frame=frame;expected=frame*d.FRAME_SAMPLES+256
            at,hz,phase,score=decoder.track(expected+9)
            self.assertEqual(at,expected);self.assertAlmostEqual(hz,8300,places=3);self.assertGreater(score,.99)
            decoder.hz=hz

    def test_local_pilot_fir_preserves_full_convolution_including_edges(self):
        from rml2018a_lo_cancellation import filtered_pilot
        rng=np.random.default_rng(144);z=rng.normal(size=65535)+1j*rng.normal(size=65535)
        decoder=d.Decoder('d'*32,np.zeros((2048,1024),complex),None)
        full=np.convolve(z,decoder.fir,mode='same')*np.exp(-2j*np.pi*8100*np.arange(len(z))/d.c.RATE)
        for at in (0,1,63,64,256,30000,len(z)-1024):
            actual=filtered_pilot(z,decoder.fir,at,8100)
            np.testing.assert_allclose(actual,full[at:at+1024],rtol=0,atol=1e-14)
        np.testing.assert_array_equal(filtered_pilot(z,decoder.fir,256,8100),full[256:1280])


if __name__=='__main__':unittest.main()
