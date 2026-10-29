#!/usr/bin/env python3
"""Finite SNR streaming and26-group acquisition ledger; no model invocation."""
import argparse
import json
from pathlib import Path
from rml2018a_snr_stream import create,run,recover,full_plan,full_run,full_status

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['plan','run','recover','full-plan','full-run','status'])
    p.add_argument('--root',type=Path,required=True);p.add_argument('--backend',type=Path)
    p.add_argument('--snrs',type=int,nargs='+',default=[30]);p.add_argument('--after',type=Path)
    p.add_argument('--import-pair',type=Path);p.add_argument('--retry',action='store_true')
    p.add_argument('--stop-after',type=int,choices=range(1,13))
    a=p.parse_args()
    if a.command=='plan':create(a.root,a.backend,a.snrs,a.after)
    elif a.command=='run':run(a.root)
    elif a.command=='recover':recover(a.root)
    elif a.command=='full-plan':full_plan(a.root,a.backend,a.after,a.import_pair)
    elif a.command=='full-run':print(json.dumps(full_run(a.root,a.retry,a.stop_after)))
    else:print(json.dumps(full_status(a.root)))
