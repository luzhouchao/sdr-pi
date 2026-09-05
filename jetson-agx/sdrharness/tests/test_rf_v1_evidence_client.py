"""Bounded receive-free corpus import client checks."""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

SPEC=importlib.util.spec_from_file_location("rf_client",Path(__file__).resolve().parents[1]/"scripts/import-rf-v1-corpus.py")
client=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(client)

class ClientTests(unittest.TestCase):
    def test_loopback_only_endpoint_and_safe_parent(self):
        for url in ["https://127.0.0.1:8787","http://192.168.1.10:8787","http://localhost:8787","http://user@127.0.0.1:8787","http://127.0.0.1:8787/path","http://127.0.0.1:8787?secret=x"]:
            with self.assertRaises(ValueError):client.endpoint(url)
        self.assertEqual(client.endpoint("http://127.0.0.1:8787/"),"http://127.0.0.1:8787")
        with self.assertRaises(ValueError):client.submit("http://127.0.0.1:1","../bad",Path("unused"))

    def test_malformed_duplicate_nonfinite_and_oversized_requests_fail_before_network(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"request.json"
            for data in [b'{"schema_version":1,"schema_version":1}',b'{"schema_version":NaN}',b'{',b' '*(client.MAX_BYTES+1)]:
                p.write_bytes(data)
                with self.assertRaises(ValueError):client.submit("http://127.0.0.1:1","parent",p)

    def test_success_and_redirect_do_not_expose_evidence_or_follow_remote_url(self):
        class Handler(BaseHTTPRequestHandler):
            redirect=False
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                if self.redirect:
                    self.send_response(302);self.send_header('Location','http://192.168.1.10:1/private');self.end_headers()
                else:
                    payload=json.dumps({'summary':{'result_id':'derived'},'record':{'evidence':'private'}}).encode()
                    self.send_response(201);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            def log_message(self,*args):pass
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)/'request.json';p.write_text('{"schema_version":1}')
                base=f'http://127.0.0.1:{server.server_port}'
                self.assertEqual(client.submit(base,'parent',p),{'result_id':'derived'})
                Handler.redirect=True
                with self.assertRaises(ValueError):client.submit(base,'parent',p)
        finally:
            server.shutdown();thread.join();server.server_close()

if __name__=='__main__':unittest.main()
