"""Versioned amplitude lineage and explicit center binding; synthetic IQ, no RF."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
spec=importlib.util.spec_from_file_location('margin',Path(__file__).resolve().parents[1]/'scripts/validate-b210-2455-margin.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class MarginTests(unittest.TestCase):
    def test_float32_derivation_preserves_every_sample_and_order(self):
        v=np.linspace(-.08,.08,2048,dtype='<f4');parent=v.tobytes()
        expected=struct.pack('<2048f',*[float(x)*1.5 for x in v])
        h=hashlib.sha256(parent).hexdigest()
        with patch.object(m.lo,'SOURCE_HASH',h),patch.object(m,'HASHES',{.2:h,.3:hashlib.sha256(expected).hexdigest()}):
            self.assertEqual(m.derive(parent,.2),parent)
            self.assertEqual(m.derive(parent,.3),expected)
        for data,peak in ((parent,.2),(parent[:-1],.3),(parent,.4)):
            with self.assertRaises(ValueError):m.derive(data,peak)

class CenterBindingTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']);self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        history=json.loads((m.live.affine.ROOT/'docs/B210_RX_AFFINE_AUDIT_2026-09-06.json').read_text())
        self.link=copy.deepcopy(history['links']['tone']);self.link['feature_directory']=str(self.root);self.link['center_hz']=2455000000
        self.link['radio_before']=self.link['radio_after']=history['final_radio_state']
        for i,(tag,field) in enumerate((('baseline','baseline'),('during-tx','during_tx'),('after-tx','after_tx'))):
            root=self.root/tag;root.mkdir();data=root/'iq.sigmf-data';data.write_bytes(bytes(262140));meta=root/'iq.sigmf-meta'
            report=self.link[field];point=report['points'][0]
            point['requested_center_hz']=point['actual_center_hz']=2455000000
            self.link['plans'][i]['frequencies']['centers_hz']=[2455000000]
            report['dataset'].update(data_path=str(data),metadata_path=str(meta))
            meta.write_text(json.dumps({'global':{'core:sample_rate':2500000,'core:datatype':'ci16_le','sdrharness:sample_layout':'interleaved_iq'},
             'captures':[{'core:sample_start':0,'core:frequency':2455000000,'sdrharness:point_index':0,'sdrharness:rf_bandwidth_hz':1000000,'sdrharness:gain_db':40}]}))
        self.save()
    def save(self):
        (self.root/'link-summary.json').write_text(json.dumps(self.link))
        for tag,field in (('baseline','baseline'),('during-tx','during_tx'),('after-tx','after_tx')):(self.root/f'{tag}-report.json').write_text(json.dumps(self.link[field]))
    def test_new_center_requires_explicit_expected_contract(self):
        with self.assertRaises(AssertionError):m.live.validate_capture_root(self.root,'tone')
        self.assertEqual(len(m.live.validate_capture_root(self.root,'tone',expected_center_hz=2455000000)['captures']),3)
    def test_wrong_rx_and_mixed_center_rejected(self):
        self.link['during_tx']['points'][0]['actual_center_hz']=2440000000;self.save()
        with self.assertRaises(AssertionError):m.live.validate_capture_root(self.root,'tone',expected_center_hz=2455000000)
        self.link['during_tx']['points'][0]['actual_center_hz']=2455000000
        self.link['during_tx']['points'][0]['rx_input']['front_panel_port']='RX2';self.save()
        with self.assertRaises(AssertionError):m.live.validate_capture_root(self.root,'tone',expected_center_hz=2455000000)

if __name__=='__main__':unittest.main()
