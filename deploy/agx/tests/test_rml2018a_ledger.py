"""Ledger invariants: durable reservations, budget gates and rebuildable views."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
S=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(S))
import rml2018a_campaign_ledger as l
c=l.c


def plan():return dict(maximum_new_batches=2,maximum_new_tx_seconds=16,failure_pool_bytes=l.e.storage.FAILURE_POOL,retention_limit_bytes=l.TOTAL_CAP)
def state():return dict(new_batches_reserved=0,new_tx_seconds_reserved=0,failure_bytes=0,outstanding_failure_reserve_bytes=0,retained_bytes=0,outstanding_reserve_bytes=0,stop_requested=False)


class LedgerTests(unittest.TestCase):
    def test_total_budgets_are_independent_and_fail_closed(self):
        p=plan();s=state();l.gate(p,s,2)
        for changes,reason in [({'new_batches_reserved':2,'new_tx_seconds_reserved':16},'TX/batch'),
            ({'failure_bytes':p['failure_pool_bytes']},'failure pool'),
            ({'retained_bytes':p['retention_limit_bytes']},'storage'),({'stop_requested':True},'STOP')]:
            with self.assertRaisesRegex(ValueError,reason):l.gate(p,{**s,**changes},1)

    def test_pending_reservations_use_worst_case_failure_budget(self):
        b=l.e.storage.budget([0]);p=plan();s=state()
        s['outstanding_failure_reserve_bytes']=p['failure_pool_bytes']-l.failure_budget(b)+1
        with self.assertRaisesRegex(ValueError,'failure pool'):l.gate(p,s,1)

    def test_dataset_cached_identity_change_rejected(self):
        v=dict(ledger_root='/var/tmp/sdrharness-dev/b210-rml2018a-ledger-test',ledger_plan_sha256='a',identity={'sha256':'abc','inode':1})
        with patch.object(l,'cached_source',return_value=v):self.assertEqual(l.verify_cached(v),'abc')
        with patch.object(l,'cached_source',return_value={**v,'identity':{'sha256':'abc','inode':2}}):
            with self.assertRaises(ValueError):l.verify_cached(v)

    def test_state_rebuild_preserves_registration_after_interruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'entries').mkdir();c.save(root/'ledger-plan.json',plan())
            child=root/'child';entry=dict(kind='reserved',child_root=str(child),batch_indices=[170],ledger_plan_sha256=c.file_hash(root/'ledger-plan.json'))
            c.save(l.entry_path(root,child),entry)
            (root/'state.json').write_text('corrupted');(root/'state.json.tmp').write_text('{partial')
            with patch.object(l,'load',return_value=plan()),patch.object(l,'private_root'):
                rebuilt=l.refresh(root)
            self.assertEqual(rebuilt['registered_source_rows'],24);self.assertEqual(rebuilt['completed_source_rows'],0)
            self.assertEqual(rebuilt['new_tx_seconds_reserved'],8);self.assertEqual(rebuilt['outstanding_failure_reserve_bytes'],l.failure_budget(l.e.storage.budget([170])))
            self.assertEqual(len(list((root/'recovery').iterdir())),1)
            self.assertEqual(sum(v['registered_rows'] for v in rebuilt['by_class_source_snr'].values()),24)

    def test_reservation_durable_before_child_creation_and_duplicates_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'entries').mkdir();c.save(root/'ledger-plan.json',plan());child=root/'child'
            with patch.object(l,'load',return_value=plan()),patch.object(l,'private_root'),patch.object(l,'cached_source',return_value={}),patch.object(l.m,'create_plan',side_effect=RuntimeError('interrupted')):
                with self.assertRaisesRegex(RuntimeError,'interrupted'):l.reserve(root,child,[170])
                self.assertTrue(l.entry_path(root,child).exists())
                with self.assertRaisesRegex(ValueError,'duplicate'):l.reserve(root,root/'other',[170])
                s=l.refresh(root);self.assertEqual(s['new_batches_reserved'],1)

    def test_duplicate_registrations_are_not_double_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'entries').mkdir();c.save(root/'ledger-plan.json',plan())
            for name in ('one','two'):
                child=root/name;c.save(l.entry_path(root,child),dict(kind='reserved',child_root=str(child),batch_indices=[170],ledger_plan_sha256=c.file_hash(root/'ledger-plan.json')))
            with patch.object(l,'load',return_value=plan()),patch.object(l,'private_root'):
                with self.assertRaisesRegex(ValueError,'duplicate'):l.refresh(root)

    def test_cached_plan_does_not_hash_the_dataset_again(self):
        # The cache verifier never performs a full source read; it checks its sealed ledger.
        value=dict(ledger_root='/var/tmp/sdrharness-dev/b210-rml2018a-test',ledger_plan_sha256='pin',identity={'sha256':l.DATA_SHA})
        with patch.object(l,'cached_source',return_value=value),patch.object(c,'file_hash') as digest:
            self.assertEqual(l.verify_cached(value),l.DATA_SHA);digest.assert_not_called()

    def test_root_escape_rejected(self):
        for root in (Path('/tmp/b210-rml2018a-test'),Path('/var/tmp/sdrharness-dev/b210-rml2018a-a/b')):
            with self.assertRaises(ValueError):l.private_root(root)

if __name__=='__main__':unittest.main()
