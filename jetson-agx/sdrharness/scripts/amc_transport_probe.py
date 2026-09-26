"""Offline candidate only: fixed 4x RRC sample transport, no RF/model calls."""
import argparse,json,sys,hashlib
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from rml2018a_stream_dsp import packet
from amc_dataset_contract import read_selected
from amc_rrc_transport import taps, interpolate
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root=args.output
    root.mkdir(parents=True,exist_ok=True)
    plan=dict(factor=4,rolloff=.25,span_native_samples=32,rate_hz=2100000,
              maximum_row_relative_rms_error=.01,maximum_outside_fraction=.01,
              max_mean_error_over_source_rms=.01,scope='offline fixed candidate; no noise/channel/synchronization test')
    (root/'transport-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    q=4; h=taps()
    combined=np.convolve(h,h);sampled=combined[::q];center=len(sampled)//2
    assert abs(sampled[center]-1)<1e-12
    out={'plan':plan,'taps':h.tolist(),'taps_sha256':hashlib.sha256(h.tobytes()).hexdigest(),
         'combined_offcenter_sample_max':float(np.max(abs(np.delete(sampled,center)))),'datasets':{}}
    selection=json.loads(args.selection.read_text())
    selection=selection.get('source_selection',selection)
    for ds,entry in selection.items():
      contract=entry['contract']
      x,actual=read_selected(entry['source_path'],ds,np.array(contract['source_rows']),contract['class_names'],contract['source_sha256'])
      assert actual==contract
      assert hashlib.sha256(x.tobytes()).hexdigest()==entry['selected_iq_sha256']
      n,L=x.shape;frame,scales=packet(x,'amc-rrc-offline-20260926',window_samples=L,total_rows=n)
      # Full sequence convolution retains filter tails; receive has full context.
      tx=interpolate(frame);gain=.632455532033676/max(abs(tx));tx=(tx*gain).astype("<c8")
      rx=np.convolve(tx,h)[128:128+q*len(frame):q]/gain
      assert len(rx)==len(frame)
      indices=np.array([i//16*(1536+16*L)+1280+(i%16)*L for i in range(n)])
      got=np.stack([rx[i:i+L] for i in indices])/scales[:,None]
      rms=np.sqrt(np.mean(abs(x)**2,axis=1));evm=np.sqrt(np.mean(abs(got-x)**2,axis=1))/rms
      means=abs(got.mean(1)-x.mean(1))/rms
      # Whole waveform FFT includes pilot, row seams, finite filter and TX tails.
      fr=np.fft.fftfreq(len(tx),1/2100000);p=abs(np.fft.fft(tx))**2
      inside=(abs(fr)<=700000)&(abs(fr-250000)<=700000)
      outside=float(p[~inside].sum()/p.sum())
      result=dict(rows=n,native_length=L,tx_samples=len(tx),tx_seconds=len(tx)/2100000,
        tx_fc32_bytes=len(tx)*8,tx_peak=float(max(abs(tx))),tx_global_gain=float(gain),
        nominal_support_hz=328125,whole_waveform_outside_fraction=outside,
        max_relative_rms_error=float(max(evm)),median_relative_rms_error=float(np.median(evm)),
        max_mean_error_over_source_rms=float(max(means)),row_relative_rms_error=evm.tolist(),
        passed=bool(max(evm)<=.01 and max(means)<=.01 and outside<=.01))
      out['datasets'][ds]=result;print(ds,{k:v for k,v in result.items() if k!='row_relative_rms_error'},flush=True)
    (root/'transport-results.json').write_text(json.dumps(out,indent=2)+'\n')


if __name__ == "__main__":
    main()
