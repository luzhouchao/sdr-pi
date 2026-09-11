import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch

REPO=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('test_b210_transport',REPO/'devices/b210/transport.py')
t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)


class TransportTests(unittest.TestCase):
    def test_agx_copy_and_command_do_not_use_nx(self):
        bg=MagicMock()
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory:
            root=Path(directory);source=root/'source';stage=root/'stage';dest=root/'dest'
            for p in (source,stage,dest):p.mkdir()
            (source/'packet').write_bytes(b'finite test')
            with patch.object(t,'identity',return_value={'host':'agx'}),patch.object(t.device,'environment',return_value=os.environ.copy()):
                tx=t.Transport('agx',bg);tx.put([source/'packet'],stage);tx.get([stage/'packet'],dest)
                self.assertEqual((dest/'packet').read_bytes(),b'finite test')
                self.assertEqual(tx.run("python3 -c 'print(123)'"),'123\n')
                child=tx.spawn("python3 -c 'import sys; print(sys.stdin.read())'")
                out,_=child.communicate(b'EOF test',timeout=5);self.assertEqual(child.returncode,0)
                self.assertIn(b'EOF test',out)
                with self.assertRaisesRegex(ValueError,'target exists'):tx.put([source/'packet'],stage)
            self.assertEqual(bg.mock_calls,[])

    def test_unknown_host_rejected(self):
        with self.assertRaises(ValueError):t.identity('p201')

    def test_dataset_is_shared_and_program_links_resolve(self):
        expected=REPO/'local-assets/amc-eval/datasets/rml2018a'
        for name in ('b210','p201'):
            p=REPO/'devices'/name/'dataset';self.assertTrue(p.is_symlink());self.assertEqual(p.resolve(),expected.resolve())
        self.assertEqual((REPO/'devices/b210/programs/campaign.py').resolve(),REPO/'jetson-agx/sdrharness/scripts/rml2018a-rf-campaign.py')

    def test_symlink_entry_pins_canonical_campaign_filename(self):
        import sys
        sys.path.insert(0,str(REPO/'jetson-agx/sdrharness/scripts'))
        spec=importlib.util.spec_from_file_location('symlink_campaign',REPO/'devices/b210/programs/campaign.py')
        runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
        software=runner.campaign_software()
        self.assertIn('rml2018a-rf-campaign.py',software);self.assertNotIn('campaign.py',software)
        self.assertEqual(Path(importlib.util.find_spec('gpu_lease').origin),REPO/'jetson-agx/sdrharness/scripts/gpu_lease.py')


if __name__=='__main__':unittest.main()
