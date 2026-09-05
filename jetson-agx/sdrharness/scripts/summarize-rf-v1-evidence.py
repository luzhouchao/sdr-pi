#!/usr/bin/env python3
"""Audit RF-v1 corpus groups and summarize evidence coverage, never grant V1b."""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def summarize(root):
    validator = load("corpus_validator", SCRIPTS / "validate-amc-corpus-manifest.py")
    auditor = load("corpus_auditor", SCRIPTS / "audit-amc-split-isolation.py")
    # Only application P201 packages, no offline HDF5/split operations.
    for directory in root.iterdir():
        manifest = validator.read_bounded_json(directory / "manifest.json", 128*1024, "manifest")
        if manifest.get("corpus_kind") != "p201_receive":
            raise ValueError("coverage accepts only P201 application packages")
    result = auditor.audit_p201_corpus(root, SCRIPTS / "validate-amc-corpus-manifest.py", validator.DEFAULT_SCHEMA, True)
    counts = Counter()
    days = {}
    sessions = {}
    sources = {}
    for directory in root.iterdir():
        manifest = validator.read_bounded_json(directory / "manifest.json",128*1024,"manifest")
        if manifest["contract"]["preprocessing"]["id"] != "rf_preprocess_v1":
            continue
        record = validator.read_bounded_json(directory / "records.jsonl",64*1024,"record")
        label = record["label"]
        key = f'{record["split"]}/{label.get("category", "unknown")}/{label.get("numeric_id", "none")}'
        counts[key] += 1
        sources.setdefault(key,set()).add(record["window"]["sha256"])
        days.setdefault(key,set()).add(record["lineage"]["capture_day"])
        sessions.setdefault(key,set()).add(record["lineage"]["capture_session_id"])
    return {"schema_version":1,"schema_id":"rf_v1_evidence_coverage_v1", "group_audit":result,
            "coverage":{k:{"records":v,"unique_iq_captures":len(sources[k]),"distinct_days":len(days[k]),"distinct_sessions":len(sessions[k])} for k,v in sorted(counts.items())},
            "v1b_complete":False,"recognizer_available":False,
            "limitation":"Counts are not effective independent sample sizes or proof of annotation correctness. Human evidence/coverage review is required."}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root",type=Path,required=True)
    args=parser.parse_args()
    try:
        print(json.dumps(summarize(args.corpus_root),sort_keys=True))
    except Exception as error:
        parser.exit(1,f"evidence_audit_failed: {error}\n")


if __name__=="__main__":
    main()
