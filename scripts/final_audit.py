"""Read current service/project state and emit bounded, reproducible audit evidence."""
from pathlib import Path
from hashlib import sha256
import argparse
import json
import subprocess
import httpx
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'.data'/'verification';OUT.mkdir(parents=True,exist_ok=True)
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--project-id',required=True)
parser.add_argument('--source',type=Path,help='Optional independent original DOCX')
parser.add_argument('--base-url',default='http://127.0.0.1:17865/api')
args=parser.parse_args()
c=httpx.Client(base_url=args.base_url,trust_env=False,timeout=180)
health=c.get('/health').json()
response=c.get('/projects/'+args.project_id);response.raise_for_status();demo=response.json()
config=c.get(f'/projects/{demo["id"]}/config');config.raise_for_status();config=config.json()
export=c.get(f'/projects/{demo["id"]}/export');export.raise_for_status()
source=args.source
if source:
    assert sha256(source.read_bytes()).hexdigest()==demo['sourceSha256']
    if not config['operations']:assert export.content==source.read_bytes()
# Scan only non-ignored repository files; do not print credential values.
files=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
def secret_values(value):
    if isinstance(value,str):
        if len(value)>8:yield value
    elif isinstance(value,dict):
        for item in value.values():yield from secret_values(item)
    elif isinstance(value,list):
        for item in value:yield from secret_values(item)
secrets=[]
for secret_name in ('secrets.json','translation-secrets.json'):
    secret_file=ROOT/'.data'/secret_name
    if secret_file.exists():secrets.extend(secret_values(json.loads(secret_file.read_text('utf-8-sig'))))
hits=[]
for relative in filter(None,files):
    path=ROOT/relative
    if path.is_file():
        data=path.read_bytes()
        if any(value.encode() in data for value in secrets):hits.append(relative)
assert not hits,'Credential present in non-ignored source files'
result={'health':health,'demoProjectId':demo['id'],'paragraphs':len(demo['paragraphs']),
    'tableParagraphs':sum(p['container']=='table' for p in demo['paragraphs']),
    'protectedParagraphs':sum(bool(p['protected']) for p in demo['paragraphs']),
    'exportSucceeded':True,'sourceHashVerified':source is not None,
    'credentialScan':'passed',
    'semanticHumanReview':'not performed; structure and selected integration examples only'}
(OUT/'final_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ('sourceSha256','connectionTest')},ensure_ascii=True),flush=True)
