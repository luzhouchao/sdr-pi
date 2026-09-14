"""Contracts for new HDF5s and resumable all-model engineering evaluation."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import h5py
import numpy as np

spec = importlib.util.spec_from_file_location(
    "collection_eval", Path(__file__).resolve().parents[1] / "scripts/rml2018a_model_collection_eval.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


class Contracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.small = patch.object(ev, "ROWS", 12)
        self.small.start()
        self.labels = np.arange(12, dtype=np.int16)
        self.snr = np.arange(-20, 4, 2, dtype=np.int16)
        self.classes = [str(i) for i in range(24)]

    def tearDown(self):
        self.small.stop()
        self.temp.cleanup()

    def cleaned(self):
        p = self.root / "clean.h5"
        ids = np.arange(11, -1, -1)
        with h5py.File(p, "w") as f:
            f.attrs.update(status="complete", rows_written=12,
                           usable_required_mask=35, strict_quality_required_mask=63,
                           quality_flag_definitions_json=json.dumps({str(b):str(b) for b in (1,2,4,8,16,32)}))
            f["iq"] = np.ones((12,2,1024),np.float32) / np.float32(np.sqrt(2))
            f["class_names"] = np.array(self.classes, dtype=h5py.string_dtype())
            f["class_id"] = self.labels[ids]
            f["source_snr_db"] = self.snr[ids]
            f["source_row"] = ids
            f["quality_flags"] = np.array([35,63]*6, np.uint16)
            f["usable"] = np.ones(12,bool)
            f["strict_quality_pass"] = np.array([False,True]*6)
            for k in ("guard_applied", "raw_sinr_db", "guard_sinr_db"):
                f[k] = np.zeros(12)
        return p

    def test_reordered_lineage_and_quality_flags(self):
        p = self.cleaned()
        m = ev.metadata(p, "raw", self.labels, self.snr, self.classes)
        self.assertEqual(m["source_row"][0],11)
        self.assertEqual(m["strict_quality_pass"].sum(),6)
        with h5py.File(p,"r+") as f:
            f["class_id"][0] = 0
        with self.assertRaisesRegex(ValueError,"source row"):
            ev.metadata(p,"raw",self.labels,self.snr,self.classes)

    def test_duplicate_source_id_rejected(self):
        p = self.cleaned()
        with h5py.File(p,"r+") as f:
            f["source_row"][0]=0
        with self.assertRaisesRegex(ValueError,"permutation"):
            ev.metadata(p,"guard",self.labels,self.snr,self.classes)

    def test_quality_flag_inconsistency_rejected(self):
        p = self.cleaned()
        with h5py.File(p,"r+") as f:
            f["usable"][0]=False
        with self.assertRaisesRegex(ValueError,"quality flag"):
            ev.metadata(p,"guard",self.labels,self.snr,self.classes)

    def test_input_finiteness_rms_and_no_renormalization(self):
        p = self.cleaned()
        ds = dict(plane="raw",**ev.identity(p))
        x=ev.read_iq(ds,0,12)
        with h5py.File(p) as f:
            np.testing.assert_array_equal(x,f["iq"][:])
        with h5py.File(p,"r+") as f:
            f["iq"][0,0,0]=float("nan")
        ds = dict(plane="raw",**ev.identity(p))
        with self.assertRaisesRegex(ValueError,"nonfinite"):
            ev.read_iq(ds,0,12)
        # Rejected rows must not reach finiteness checks or the model.
        accepted=np.ones(12,bool);accepted[0]=False
        self.assertEqual(ev.read_iq(ds,0,12,accepted).shape,(11,2,1024))

    def test_common_selection_uses_source_ids_not_file_positions(self):
        p=self.cleaned()
        m=ev.metadata(p,"raw",self.labels,self.snr,self.classes)
        source=dict(source_row=np.arange(12),class_id=self.labels,source_snr_db=self.snr)
        guard={k:v[::-1].copy() for k,v in m.items()}
        datasets=[]
        for plane,values in (("source",source),("raw",m),("guard",guard)):
            np.savez(self.root/f"{plane}-metadata.npz",**values)
            datasets.append(dict(plane=plane,path=str(p)))
        ev.select_metadata(self.root,datasets)
        self.assertEqual([d["selected_rows"] for d in datasets],[12,6,6])
        self.assertEqual([d["common_rows"] for d in datasets],[6,6,6])
        with np.load(self.root/"raw-metadata.npz") as raw,np.load(self.root/"guard-metadata.npz") as guard:
            np.testing.assert_array_equal(np.sort(raw["source_row"][raw["common_source_subset"]]),
                                          np.sort(guard["source_row"][guard["common_source_subset"]]))

    def test_confusion_orientation_and_strict_denominator(self):
        y=np.array([1,1,2]);z=np.array([-20,-20,30]);p=np.array([1,2,1])
        cm=ev.confusion(y,z,p)
        self.assertEqual(cm[0,1,1],1)
        self.assertEqual(cm[0,1,2],1)
        self.assertEqual(cm[25,2,1],1)
        self.assertEqual(ev.confusion(y,z,p,np.array([True,False,False])).sum(),1)

    def test_stream_resume_and_identity_rejection(self):
        models=[dict(variant="m",seed=i,checkpoint=dict(sha256=str(i))) for i in range(12)]
        datasets=[]
        for plane in ("source","raw","guard"):
            selected=np.ones(12,bool) if plane=="source" else np.array([True,False]*6)
            np.savez(self.root/f"{plane}-metadata.npz",class_id=self.labels,
                     source_snr_db=self.snr,selected_for_inference=selected,
                     common_source_subset=np.array([True,False]*6))
            datasets.append(dict(plane=plane,sha256=plane,selected_rows=int(selected.sum()),
                                 skipped_rows=int((~selected).sum()),metadata_sha256=ev.digest(self.root/f"{plane}-metadata.npz")))
        ev.atomic(self.root/"probe.json",dict(passed=True,models=[dict(variant="m",seed=i,precision="fp32") for i in range(12)]))
        plan=dict(models=models,datasets=datasets,deadline_seconds=60,batch_size=3,total_predictions=288,
                  probe_sha256=ev.digest(self.root/"probe.json"))
        def read(_ds,lo,hi,selected):
            x=np.zeros((hi-lo,2,1024),np.float32);x[:,0,0]=np.arange(lo,hi);return x[selected]
        def predict(_model,x,_torch,_precision):
            return np.eye(24,dtype=np.float32)[x[:,0,0].astype(int)]
        class Torch:
            class cuda:
                @staticmethod
                def empty_cache(): pass
        with patch.object(ev,"BLOCK",5),patch.object(ev,"load_model",return_value=None),\
             patch.object(ev,"read_iq",side_effect=read),patch.object(ev,"render"),\
             patch.object(ev,"predict",side_effect=predict) as pred:
            ev.run(self.root,plan,Torch)
            self.assertTrue((self.root/"COMPLETE.json").exists())
            summary=json.loads((self.root/"m-seed0/raw-summary.json").read_text())
            self.assertEqual(summary["rows"],6)
            self.assertEqual(summary["common_rows"],6)
            self.assertEqual(summary["skipped_rows"],6)
            self.assertEqual(summary["accuracy"],1)
            with np.load(self.root/"m-seed0/raw/0000000.npz") as f:
                np.testing.assert_array_equal(f["dataset_row"],[0,2,4])
            pred.reset_mock()
            ev.run(self.root,plan,Torch)
            pred.assert_not_called()
            receipt=self.root/"m-seed0/source/0000000.json"
            r=json.loads(receipt.read_text());r["input_sha256"]="wrong";ev.atomic(receipt,r)
            with self.assertRaisesRegex(ValueError,"identity mismatch"):
                ev.run(self.root,plan,Torch)


if __name__ == "__main__":
    unittest.main()
