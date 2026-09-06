#!/usr/bin/env python3
"""Verify an inert RX-only candidate release manifest; never installs or enables capability."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat


def verify(root):
    if not root.is_absolute() or root.resolve()!=root or not root.is_dir():raise ValueError('canonical_release_root')
    manifest=root/'release.json'
    fd=os.open(manifest,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as source:
        meta=os.fstat(source.fileno())
        if not stat.S_ISREG(meta.st_mode) or meta.st_nlink!=1 or meta.st_size>65536:raise ValueError('manifest_file')
        manifest_bytes=source.read(65537)
        if len(manifest_bytes)>65536:raise ValueError('manifest_limit')
    def unique(pairs):
        result={}
        for k,v in pairs:
            if k in result:raise ValueError('duplicate_key')
            result[k]=v
        return result
    data=json.loads(manifest_bytes,object_pairs_hook=unique)
    if set(data)!={'schema_version','release_id','kind','recognizer_available','files'} or type(data['schema_version']) is not int or data['schema_version']!=1 or data['kind']!='rx_only_candidate' or data['recognizer_available'] is not False:raise ValueError('candidate_contract')
    if not isinstance(data['release_id'],str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',data['release_id']):raise ValueError('release_id')
    if not isinstance(data['files'],list) or not 1<=len(data['files'])<=256:raise ValueError('file_count')
    seen=set();total=0
    for item in data['files']:
        if set(item)!={'path','bytes','sha256'}:raise ValueError('file_fields')
        relative=Path(item['path'])
        if relative.is_absolute() or '..' in relative.parts or not relative.parts or str(relative)!=item['path'] or item['path'] in seen or relative==Path('release.json'):raise ValueError('file_path')
        seen.add(item['path'])
        if type(item['bytes']) is not int or not 0<item['bytes']<=512*1024**2 or not re.fullmatch('[0-9a-f]{64}',item['sha256']):raise ValueError('file_identity')
        total+=item['bytes']
        if total>1024**3:raise ValueError('release_budget')
        path=root/relative
        for parent in [path,*path.parents]:
            if parent==root:break
            if parent.is_symlink():raise ValueError('symlink')
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as f:
            before=os.fstat(f.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size!=item['bytes']:raise ValueError('file_metadata')
            digest=hashlib.sha256()
            remaining=item['bytes']
            while remaining:
                chunk=f.read(min(1024*1024,remaining))
                if not chunk:raise ValueError('truncated_file')
                digest.update(chunk);remaining-=len(chunk)
            if f.read(1):raise ValueError('file_grew')
            after=os.fstat(f.fileno())
            if (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise ValueError('changed_during_verification')
            if digest.hexdigest()!=item['sha256']:raise ValueError('hash_mismatch')
    # Only regular manifest-listed artifacts may be released; external assets remain receipts.
    actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() or p.is_symlink()}
    if actual!=seen|{'release.json'}:raise ValueError('unlisted_artifact')
    return {'schema_version':1,'release_id':data['release_id'],'verified_files':len(seen),'bytes':total,'recognizer_available':False,'installed':False,'manifest_sha256':hashlib.sha256(manifest_bytes).hexdigest()}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);a=p.parse_args()
    try:print(json.dumps(verify(a.root),sort_keys=True));return 0
    except (OSError,ValueError,TypeError,KeyError,RecursionError):
        print(json.dumps({'error':'release_verification_failed','installed':False,'recognizer_available':False}));return 2


if __name__=='__main__':raise SystemExit(main())
