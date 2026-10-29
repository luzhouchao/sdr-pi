"""原生短窗帧/保护区/载波保真回归；仅程序检验，不构建调制数据集。"""
from pathlib import Path
import sys
import os
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import rml2018a_campaign as c
import rml2018a_campaign_gpu as gpu
import rml2018a_stream_dsp as dsp
import rml2018a_lo_cancellation as lo
import rml2018a_guard_tone as guard


class NativeWindowTests(unittest.TestCase):
    def test_legacy_packet_byte_identity(self):
        rng=np.random.default_rng(101)
        source=rng.normal(size=(2048,1024))+1j*rng.normal(size=(2048,1024))
        peak=.2*np.sqrt(10);scales=peak/np.max(abs(source),axis=1);parts=[]
        for frame in range(128):
            x=source[frame*16:(frame+1)*16]*scales[frame*16:(frame+1)*16,None]
            parts.extend((np.zeros(256),c.marker('compat',frame)*np.sqrt(10),x.ravel(),np.zeros(256)))
        expected=np.concatenate(parts).astype('<c8')
        actual,factors=dsp.packet(source,'compat')
        np.testing.assert_array_equal(actual,expected)
        np.testing.assert_array_equal(factors,scales)

    def test_native_offsets_tail_and_carrier_preserved(self):
        # 含非零均值载波，确保裁剪和RMS未把载波去掉；尾帧不复制最后一行。
        for length in (128,1024):
            source=np.array([2+np.exp(2j*np.pi*np.arange(length)*(k+1)/length) for k in range(19)])
            packet,scales=dsp.packet(source,'native',window_samples=length,total_rows=19)
            frame_len=1536+16*length
            self.assertEqual(len(packet),2*frame_len)
            for frame in range(2):
                at=frame*frame_len+256
                sync=dict(payload_marker_offset=at,estimated_cfo_hz=0.,phase_rotation_rad=0.)
                recovered=lo.payload(packet,sync,16,window_samples=length)
                count=min(16,19-frame*16)
                np.testing.assert_allclose(recovered[:count],source[frame*16:frame*16+count]*scales[frame*16:frame*16+count,None],atol=3e-8)
                np.testing.assert_array_equal(recovered[count:],0)
                normalized=gpu.PayloadBatch('cpu',window_samples=length).normalize(recovered[:count])
                self.assertEqual(normalized.shape,(count,2,length))
                self.assertGreater(float(normalized[:,0,:].mean()),.8)
            intervals=lo.guard_intervals(256,16,window_samples=length)
            for begin,end in intervals:
                for n in range(begin,end):
                    self.assertTrue(n%frame_len < 256 or n%frame_len >= frame_len-256)

    def test_short_sinr_identity_and_invariance(self):
        n=np.arange(128);x=2+np.exp(2j*np.pi*n/16)
        original=x.copy()
        quality=c.receive_quality('synchronized',x,(.7+.3j)*x,12.,window_samples=128)
        self.assertEqual(quality['rx_sinr_status'],'estimated')
        self.assertAlmostEqual(quality['rx_sinr_db'],12.,places=10)
        self.assertTrue(quality['rx_sinr_method'].endswith('/native128-experimental'))
        c.validate_receive_quality(quality,12.,window_samples=128)
        np.testing.assert_array_equal(x,original)
        with self.assertRaises(ValueError): c.validate_receive_quality(quality,12.)
        q=c.receive_quality('synchronized',np.ones(128),np.ones(128),12.,window_samples=128)
        self.assertEqual(q['rx_sinr_reason'],'reference_not_identifiable')

    def test_short_guard_fits_only_guards_and_preserves_payload_tone(self):
        length=128;rows=320;n=np.arange(length)
        source=np.tile(2+np.exp(2j*np.pi*250000*n/c.RATE),(rows,1))
        wave,_=dsp.packet(source,'guard-native',window_samples=128,total_rows=rows)
        index=np.arange(c.RX_SAMPLES);clean=40*wave[:c.RX_SAMPLES]
        tone=7*np.exp(2j*np.pi*250003*index/c.RATE+.8j)
        raw=clean+tone;sync=dict(marker_offset=256,payload_marker_offset=256,estimated_cfo_hz=0.,phase_rotation_rad=0.)
        out,info=guard.cancel(raw,sync,16,window_samples=128)
        self.assertEqual(info['status'],'applied',info)
        x=lo.payload(clean,sync,16,window_samples=128);y=lo.payload(out,sync,16,window_samples=128)
        self.assertLess(np.mean(abs(y-x)**2)/np.mean(abs(x)**2),1e-8)
        changed=raw.copy();changed[1408:3200]+=300j
        _,second=guard.cancel(changed,sync,16,window_samples=128)
        for key in ('frequency_hz','amplitude_real','amplitude_imag'):
            self.assertEqual(info['v1'][key],second['v1'][key])
        drift=raw.copy();drift[index>30000]-=2*tone[index>30000]
        rejected,why=guard.cancel(drift,sync,16,window_samples=128)
        self.assertEqual(why['status'],'skipped')
        np.testing.assert_array_equal(drift,rejected)

    def test_stream_chunks_short_windows_partial_final_block(self):
        self.check_stream(128)

    def test_stream_native1024_partial_final_block(self):
        self.check_stream(1024)

    def check_stream(self,length):
        # 已知首导频位置只隔离首次CUDA搜索；真实逐帧track/feed/guard/RMS仍全部执行。
        rows=1041;run='native-chunks'
        rng=np.random.default_rng(92)
        source=2+.1*(rng.normal(size=(rows,length))+1j*rng.normal(size=(rows,length)))
        waveform,_=dsp.packet(source,run,window_samples=length,total_rows=rows)
        prefix=512;signal=np.pad(100*waveform,(prefix,70000));n=np.arange(len(signal))
        signal=signal*np.exp(2j*np.pi*8300*n/c.RATE+.4j)
        signal+=7*np.exp(2j*np.pi*258300*n/c.RATE+.8j)
        iq=np.stack((signal.real,signal.imag),axis=1).round().astype('<i2')
        decoder=dsp.Decoder(run,source,gpu.PayloadBatch('cpu',window_samples=length),
            window_samples=length,native_rows=rows,source_snr_db=np.full(rows,12.))
        decoder.marker=prefix+256;decoder.hz=8000.
        outputs=[]
        for start in range(0,len(iq),20000):outputs+=decoder.feed(iq[start:start+20000])
        while decoder.frame<decoder.total_frames:
            more=decoder.feed(np.empty((0,2),dtype='<i2'))
            self.assertTrue(more,'complete capture must drain final partial block')
            outputs+=more
        self.assertEqual([len(x['quality']) for x in outputs],[1024,17])
        starts=np.concatenate([x['sample_starts'] for x in outputs])
        expected=np.array([prefix+(k//16)*(1536+16*length)+1280+(k%16)*length for k in range(rows)])
        np.testing.assert_array_equal(starts,expected)
        for block in outputs:
            self.assertEqual(block['inputs']['raw'].shape[1:],(2,length))
            np.testing.assert_array_equal(block['sample_counts'],length)
        final=outputs[-1]['frames'][-1]['guard']
        self.assertEqual(final['status'],'skipped')
        self.assertEqual(final['reason'],'v1_insufficient_complete_guards')
        np.testing.assert_array_equal(outputs[-1]['inputs']['raw'][-1],outputs[-1]['inputs']['guard'][-1])
        # 最后仅1个有效窗，其余15个传输空位不进入模型输入/分母。
        self.assertEqual(sum(len(x['inputs']['raw']) for x in outputs),rows)

    def test_missing_pilot_stops_instead_of_shifting_row_ids(self):
        source=np.ones((33,128),complex);run='missing-pilot'
        wave,_=dsp.packet(source,run,window_samples=128,total_rows=33)
        wave[3584+256:3584+1280]=0
        signal=np.pad(100*wave,(0,70000))
        iq=np.stack((signal.real,signal.imag),axis=1).round().astype('<i2')
        decoder=dsp.Decoder(run,source,gpu.PayloadBatch('cpu',window_samples=128),
            window_samples=128,native_rows=33,source_snr_db=np.full(33,12.))
        decoder.marker=256;decoder.hz=0.
        with self.assertRaisesRegex(ValueError,'marker below'):decoder.feed(iq)
        self.assertEqual(decoder.frame,1)

    @unittest.skipUnless(os.environ.get('RML_TEST_CUDA')=='1','explicit offline CUDA validation')
    def test_cuda_native_quality_and_initial_search(self):
        import torch
        rng=np.random.default_rng(104)
        for length in (128,1024):
            x=rng.normal(size=(32,length))+1j*rng.normal(size=(32,length))
            y=x+.1*(rng.normal(size=x.shape)+1j*rng.normal(size=x.shape))
            x[0]=0;x[1]=1;y[2]=0;y[3,length//2:]*=10
            z=np.full(32,12.)
            cpu=gpu.PayloadBatch('cpu',window_samples=length)
            cuda=gpu.PayloadBatch('cuda',window_samples=length)
            expected=cpu.quality(x,y,z);actual=cuda.quality(x,y,z)
            for a,b in zip(expected,actual):
                self.assertEqual((a['rx_sinr_status'],a['rx_sinr_reason'],a['rx_sinr_method']),
                                 (b['rx_sinr_status'],b['rx_sinr_reason'],b['rx_sinr_method']))
                if a['rx_sinr_db'] is not None:self.assertLess(abs(a['rx_sinr_db']-b['rx_sinr_db']),1e-9)
            np.testing.assert_allclose(cpu.normalize(x[2:]),cuda.normalize(x[2:]),rtol=0,atol=1e-6)
        run='native-first-search';x=np.ones((16,128),complex)
        decoder=dsp.Decoder(run,x,gpu.PayloadBatch('cuda',window_samples=128),
            window_samples=128,native_rows=16,source_snr_db=np.full(16,12.))
        decoder.samples=np.zeros(1048576,complex);n=np.arange(4096,5120)
        decoder.samples[4096:5120]=c.marker(run,0)*np.exp(2j*np.pi*8000*n/c.RATE)
        decoder.find_first()
        self.assertEqual(decoder.marker,4096);self.assertEqual(decoder.hz,8000.)
        from rml2018a_guard_gpu import GuardBatch
        source=np.tile(2+np.exp(2j*np.pi*np.arange(128)/16),(320,1))
        wave,_=dsp.packet(source,'cuda-guard',window_samples=128,total_rows=320)
        n=np.arange(c.RX_SAMPLES);raw=40*wave[:c.RX_SAMPLES]+7*np.exp(2j*np.pi*250003*n/c.RATE+.8j)
        sync=dict(marker_offset=256,payload_marker_offset=256,estimated_cfo_hz=0.)
        fit=GuardBatch(torch).fit([raw],[sync],16,window_samples=128)[0]
        expected,a=guard.cancel(raw,sync,16,window_samples=128)
        actual,b=guard.cancel(raw,sync,16,window_samples=128,frequency_fit=fit)
        self.assertEqual((a['status'],a['reason']),(b['status'],b['reason']))
        self.assertEqual(a['status'],'applied')
        self.assertLess(np.sqrt(np.mean(abs(actual-expected)**2)/np.mean(abs(expected)**2)),1e-5)
        torch.cuda.synchronize()

    def test_reject_bad_windows_and_zero_sources(self):
        for length in (0,127,256,True):
            with self.assertRaises(ValueError):gpu.PayloadBatch('cpu',window_samples=length)
        with self.assertRaises(ValueError):dsp.packet(np.zeros((16,128),complex),'x',window_samples=128,total_rows=16)
        with self.assertRaises(ValueError):dsp.packet(np.ones((16,128),complex),'x')

if __name__=='__main__':unittest.main()
