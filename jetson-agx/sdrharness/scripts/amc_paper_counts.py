#!/usr/bin/env python3
"""Compact integer counts and RF protocol facts from immutable campaign evidence."""
import csv,json,hashlib
from pathlib import Path

REPO=Path('/home/jetson/sdrharness');ROOT=REPO/'local-assets/amc-eval/results/paper-deployment-closeout-20260929'
MATCHED=REPO/'local-assets/amc-eval/results/matched-source-baseline-20260928'
CAPTURE=REPO/'local-assets/amc-eval/rf/validation-seed42-20260927'

def read(p):return json.loads(p.read_text())
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8388608),b''):h.update(b)
    return h.hexdigest()
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')

def run():
    audit=read(REPO/'docs/evidence/AMC_MATCHED_SOURCE_BASELINE_2026-09-28.json');assert sha(MATCHED/'retention-v1.json')==audit['retention']['sha256']
    retained={v['path']:v for v in read(MATCHED/'retention-v1.json')['files']}
    for name in ['strata.csv','plan.json','verification.json']:
        path=MATCHED/name;assert sha(path)==retained[str(path)]['sha256']
    p=read(MATCHED/'plan.json');rows=[];identities={}
    for r in csv.DictReader((MATCHED/'strata.csv').open()):
        if r['class_id']!='-1' or r['reference_bin']!='-1':continue
        n=int(r['rows']);source=int(r['source_correct']);matched=int(r['matched_correct']);raw=int(r['raw_correct']);guard=int(r['guard_correct']);fixed=int(r['raw_to_guard_fixed']);regressed=int(r['raw_to_guard_regressed']);both=raw-regressed;neither=n-raw-fixed
        assert min(both,neither,fixed,regressed)>=0 and both+neither+fixed+regressed==n and guard-raw==fixed-regressed
        path=MATCHED/r['dataset']/r['model']/'result.json';assert sha(path)==retained[str(path)]['sha256'];result=read(path)
        assert result['correct']==matched and result['rows']==n
        assert [result['original'][v]['correct'] for v in ['source','raw','guard']]==[source,raw,guard]
        rows.append(dict(dataset=r['dataset'],model=r['model'],rows=n,source_correct=source,matched_source_correct=matched,raw_correct=raw,guard_correct=guard,raw_wrong_guard_right=fixed,raw_right_guard_wrong=regressed,both_correct=both,both_wrong=neither))
        identities[r['dataset']+'/'+r['model']]=dict(result_path=str(path),result_sha256=sha(path),checkpoint_sha256=result['checkpoint_sha256'])
    assert len(rows)==32 and sum(r['rows'] for r in rows)==713385*8
    destination=REPO/'docs/evidence/AMC_PAPER_DEPLOYMENT_COUNTS_2026-09-29.csv'
    with destination.open('w') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    rf=[];parents={};frames=[]
    for d in p['datasets']:
        folder=CAPTURE/d['dataset'];seal=read(folder/'dataset-complete.json');assert sha(folder/'dataset-complete.json')==d['seal_sha256']
        for receipt in seal['batch_receipts']:
            batch=folder/f"batch-{receipt['batch']:05d}";br=read(batch/'batch-complete.json');assert sha(batch/'batch-complete.json')==receipt['sha256']
            path=batch/'plan.json';expected=next(x['sha256'] for x in br['files'] if x['path']=='plan.json');assert sha(path)==expected;plan=read(path)
            assert plan['rf']==dict(center_hz=2455000000,rate_sps=2100000,bandwidth_hz=1500000,lo_offset_hz=250000,tx_gain_db=60,rx_gain_db=50,rx_port='RX1/RX0/A_BALANCED',settle_ms=500)
            co=plan['transport']['contract'];assert co['factor']==4 and co['rolloff']==.25 and co['taps']==129 and co['frame_payload_samples']==2048 and co['frame_rf_samples']==14336
            rf.append(plan['rf']);parents[str(path)]=expected
        frames.append(dict(dataset=d['dataset'],rows=d['rows'],batches=seal['batches']))
    assert len(rf)==517
    write(ROOT/'paper-counts-verification.json',dict(status='passed',source_strata=dict(path=str(MATCHED/'strata.csv'),sha256=sha(MATCHED/'strata.csv')),output=dict(path=str(destination),sha256=sha(destination),rows=32),identity=identities,checks=['all 32 integer totals agree with sealed source/raw/guard/matched result counts','four paired outcomes sum to N','guard-raw correct counts equal corrected-regressed; same complete membership includes invalid SINR/fallback']))
    facts=dict(scope='Offline coaxial link validation, no OTA fading/deployment/real-time claim',rf_across_all_517_batches=rf[0],tx_device=dict(user_name='国产N210',paper_name='B210-compatible USB SDR, UHD B200/B210 family',serial='2508504',not_device='not NI/Ettus Ethernet USRP N210; authentic Ettus B210 branding not established'),rx_device=dict(user_name='P201',paper_name='P201 AD9361-based Linux/IIO receiver (vendor documentation: PZSDR P201Pro)',identity_scope='Retained vendor/port-routing evidence, no fresh live board probe',identity_evidence='docs/evidence/P201_RX_PORT_SELECTION_AUDIT_2026-09-07.json',port='front RX1 / IIO RX0 / A_BALANCED'),connection='TX A TX/RX -> 20 dB attenuator -> 15 cm coax -> P201 RX1; nominal attenuator/cable values from confirmed setup, not fresh calibration',gain_units='TX60 and RX50 are gain settings in dB; neither is calibrated RF output/input power in dBm',frame=dict(adc_tx_rate_sps=2100000,native_rate_sps=525000,rrc_factor=4,rrc_rolloff=.25,rrc_taps_each=129,rrc_span_native_intervals=32,tx_group_delay_adc_samples=64,rx_group_delay_adc_samples=64,native_guard_each=256,native_pilot=1024,native_payload=2048,native_total=3584,rf_guard_each=1024,rf_pilot=4096,rf_payload=8192,rf_nominal_frame=14336,frame_ms=14336/2100,windows_per_frame={'128_point':16,'1024_point':2},pilot='QPSK, 128 pseudorandom chips repeated 4 native samples/chip per half; two identical 512-native-sample halves; 1024 native samples total',pilot_original_marker_modulus=.2,pilot_multiplier=10**.5,pilot_modulus_before_batch_gain=.2*10**.5,payload_peak_before_batch_gain=.2*10**.5,tx_common_batch_gain='additional common peak rescaling after interpolation; original per-window amplitudes not transmitted'),processing=dict(receiver='P201 bounded IIO RX and transfer only; AGX synchronization/CFO-phase correction, guard-tone cancellation or unchanged-raw fallback, matched RRC and 4x decimation, separate per-window RMS',model_adapter={'rml2016a':'sum(abs(complex IQ))=1','rml2016b':'sum(abs(complex IQ))=1','rml2018a':'complex RMS=1','hisarmod2019':'complex RMS=1'},source='original frozen reader values; matched source is a separate amplitude-only control',sinr='source-assisted conditional estimate; paired results use same raw-reference bins; invalid separate',iio_buffer_samples=65536),historical_inference=dict(precision='FP32 weights/inputs, no autocast; PyTorch matmul/cuDNN TF32 flags disabled. Do not infer precision of every custom kernel.',batch_size=128,chunk_rows=2048,cpu_torch_threads=2,cpu_torch_interop_threads=1,power_mode='not recorded',clock_lock_state='not recorded',full_runtime_versions='not recorded as a complete historical snapshot; current environment is separately measured',latency='not recorded as repeatable forward/pipeline benchmark; job elapsed times include IO/loading and cannot substitute'),datasets=frames,parent_batch_plan_sha256=parents)
    write(ROOT/'rf-paper-facts.json',facts)
    print(json.dumps([r for r in rows if r['model']=='amc_mamba_d10'],indent=2))

if __name__=='__main__':run()
