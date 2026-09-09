"""Consume FC toolkit evidence; retain queueboard's classification and timing model."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from conjectures.catalog_data import module_path
from conjectures.core import save
from conjectures.evidence_reader import load
from conjectures.projections import contribution_context, work_context

HERE=Path(__file__).parent


def queue_context(snapshot, basics):
    rows=[];times=[]
    for number, pr in snapshot['prs'].items():
        basic=basics.get(str(number),{})
        if basic.get('headRefOid'):
            if not basic.get('observedAt'):raise ValueError('PR observation time is missing. Run ./sync.sh again.')
            times.append(basic['observedAt'])
        rows.append({'number':int(number),'title':pr.get('title') or '(untitled)',
                     'head':basic.get('headRefOid'),'base':basic.get('baseRefOid'),
                     'files':pr.get('modified_files') or []})
    return work_context({'schema_version':'fc.work-context.v1','repository':'google-deepmind/formal-conjectures',
        'observed_at':min(times) if times else datetime.now(timezone.utc).isoformat(),'pull_requests':rows})


def build():
    snapshot=json.loads((HERE/'snapshot.json').read_text())
    basics=json.loads((HERE/'pr_basics.json').read_text())
    work=queue_context(snapshot,basics)
    repo=os.environ.get('FC_EVIDENCE_REPOSITORY');branch=os.environ.get('FC_EVIDENCE_BRANCH')
    if bool(repo)!=bool(branch):raise ValueError('Configure both FC evidence repository and branch')
    evidence=load(destination={'repository':repo,'branch':branch} if repo else None)
    context=contribution_context(evidence,work)
    for record in context['runs']:
        paths=record.get('scope',[])
        if record['kind']=='verify' and record.get('target',{}).get('module'):
            paths=[module_path(record['target']['module'])]
        record['fc_pages']=[{'path':path,'url':'https://google-deepmind.github.io/formal-conjectures/src/'+quote('/'.join('«'+part+'»' if part[0].isdigit() else part for part in path.removesuffix('.lean').split('/')),safe='/')+'/'}
            for path in paths if path.startswith('FormalConjectures/') and path.endswith('.lean')]
    save(HERE/'work.json',work)
    save(HERE/'toolkit-evidence.json',context)
    return context


if __name__=='__main__':build()
