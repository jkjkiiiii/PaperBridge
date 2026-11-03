"""Real LLM integration checks; output evidence is distinct from deterministic tests."""
from io import BytesIO
import json
from pathlib import Path
import sys
import httpx
from docx import Document
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.documents import extract,package_hashes

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.data'/'verification';OUT.mkdir(exist_ok=True)
c=httpx.Client(base_url='http://127.0.0.1:17865/api',trust_env=False,timeout=620)
d=Document();p=d.add_paragraph();p.add_run('I love ');p.add_run('you').bold=True;p.add_run('. We live in Beijing.')
d.add_paragraph('The study included ten participants. The analysis used two tasks. The result was stable.')
d.add_paragraph('A removable paragraph.')
buf=BytesIO();d.save(buf);source=buf.getvalue();(OUT/'sample.docx').write_bytes(source)
project=c.post('/projects',files={'file':('Editing-demo.docx',source)}).json();pid=project['id'];records=[]
def get():return c.get('/projects/'+pid).json()
def model(id,task):
    r=c.post(f'/projects/{pid}/paragraphs/{id}/model',json={'task':task});r.raise_for_status();return r.json()
for p in project['paragraphs']:model(p['id'],'translate_align')
project=get();p=project['paragraphs'][0]
assert p['status']=='ready',p.get('error')
# Exact test Chinese controls intended edit, independent of initial translation wording.
zh=p['draftZh'].replace('你','她')
assert zh!=p['draftZh'],'Expected person pronoun in sample translation'
r=c.post(f'/projects/{pid}/paragraphs/{p["id"]}/draft',json={'text':zh,'revision':p['revision']});r.raise_for_status()
project=model(p['id'],'rewrite_en');after=project['paragraphs'][0]
assert after['status']=='ready',after.get('error')
assert after['en']=='I love her. We live in Beijing.',after['en']
records.append({'case':'word_change','en':after['en'],'pass':True,'meta':after.get('modelMeta')})
r=c.get(f'/projects/{pid}/export');r.raise_for_status();(OUT/'sample_edited.docx').write_bytes(r.content)
before=package_hashes(source);afterhash=package_hashes(r.content)
assert {k:v for k,v in before.items() if k!='word/document.xml'}=={k:v for k,v in afterhash.items() if k!='word/document.xml'}
assert extract(r.content)[0]['en']=='I love her. We live in Beijing.'
records.append({'case':'export_content_and_unmodified_parts','pass':True})
(OUT/'sample_config.json').write_text(json.dumps(c.get(f'/projects/{pid}/config').json(),ensure_ascii=False,indent=2),'utf-8')
(OUT/'real_model_checks.json').write_text(json.dumps({'projectId':pid,'records':records},ensure_ascii=False,indent=2),'utf-8')
print(json.dumps({'projectId':pid,'checks':len(records),'passed':True}),flush=True)
