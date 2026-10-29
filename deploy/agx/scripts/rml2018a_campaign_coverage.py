"""Frozen all-row disposition and historical replay lineage; no RF executor."""
from pathlib import Path

import rml2018a_campaign as c

POLICY='standardized-replay-v1'
TOTAL=2555904
BATCHES=106496
PATTERNS=('b210-rml2018a-*/batch-*/source.json',
    'b210-rml2018a-*/run-plan.json','b210-rml-event-retest-*/plan.json',
    'b210-rml-uniform24-*/plan.json','b210-rml-snr-strata-*/plan.json')


def document(path):
    import json
    return json.loads(path.read_text())


def source_rows(path):
    d=document(path)
    if path.name=='source.json':rows=d['rows']
    elif path.name=='run-plan.json':
        rows=[row for v in d.get('event_sources',{}).values() for row in v['source']['rows']]
    else:rows=[row for point in d['points'] if point['mode'] for row in point['source']['rows']]
    c.require(all(type(row) is int and 0<=row<TOTAL for row in rows),'historical source row domain')
    return set(rows)


def history(base,exclude=None):
    parents=[];rows=set()
    for path in sorted({p for pattern in PATTERNS for p in base.glob(pattern)}):
        if exclude is not None and path.is_relative_to(exclude):continue
        c.require(path.resolve()==path and path.is_file(),'historical path identity')
        members=source_rows(path)
        if members:
            rows.update(members);parents.append(dict(path=str(path),sha256=c.file_hash(path)))
    return parents,rows


def ranges(values):
    """Sorted nonoverlapping half-open intervals, including the empty set."""
    result=[]
    for value in sorted(set(values)):
        if result and value==result[-1][1]:result[-1][1]+=1
        else:result.append([value,value+1])
    return result


def expand(intervals,limit):
    values=set();last=0
    for start,stop in intervals:
        c.require(type(start) is int and type(stop) is int and last<=start<stop<=limit,'coverage interval domain/order')
        values.update(range(start,stop));last=stop
    c.require(ranges(values)==intervals,'canonical coverage intervals')
    return values


def manifest(parents,rows):
    return dict(schema='rml2018a-coverage-policy-v1',policy=POLICY,
        source_rows=TOTAL,total_batches=BATCHES,rows_per_batch=24,
        domain=dict(first_row=0,stop_row=TOTAL,first_batch=0,stop_batch=BATCHES),
        membership='batch b contains rows [24*b,24*(b+1)); class=row//106496; Z=2*((row%106496)//4096)-20; actual Y/Z checked per batch',
        historical_parents=parents,historical_row_ranges=ranges(rows),
        historical_unique_rows=len(rows),historical_batch_ranges=ranges(row//24 for row in rows),
        disposition='Import verified completed compatible event-chunks once. All other batches remain pending fresh capture or standardized historical replay; no diagnostic result fills coverage implicitly.',
        replay='Explicit ledger reservation only; preserve original history and new source/capture/session provenance. Within this ledger each batch and original row has one owner, including failed/incomplete reservations.',
        inference='Frozen source/raw/guard, all failures retained; engineering comparison, not independent locked-test admission',
        automatic_execution=False)


def create(root):
    parents,rows=history(root.parent,root);value=manifest(parents,rows)
    c.save(root/'coverage-policy.json',value)
    return dict(policy=POLICY,path=str(root/'coverage-policy.json'),sha256=c.file_hash(root/'coverage-policy.json'))


def verify(root,receipt):
    path=root/'coverage-policy.json'
    c.require(receipt==dict(policy=POLICY,path=str(path),sha256=c.file_hash(path)),'coverage policy pin')
    value=document(path);rows=set()
    for parent in value['historical_parents']:
        q=Path(parent['path']);c.require(q.resolve()==q and c.file_hash(q)==parent['sha256'],'historical lineage pin')
        rows.update(source_rows(q))
    c.require(value==manifest(value['historical_parents'],rows),'coverage policy contract')
    return value


def authorize(root,p,parents,overlap):
    """Only ledger-bound children may replay frozen history; legacy stays strict."""
    import rml2018a_campaign_ledger as ledger
    receipt=p.get('source_verification');c.require(receipt is not None,'replay requires ledger source receipt')
    ledger.verify_cached(receipt);owner=Path(receipt['ledger_root']);plan=ledger.load(owner)
    policy=verify(owner,plan['coverage'])
    path=ledger.entry_path(owner,root)
    c.require(path.is_file(),'replay reservation missing')
    entry=ledger.m.document(path)
    c.require(entry['kind']=='reserved' and entry['child_root']==str(root) and
        entry['ledger_plan_sha256']==c.file_hash(owner/'ledger-plan.json') and
        entry['batch_indices']==p['execution_limits']['allowed_batch_indices'],'replay reservation binding')
    c.require(p['tx_level_profile']=='event-chunk' and p['coverage']==plan['coverage'],'replay profile/policy')
    pinned={v['path']:v['sha256'] for v in policy['historical_parents']}
    selected={row for v in p['event_sources'].values() for row in v['source']['rows']}
    for parent in parents:
        if source_rows(Path(parent['path']))&selected:
            c.require(pinned.get(parent['path'])==parent['sha256'],'unregistered overlapping history after policy freeze')
    c.require(overlap<=expand(policy['historical_row_ranges'],TOTAL),'unregistered replay rows')


def partition(policy,campaigns):
    historical=expand(policy['historical_batch_ranges'],BATCHES)
    sets={k:set() for k in ('imported_complete','new_complete','registered_incomplete','pending_historical_replay','pending_fresh')}
    seen=set()
    for v in campaigns:
        ids=v['batch_indices'];c.require(len(ids)==len(set(ids)) and all(type(i) is int and 0<=i<BATCHES for i in ids) and not seen.intersection(ids),'coverage duplicate/domain')
        c.require(v['kind'] in ('imported','reserved'),'coverage registration kind')
        tag=('imported_complete' if v['kind']=='imported' else 'new_complete') if v['state']=='completed' else 'registered_incomplete'
        sets[tag].update(ids);seen.update(ids)
    sets['pending_historical_replay']=historical-seen
    sets['pending_fresh']=set(range(BATCHES))-seen-historical
    c.require(sum(map(len,sets.values()))==BATCHES and set.union(*sets.values())==set(range(BATCHES)),'full coverage partition')
    return dict(policy=POLICY,total_source_rows=TOTAL,total_batches=BATCHES,
        historical_unique_rows=policy['historical_unique_rows'],
        dispositions={k:dict(batch_ranges=ranges(v),batches=len(v),source_rows=len(v)*24) for k,v in sets.items()},
        whole_dataset_complete=len(sets['imported_complete'])+len(sets['new_complete'])==BATCHES)
