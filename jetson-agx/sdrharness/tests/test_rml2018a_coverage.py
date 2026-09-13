"""All-row partition and explicit replay authority, including mixed Y/Z batches."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import rml2018a_campaign_coverage as v
import rml2018a_campaign_ledger as l
c=v.c


class CoverageTests(unittest.TestCase):
    def test_full_domain_partition_and_failed_rows_not_lost(self):
        policy=v.manifest([],set(range(4080,4104))|{106495,106496})
        states=[dict(kind='imported',state='completed',batch_indices=[170]),
            dict(kind='reserved',state='reserved_or_interrupted',batch_indices=[4437]),
            dict(kind='reserved',state='completed',batch_indices=[0])]
        result=v.partition(policy,states);seen=set()
        for record in result['dispositions'].values():
            members=v.expand(record['batch_ranges'],v.BATCHES)
            self.assertFalse(seen&members);seen.update(members)
            self.assertEqual(record['source_rows'],len(members)*24)
        self.assertEqual(seen,set(range(v.BATCHES)))
        self.assertEqual(result['dispositions']['registered_incomplete']['source_rows'],24)
        self.assertFalse(result['whole_dataset_complete'])

    def test_every_row_including_class_and_z_boundaries_once(self):
        for batch in range(v.BATCHES):
            rows=c.batch_rows(v.TOTAL,batch)
            self.assertEqual(rows,list(range(batch*24,(batch+1)*24)))
        self.assertEqual([(x//106496,2*((x%106496)//4096)-20) for x in (4095,4096,106495,106496)],[(0,-20),(0,-18),(0,30),(1,-20)])

    def test_overlap_and_invalid_ranges_fail(self):
        for intervals in ([[0,2],[1,3]],[[0,1],[1,2]],[[-1,1]],[[0,v.BATCHES+1]]):
            with self.assertRaises(ValueError):v.expand(intervals,v.BATCHES)
        row=dict(kind='reserved',state='completed',batch_indices=[2])
        with self.assertRaisesRegex(ValueError,'duplicate'):v.partition(v.manifest([],set()),[row,row])

    def test_history_includes_unfinished_planned_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'b210-rml2018a-old';old.mkdir()
            c.save(old/'run-plan.json',dict(event_sources={'170':{'source':{'rows':[4080,4081]}}}))
            parents,rows=v.history(root)
            self.assertEqual(rows,{4080,4081});self.assertEqual(len(parents),1)

    def test_policy_and_historical_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'new';root.mkdir();old=base/'b210-rml2018a-old'/'batch-0000001';old.mkdir(parents=True)
            c.save(old/'source.json',dict(rows=[24]))
            receipt=v.create(root);self.assertEqual(v.verify(root,receipt)['historical_unique_rows'],1)
            policy=v.document(root/'coverage-policy.json');policy['automatic_execution']=True;c.save(root/'coverage-policy.json',policy)
            with self.assertRaisesRegex(ValueError,'policy pin'):v.verify(root,receipt)
            receipt['sha256']=c.file_hash(root/'coverage-policy.json')
            with self.assertRaisesRegex(ValueError,'policy contract'):v.verify(root,receipt)
            receipt=v.create(root);c.save(old/'source.json',dict(rows=[25]))
            with self.assertRaisesRegex(ValueError,'lineage pin'):v.verify(root,receipt)

    def test_explicit_replay_requires_bound_reservation_and_frozen_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);owner=base/'owner';owner.mkdir();(owner/'entries').mkdir();child=base/'child'
            old=base/'b210-rml2018a-old'/'batch-0000001';old.mkdir(parents=True);c.save(old/'source.json',dict(rows=[24]))
            receipt=v.create(owner);plan=dict(coverage=receipt);c.save(owner/'ledger-plan.json',plan)
            entry=dict(kind='reserved',child_root=str(child),ledger_plan_sha256=c.file_hash(owner/'ledger-plan.json'),batch_indices=[1])
            c.save(l.entry_path(owner,child),entry)
            p=dict(source_verification={'ledger_root':str(owner)},coverage=receipt,tx_level_profile='event-chunk',execution_limits={'allowed_batch_indices':[1]},event_sources={'1':{'source':{'rows':[24]}}})
            parents=v.history(base)[0]
            with patch.object(l,'verify_cached'),patch.object(l,'load',return_value=plan):
                v.authorize(child,p,parents,{24})
                with self.assertRaises(ValueError):v.authorize(base/'unregistered',p,parents,{24})
                new=base/'b210-rml2018a-new'/'batch-0000001';new.mkdir(parents=True);c.save(new/'source.json',dict(rows=[24]))
                with self.assertRaisesRegex(ValueError,'after policy freeze'):v.authorize(child,p,v.history(base)[0],{24})


if __name__=='__main__':unittest.main()
