#!/usr/bin/env python3
"""Plan/run one full source-SNR group, then two continuous groups after success."""
import argparse
from pathlib import Path
from rml2018a_snr_stream import create,run

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['plan','run'])
    p.add_argument('--root',type=Path,required=True);p.add_argument('--backend',type=Path)
    p.add_argument('--snrs',type=int,nargs='+',default=[30]);p.add_argument('--after',type=Path)
    a=p.parse_args()
    if a.command=='plan':create(a.root,a.backend,a.snrs,a.after)
    else:run(a.root)
