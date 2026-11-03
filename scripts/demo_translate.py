"""Translate missing paragraphs in an explicitly selected project using its configured model."""
import argparse
import json
import time
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--project-id', required=True, help='Project ID shown by GET /api/projects')
parser.add_argument('--base-url', default='http://127.0.0.1:17865/api')
args=parser.parse_args()
client=httpx.Client(base_url=args.base_url,timeout=620,trust_env=False)
pid=args.project_id; report=[]
(ROOT/'.data').mkdir(exist_ok=True)
state=client.get('/projects/'+pid).json()
for item in state['paragraphs']:
    if item['zh'] or not item['en'].strip(): continue
    started=time.time()
    r=client.post(f'/projects/{pid}/paragraphs/{item["id"]}/model',json={'task':'translate_align'})
    r.raise_for_status(); fresh=next(x for x in r.json()['paragraphs'] if x['id']==item['id'])
    report.append({'paragraph':item['id'],'status':fresh['status'],'seconds':round(time.time()-started,2),'error':fresh.get('error','')})
    (ROOT/'.data'/'demo_progress.json').write_text(json.dumps({'projectId':pid,'results':report},ensure_ascii=False,indent=2),'utf-8')
    print(item['id'],fresh['status'],round(time.time()-started,1),flush=True)
print('DONE',pid,flush=True)
