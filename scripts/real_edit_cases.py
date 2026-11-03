"""Run the remaining requested editing scenarios against the configured local model."""
from io import BytesIO
from pathlib import Path
import json
import sys
import httpx
from docx import Document
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.documents import extract
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'.data'/'verification';OUT.mkdir(exist_ok=True)
c=httpx.Client(base_url='http://127.0.0.1:17865/api',trust_env=False,timeout=620)
d=Document();d.add_paragraph('The study included ten participants. The analysis used two tasks. The result was stable.');d.add_paragraph('A removable paragraph.')
b=BytesIO();d.save(b);source=b.getvalue()
p=c.post('/projects',files={'file':('Edit-scenarios.docx',source)}).json();pid=p['id'];paragraph=p['paragraphs'][0]['id'];records=[]
def state():return c.get('/projects/'+pid).json()
def get(id=paragraph):return next(x for x in state()['paragraphs'] if x['id']==id)
def model(id,task):
    r=c.post(f'/projects/{pid}/paragraphs/{id}/model',json={'task':task});r.raise_for_status();q=next(x for x in r.json()['paragraphs'] if x['id']==id)
    assert q['status']=='ready',(id,q['status'],q.get('error'));return q
def edit(text,id=paragraph):
    q=get(id);r=c.post(f'/projects/{pid}/paragraphs/{id}/draft',json={'text':text,'revision':q['revision']});r.raise_for_status();return model(id,'rewrite_en')
def record(case,q):
    records.append({'case':case,'en':q['en'],'zh':q['zh'],'groups':q['groups'],'pass':True,'meta':q.get('modelMeta')})
    (OUT/'real_edit_cases.json').write_text(json.dumps({'projectId':pid,'records':records},ensure_ascii=False,indent=2),'utf-8');print(case,'PASS',flush=True)
q=model(paragraph,'translate_align');locked=q['units'][1]['text']
q=edit('本研究纳入了十一名参与者。分析使用了两项任务。结果不稳定。')
assert locked in q['en'];assert 'eleven' in q['en'].lower() or '11' in q['en'];assert 'not stable' in q['en'].lower() or 'unstable' in q['en'].lower();record('multiple_sentence_edits',q)
targets=q['targetUnits'];q=edit(''.join(u['text'] for i,u in enumerate(targets) if i!=1));assert 'two tasks' not in q['en'];record('delete_sentence',q)
targets=q['targetUnits'];q=edit(targets[0]['text']+'这是新增的测试句子。'+''.join(u['text'] for u in targets[1:]));assert len(q['units'])>=3;record('insert_sentence',q)
r=c.post(f'/projects/{pid}/paragraphs/{paragraph}/action',json={'action':'insert'});r.raise_for_status();new=r.json()['paragraphs'][1]
q=edit('此段仅用于软件验证。',new['id']);assert q['en'];record('insert_paragraph',q)
last=state()['paragraphs'][-1];r=c.post(f'/projects/{pid}/paragraphs/{last["id"]}/action',json={'action':'delete'});r.raise_for_status();assert r.json()['paragraphs'][-1]['deleted'];record('delete_paragraph',r.json()['paragraphs'][-1])
r=c.get(f'/projects/{pid}/export');r.raise_for_status();(OUT/'scenarios_edited.docx').write_bytes(r.content)
texts=[x['en'] for x in extract(r.content)];assert len(texts)==2;assert not any('removable' in x for x in texts);assert any('verification' in x.lower() or 'validation' in x.lower() for x in texts)
config=c.get(f'/projects/{pid}/config').json();(OUT/'scenarios_config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),'utf-8')
fresh=c.post('/projects',files={'file':('Config-replay-demo.docx',source)}).json();replayed=c.post(f'/projects/{fresh["id"]}/config',json={'config':config,'apply':True});replayed.raise_for_status();assert replayed.json().get('applied'),replayed.json()
r2=c.get(f'/projects/{fresh["id"]}/export');r2.raise_for_status();assert [x['en'] for x in extract(r2.content)]==texts
print('config_replay PASS',flush=True)
records.append({'case':'export_and_config_replay','pass':True});(OUT/'real_edit_cases.json').write_text(json.dumps({'projectId':pid,'records':records},ensure_ascii=False,indent=2),'utf-8')
