#!/usr/bin/env python3
"""S6a terminal client for the existing local application recognition archive.

Imports metadata only. Never reads IQ/model/dataset files, invokes inference,
or changes scientific admission. Delete touches one archive row only.
"""
import argparse
import ipaddress
import json
from pathlib import Path
import urllib.parse
import urllib.request

MAX_IMPORT=66560
MAX_RESPONSE=512*1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError('archive redirects forbidden')


def request(base,route,method='GET',body=None):
    url=urllib.parse.urlsplit(base)
    if url.scheme!='http' or url.username or url.password or url.query or url.fragment or url.path not in ('','/') or not ipaddress.ip_address(url.hostname or '').is_loopback or url.port is None:
        raise ValueError('endpoint must be HTTP loopback IP with explicit port')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    req=urllib.request.Request(base.rstrip('/')+'/api/recognition-results'+route,data=body,headers={'Content-Type':'application/json'},method=method)
    with opener.open(req,timeout=10) as response:
        data=response.read(MAX_RESPONSE+1)
        if len(data)>MAX_RESPONSE:raise ValueError('archive response exceeds bound')
        return json.loads(data)


def render(record):
    o=record['observation']
    print(f"#{record['id']} {record['origin']} · 非生产结果 · {o['status']} · {o['candidate_id']}")
    print(f"  会话 {record['session_id']} / request {o['request_id']} / generation {o['session_generation']}")
    print(f"  原因 {o['reason'] or '—'}；校准 {o['calibration_status']}；IQ 未保留")
    predicted=o['class'] or record['experimental_prediction']
    if predicted:print(f"  演示/实验类别 ID {predicted['numeric_id']}；名称 {predicted['name_status']}（不是独立标签）")
    if o['calibrated_confidence'] is not None:print(f"  合成演示置信度 {o['calibrated_confidence']}")
    if record['uncalibrated_probability'] is not None:print(f"  未校准实验概率 {record['uncalibrated_probability']}")
    for name in ('identity','source','quality','timing','decision_references'):
        if o[name] is not None:print(f"  {name}: {json.dumps(o[name],ensure_ascii=False)}")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--endpoint',default='http://127.0.0.1:8787')
    p.add_argument('--json',action='store_true')
    sub=p.add_subparsers(dest='action',required=True)
    listing=sub.add_parser('list');listing.add_argument('--before',type=int)
    for name in ('show','delete'):
        parser=sub.add_parser(name);parser.add_argument('id',type=int)
    imp=sub.add_parser('import');imp.add_argument('file',type=Path)
    args=p.parse_args()
    try:
        route='';method='GET';body=None
        if args.action in ('show','delete'):
            if args.id<=0:raise ValueError('positive ID required')
            route=f'/{args.id}'
            if args.action=='delete':method='DELETE'
        elif args.action=='list' and args.before is not None:
            if args.before<=0:raise ValueError('positive cursor required')
            route=f'?before={args.before}'
        elif args.action=='import':
            with args.file.open('rb') as f:body=f.read(MAX_IMPORT+1)
            if not body or len(body)>MAX_IMPORT:raise ValueError('import exceeds bound')
            method='POST'
        value=request(args.endpoint,route,method,body)
        if args.json or args.action=='delete':print(json.dumps(value,ensure_ascii=False))
        else:
            for record in value if isinstance(value,list) else [value]:render(record)
    except (OSError,ValueError,KeyError) as error:p.exit(1,f'archive_failed: {error}\n')


if __name__=='__main__':main()
