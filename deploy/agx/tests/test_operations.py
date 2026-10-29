"""O1a health transitions and inert release verification, no model/hardware."""
import importlib.util
import json
import os
import subprocess
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
def module(name):
    spec=importlib.util.spec_from_file_location(name,SCRIPTS/(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
health=module('operations-health');release=module('verify-release')


class Operations(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='o1a-ops-');self.root=Path(self.tmp.name)
        self.http_status=200
        self.payload={'schema_version':1,'service':'web','ready':True,'recognizer_available':False}
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                body=json.dumps(owner.payload).encode();self.send_response(owner.http_status);self.send_header('Location','http://127.0.0.1:9/health');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.config=health.validate_config({'schema_version':1,'probes':[{'name':'web','kind':'http','endpoint':f'http://127.0.0.1:{self.server.server_port}/api/health'}],'disk_path':str(self.root),'minimum_free_bytes':0})
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def test_alert_deduplication_and_recovery(self):
        path=self.root/'state.json'
        one=health.snapshot(self.config,path);self.assertTrue(all(x=='healthy' for x in one['statuses'].values()))
        self.assertEqual(health.snapshot(self.config,path)['events'],[])
        self.payload['ready']=False
        self.assertEqual(health.snapshot(self.config,path)['events'],[{'service':'web','status':'unavailable','event':'alert'}])
        self.assertEqual(health.snapshot(self.config,path)['events'],[])
        self.payload['ready']=True
        self.assertEqual(health.snapshot(self.config,path)['events'],[{'service':'web','status':'healthy','event':'recovered'}])
        self.assertEqual(path.stat().st_mode&0o777,0o600)

    def test_capability_forgery_and_disk_exhaustion(self):
        self.payload['recognizer_available']=True
        self.config['minimum_free_bytes']=2**63
        result=health.snapshot(self.config,self.root/'state')
        self.assertEqual(result['statuses'],{'web':'unavailable','disk':'low_space'})
        self.assertNotIn('endpoint',json.dumps(result));self.assertFalse(result['recognizer_available'])

    def test_remote_redirect_inputs_duplicate_and_bad_key_refused(self):
        for endpoint in ('http://example.com/health','http://127.0.0.1/execute','http://user:secret@127.0.0.1/health','http://127.0.0.1/health?execute=1'):
            bad=json.loads(json.dumps(self.config));bad['probes'][0]['endpoint']=endpoint
            with self.assertRaises(ValueError):health.validate_config(bad)
        self.http_status=302
        self.assertEqual(health.probe(self.config['probes'][0])['status'],'unavailable')
        self.http_status=200
        self.server.RequestHandlerClass.protocol_version='HTTP/9.9'
        self.assertEqual(health.probe(self.config['probes'][0])['status'],'unavailable')
        with self.assertRaises(ValueError):health.decode(b'{"ready":true,"ready":false}')
        key=self.root/'key';key.write_text('private-value');key.chmod(0o600)
        link=self.root/'key-link';link.symlink_to(key)
        with self.assertRaises(OSError):health.private_read(link)

    def test_failed_state_replace_preserves_existing_staging(self):
        path=self.root/'state';existing=Path(str(path)+f'.tmp-{os.getpid()}');existing.write_text('user-sentinel')
        with self.assertRaises(FileExistsError):health.snapshot(self.config,path)
        self.assertEqual(existing.read_text(),'user-sentinel');self.assertFalse(path.exists())

    def test_corrupt_health_state_and_boolean_schema_fail_closed(self):
        state=self.root/'state';state.write_text(json.dumps({'schema_version':1,'statuses':{'secret-injected-name':'healthy'}}));state.chmod(0o600)
        with self.assertRaises(ValueError):health.snapshot(self.config,state)
        self.payload['schema_version']=True
        self.assertEqual(health.probe(self.config['probes'][0])['status'],'unavailable')
        root,data=self.candidate('bool-version');data['schema_version']=True
        (root/'release.json').write_text(json.dumps(data))
        with self.assertRaises(ValueError):release.verify(root)

    def test_deep_json_cli_failure_is_bounded_and_redacted(self):
        bad=self.root/'deep-config';bad.write_text('['*2000+']'*2000);bad.chmod(0o600)
        result=subprocess.run(['python3',str(SCRIPTS/'operations-health.py'),'--config',str(bad),'--state',str(self.root/'deep-state')],capture_output=True,text=True,timeout=3)
        self.assertEqual(result.returncode,3);self.assertEqual(json.loads(result.stdout)['error'],'health_monitor_failed');self.assertFalse(result.stderr)
        directory=self.root/'deep-release';directory.mkdir();(directory/'release.json').write_text(bad.read_text())
        result=subprocess.run(['python3',str(SCRIPTS/'verify-release.py'),'--root',str(directory)],capture_output=True,text=True,timeout=3)
        self.assertEqual(result.returncode,2);self.assertEqual(json.loads(result.stdout)['error'],'release_verification_failed');self.assertFalse(result.stderr)

    def test_fifo_inputs_are_refused_without_blocking(self):
        fifo=self.root/'fifo';os.mkfifo(fifo,0o600)
        start=time.monotonic()
        with self.assertRaises(ValueError):health.private_read(fifo)
        directory=self.root/'fifo-release';directory.mkdir();os.mkfifo(directory/'release.json',0o600)
        with self.assertRaises(ValueError):release.verify(directory)
        self.assertLess(time.monotonic()-start,1)

    def test_http_slow_header_has_total_deadline(self):
        class Slow(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                try:
                    for _ in range(80):self.wfile.write(b'x');self.wfile.flush();time.sleep(.05)
                except (BrokenPipeError,ConnectionResetError):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Slow);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            p={'name':'web','kind':'http','endpoint':f'http://127.0.0.1:{server.server_port}/api/health'}
            start=time.monotonic();self.assertEqual(health.probe(p)['status'],'unavailable');self.assertLess(time.monotonic()-start,3)
        finally:server.shutdown();server.server_close();thread.join()

    def candidate(self,name):
        root=self.root/name;root.mkdir();(root/'app').write_bytes(b'candidate-'+name.encode())
        data={'schema_version':1,'release_id':name,'kind':'rx_only_candidate','recognizer_available':False,'files':[{'path':'app','bytes':(root/'app').stat().st_size,'sha256':hashlib.sha256((root/'app').read_bytes()).hexdigest()}]}
        (root/'release.json').write_text(json.dumps(data));return root,data

    def test_private_upgrade_failure_and_rollback_preserve_user_results(self):
        a,_=self.candidate('a');b,_=self.candidate('b')
        current=self.root/'current';current.symlink_to(a);user=self.root/'user-results.db';user.write_bytes(b'never-rollback-user-data')
        (b/'app').write_bytes(b'tampered')
        with self.assertRaises(ValueError):release.verify(b)
        self.assertEqual(current.resolve(),a)
        (b/'app').write_bytes(b'candidate-b');release.verify(b)
        next_link=self.root/'next';next_link.symlink_to(b);os.replace(next_link,current)
        self.assertEqual(current.resolve(),b)
        release.verify(a);next_link.symlink_to(a);os.replace(next_link,current)
        self.assertEqual(current.resolve(),a);self.assertEqual(user.read_bytes(),b'never-rollback-user-data')

    def test_release_rejects_capability_links_and_unlisted_files(self):
        root,data=self.candidate('candidate')
        data['recognizer_available']=True;(root/'release.json').write_text(json.dumps(data))
        with self.assertRaises(ValueError):release.verify(root)
        data['recognizer_available']=False;(root/'release.json').write_text(json.dumps(data))
        (root/'extra').write_text('not listed')
        with self.assertRaises(ValueError):release.verify(root)
        (root/'extra').unlink();(root/'app').unlink();(root/'app').symlink_to(self.root/'nonexistent')
        with self.assertRaises(ValueError):release.verify(root)


if __name__=='__main__':unittest.main()
