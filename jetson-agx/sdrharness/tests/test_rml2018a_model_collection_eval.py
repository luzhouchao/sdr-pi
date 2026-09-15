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

    def test_original_validation_membership_with_reordered_rx(self):
        p=self.cleaned()
        m=ev.metadata(p,"raw",self.labels,self.snr,self.classes)
        source=dict(source_row=np.arange(12),class_id=self.labels,source_snr_db=self.snr)
        guard={k:v[::-1].copy() for k,v in m.items()}
        datasets=[]
        for plane,values in (("source",source),("raw",m),("guard",guard)):
            np.savez(self.root/f"{plane}-metadata.npz",**values)
            datasets.append(dict(plane=plane,path=str(p)))
        val=np.array([0,1,4,7],np.int64)
        ev.select_metadata(self.root,datasets,val)
        self.assertEqual([d['selected_rows'] for d in datasets],[4,2,2])
        self.assertEqual([d['skipped_rows'] for d in datasets],[0,2,2])
        for ds in datasets:
            with np.load(self.root/f"{ds['plane']}-metadata.npz") as f:
                ids=f['source_row'][f['selected_for_inference']]
                self.assertTrue(np.isin(ids,val).all())
                np.testing.assert_array_equal(val[f['validation_rank'][f['selected_for_inference']]],ids)
                self.assertEqual(f['common_source_subset'].sum(),2)
        # No train/test row may acquire a validation rank or a prediction mask.
        with np.load(self.root/'source-metadata.npz') as f:
            self.assertTrue((f['validation_rank'][~f['validation_member']]==-1).all())

    def test_validation_split_rejects_overlap_and_wrong_seed(self):
        p=self.root/'split.npz'
        def write(seed=42,val=(8,9)):
            np.savez(p,train=np.arange(8,dtype=np.int64),val=np.array(val,np.int64),
                     test=np.array([10,11],np.int64),num_samples=[12],seed=[seed],
                     train_ratio=[.7],val_ratio=[.15],test_ratio=[.15])
        write()
        val,record=ev.load_validation_split(p,ev.digest(p))
        np.testing.assert_array_equal(val,[8,9])
        write(val=(7,9))
        with self.assertRaisesRegex(ValueError,'overlap'):
            ev.load_validation_split(p,ev.digest(p))
        write(seed=43)
        with self.assertRaisesRegex(ValueError,'seed'):
            ev.load_validation_split(p,ev.digest(p))

    def test_include_quality_failures_keeps_split_and_strict_comparison(self):
        p=self.cleaned()
        m=ev.metadata(p,"raw",self.labels,self.snr,self.classes)
        source=dict(source_row=np.arange(12),class_id=self.labels,source_snr_db=self.snr)
        datasets=[]
        for plane,values in (("source",source),("raw",m)):
            np.savez(self.root/f"{plane}-metadata.npz",**values)
            datasets.append(dict(plane=plane,path=str(p)))
        val=np.array([0,1,4,7],np.int64)
        ev.select_metadata(self.root,datasets,val,include_quality_failed=True)
        self.assertEqual([d['selected_rows'] for d in datasets],[4,4])
        self.assertEqual([d['skipped_rows'] for d in datasets],[0,0])
        self.assertEqual([d['common_rows'] for d in datasets],[2,2])
        self.assertEqual(datasets[1]['quality_failed_included_rows'],2)
        self.assertTrue(all(v==0 for v in datasets[1]['skip_reasons_overlapping'].values()))
        with np.load(self.root/'raw-metadata.npz') as f:
            np.testing.assert_array_equal(np.sort(f['source_row'][f['selected_for_inference']]),val)
            np.testing.assert_array_equal(f['quality_flags'],m['quality_flags'])
            self.assertEqual(int((f['selected_for_inference']&~f['strict_quality_pass']).sum()),2)
            self.assertFalse((f['selected_for_inference']&~f['validation_member']).any())

    def test_fresh_prepare_needs_no_old_metadata_or_predictions(self):
        source=self.root/'source.h5'
        with h5py.File(source,'w') as f:
            f['X']=np.zeros((12,1024,2),np.float32)
            f['Y']=np.eye(24,dtype=np.int64)[:12]
            f['Z']=self.snr[:,None]
        rx=self.cleaned()
        split=self.root/'original-split.npz'
        np.savez(split,train=np.arange(8,dtype=np.int64),val=np.array([8,9],np.int64),
                 test=np.array([10,11],np.int64),num_samples=[12],seed=[42],
                 train_ratio=[.7],val_ratio=[.15],test_ratio=[.15])
        collection=self.root/'collection';collection.mkdir()
        models=[dict(variant=f'm{i}',seed=42) for i in range(8)]
        ev.atomic(collection/'manifest.json',dict(models=models,transferred_files=[]))
        parent=self.root/'audit-parent';parent.mkdir();(parent/'STOP').touch()
        ev.atomic(parent/'probe.json',dict(passed=True,models=[dict(m,passed=True,precision='fp32',full_batch_seconds=1) for m in models]))
        datasets=[dict(plane=k,**ev.identity(source if k=='source' else rx)) for k in ('source','raw','guard')]
        ev.atomic(parent/'plan.json',dict(datasets=datasets,collection_manifest=ev.identity(collection/'manifest.json'),
                   probe_sha256=ev.digest(parent/'probe.json'),classes=self.classes,batch_size=1024))
        target=self.root/'fresh-run'
        with patch.object(ev,'COLLECTION',collection),patch.object(ev,'SEED42_SPLIT_SHA',ev.digest(split)):
            ev.prepare_validation(target,parent,split,fresh=True)
        plan=json.loads((target/'plan.json').read_text())
        self.assertEqual(plan['reused_predictions'],0)
        self.assertTrue(plan['fresh_predictions'])
        self.assertEqual(plan['model_dataset_pairs'],24)
        self.assertFalse(list(target.glob('*-seed*')))
        with np.load(target/'source-metadata.npz') as f:
            np.testing.assert_array_equal(f['source_row'][f['selected_for_inference']],[8,9])
        subset=self.root/'subset-all-quality'
        with patch.object(ev,'COLLECTION',collection),patch.object(ev,'SEED42_SPLIT_SHA',ev.digest(split)):
            ev.prepare_validation(subset,parent,split,fresh=True,variants=['m0'],
                                  planes=['source','raw'],include_quality_failed=True)
        selected=json.loads((subset/'plan.json').read_text())
        self.assertEqual(selected['model_dataset_pairs'],2)
        self.assertEqual(selected['total_predictions'],4)
        self.assertEqual([m['variant'] for m in selected['models']],['m0'])
        self.assertEqual([d['plane'] for d in selected['datasets']],['source','raw'])
        self.assertEqual(selected['datasets'][1]['quality_failed_included_rows'],1)
        self.assertTrue(selected['include_quality_failed'])
        self.assertEqual(len(json.loads((subset/'probe.json').read_text())['models']),1)
        self.assertFalse((subset/'guard-metadata.npz').exists())
        with patch.object(ev,'COLLECTION',collection),patch.object(ev,'SEED42_SPLIT_SHA',ev.digest(split)):
            with self.assertRaisesRegex(ValueError,'variant selection'):
                ev.prepare_validation(self.root/'bad-subset',parent,split,variants=['missing'])

    def test_stream_resume_and_identity_rejection(self):
        models=[dict(variant=f"m{i}",seed=42,checkpoint=dict(sha256=str(i))) for i in range(8)]
        datasets=[]
        for plane in ("source","raw","guard"):
            selected=np.ones(12,bool) if plane=="source" else np.array([True,False]*6)
            np.savez(self.root/f"{plane}-metadata.npz",class_id=self.labels,
                     source_snr_db=self.snr,selected_for_inference=selected,
                     common_source_subset=np.array([True,False]*6))
            datasets.append(dict(plane=plane,sha256=plane,selected_rows=int(selected.sum()),
                                 skipped_rows=int((~selected).sum()),metadata_sha256=ev.digest(self.root/f"{plane}-metadata.npz")))
        ev.atomic(self.root/"probe.json",dict(passed=True,models=[dict(variant=f"m{i}",seed=42,precision="fp32") for i in range(8)]))
        plan=dict(models=models,datasets=datasets,deadline_seconds=60,batch_size=3,total_predictions=192,
                  probe_sha256=ev.digest(self.root/"probe.json"),sample_scope="test fixture")
        ev.atomic(self.root/'plan.json',plan)
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
            self.assertEqual(json.loads((self.root/'COMPLETE.json').read_text())['model_dataset_pairs'],24)
            summary=json.loads((self.root/"m0-seed42/raw-summary.json").read_text())
            self.assertEqual(summary["rows"],6)
            self.assertEqual(summary["common_rows"],6)
            self.assertEqual(summary["skipped_rows"],6)
            self.assertEqual(summary["accuracy"],1)
            with np.load(self.root/"m0-seed42/raw/0000000.npz") as f:
                np.testing.assert_array_equal(f["dataset_row"],[0,2,4])
            pred.reset_mock()
            ev.run(self.root,plan,Torch)
            pred.assert_not_called()
            receipt=self.root/"m0-seed42/source/0000000.json"
            r=json.loads(receipt.read_text());r["input_sha256"]="wrong";ev.atomic(receipt,r)
            with self.assertRaisesRegex(ValueError,"identity mismatch"):
                ev.run(self.root,plan,Torch)


if __name__ == "__main__":
    unittest.main()
