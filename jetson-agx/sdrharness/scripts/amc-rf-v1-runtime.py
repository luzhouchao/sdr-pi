"""RF-v1 runtime helpers; no dataset/split loader or calibration execution."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / 'jetson-agx/sdrharness/config/amc'
CANDIDATE_SHA256 = '35ff99719ab845f33dc7ca2d0e7b666e4f40721ca64a6dd615a671ec6c084f40'
# Filled from the reviewed runtime profile, independent of request contents.
PROFILE_SHA256 = '6c1dac991b45e3738e19a6a55a9f3a1b6d3db8510ceef35ee77cdd34e2982dab'


def checked_json(path, expected):
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 65536:
        raise ValueError(f'RF-v1 requires a bounded regular profile: {path}')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f'RF-v1 pinned file changed: {path}')
    return json.loads(data)


def load_contract(profile_path):
    profile = checked_json(profile_path, PROFILE_SHA256)
    candidate = checked_json(CONFIG / 'rml2018a-d8-rf-v1-fp16.candidate.json', CANDIDATE_SHA256)
    base = candidate['base_candidate']
    checked_json(ROOT / base['path'], base['sha256'])
    preprocess = candidate['preprocess']
    checked_json(ROOT / preprocess['path'], preprocess['sha256'])
    return profile, candidate


def load_model(profile_path):
    profile, candidate = load_contract(profile_path)
    path = ROOT / 'jetson-agx/sdrharness/scripts/validate-rf-aligned-checkpoint.py'
    spec = importlib.util.spec_from_file_location('rf_v1_checkpoint_loader', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # These helpers verify only model assets and train/validation provenance
    # documents. Never invoke execute(), split loaders or evaluation.
    manifest = module.load_manifest()
    delivery = module.verify_delivery(manifest)
    model, torch, _ = module.verify_checkpoint_and_model(manifest, delivery)
    return profile, candidate, model, torch


def load_admission():
    path = CONFIG / 'rf-v1-recognizer-admission.candidate.json'
    digest = '3c802706d35852e4e1ee45b3db2285b0790a7deac331b8c948c4aa6fc1147b83'
    return checked_json(path, digest), digest
