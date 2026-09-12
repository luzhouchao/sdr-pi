import importlib.util
import os
import shlex
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch

REPO=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('test_b210_transport',REPO/'devices/b210/transport.py')
t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)


class TransportTests(unittest.TestCase):
    def runner(self):
        sys.path.insert(0,str(REPO/'jetson-agx/sdrharness/scripts'))
        spec=importlib.util.spec_from_file_location('cleanup_campaign',REPO/'devices/b210/programs/campaign.py')
        runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner);return runner

    def test_stop_allows_real_helper_to_finish_fifo_cleanup(self):
        runner=self.runner()
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory,\
             patch.object(t,'identity',return_value={'host':'agx'}),\
             patch.object(t.device,'environment',return_value=os.environ.copy()):
            root=Path(directory);tx=t.Transport('agx',None)
            code="""import os,signal,sys,time
from pathlib import Path
fifo=Path('packet.fifo');os.mkfifo(fifo)
def stop(sig,frame):
    time.sleep(.15);fifo.unlink();sys.exit(0)
signal.signal(signal.SIGINT,stop)
print('ready',flush=True)
while True:time.sleep(1)
"""
            child=tx.spawn('cd '+shlex.quote(directory)+' && exec '+shlex.quote(sys.executable)+' -B -c '+shlex.quote(code))
            try:
                self.assertEqual(child.stdout.readline(),b'ready\n')
                runner.stop_tx(tx,child,child.pid,root)
                self.assertEqual(child.returncode,0);self.assertFalse((root/'packet.fifo').exists())
            finally:
                if child.poll() is None:child.kill();child.communicate(timeout=5)

    def test_stale_fifo_cleanup_refuses_an_open_fifo_then_cleans_idle(self):
        runner=self.runner()
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory,\
             patch.object(t,'identity',return_value={'host':'agx'}),\
             patch.object(t.device,'environment',return_value=os.environ.copy()):
            root=Path(directory);fifo=root/'packet.fifo';os.mkfifo(fifo)
            (root/'tx-plan.json').write_text('{}');tx=t.Transport('agx',None)
            fd=os.open(fifo,os.O_RDWR|os.O_NONBLOCK)
            try:
                with self.assertRaises(ValueError):runner.remote_cleanup(tx,root)
                self.assertTrue(fifo.exists());self.assertTrue((root/'tx-plan.json').exists())
            finally:os.close(fd)
            removed=runner.remote_cleanup(tx,root)
            self.assertEqual({r['name'] for r in removed},{'packet.fifo','tx-plan.json'})
            self.assertFalse(root.exists())

    def test_cleanup_still_rejects_foreign_fifo_and_symlink(self):
        runner=self.runner()
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory,\
             patch.object(t,'identity',return_value={'host':'agx'}),\
             patch.object(t.device,'environment',return_value=os.environ.copy()):
            root=Path(directory);foreign=root/'foreign.fifo';os.mkfifo(foreign);tx=t.Transport('agx',None)
            with self.assertRaises(ValueError):runner.remote_cleanup(tx,root)
            foreign.unlink();(root/'packet.fifo').symlink_to('/dev/null')
            with self.assertRaises(ValueError):runner.remote_cleanup(tx,root)

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
