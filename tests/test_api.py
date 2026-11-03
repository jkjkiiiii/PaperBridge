import asyncio
from copy import deepcopy
import json
from pathlib import Path
import pytest
import httpx
from fastapi.testclient import TestClient
import server.app as api
from server.state import Store, merge_text, StateError, save_json, rebase_config
from server.llm import ModelClient, ModelError, parse_json
from test_documents import fixture_doc, texts

@pytest.fixture
def http(tmp_path,monkeypatch):
    monkeypatch.setattr(api,'DATA',tmp_path);monkeypatch.setattr(api,'store',Store(tmp_path/'projects'));monkeypatch.setattr(api,'client',ModelClient(tmp_path))
    with TestClient(api.app) as c:yield c

def uploaded(c):
    r=c.post('/api/projects',files={'file':('sample.docx',fixture_doc())});assert r.status_code==200;return r.json()

def test_config_replay_and_idempotence(http):
    p=uploaded(http);pid=p['id'];item=p['paragraphs'][1]
    config={'schemaVersion':'1.0','sourceSha256':p['sourceSha256'],'operations':[{'type':'replace_text','paragraphId':item['id'],'beforeEn':item['en'],'afterEn':item['en'].replace('you','her')}],'paragraphStates':[]}
    preview=http.post(f'/api/projects/{pid}/config',json={'config':config,'apply':False}).json();assert not preview['conflicts']
    result=http.post(f'/api/projects/{pid}/config',json={'config':config,'apply':True}).json()['project']
    assert result['paragraphs'][1]['en']=='I love her. We live in Beijing.'
    assert result['paragraphs'][1]['status']=='needs_alignment'
    # A hand-edited patch must not retain a forged ready state.
    assert http.get(f'/api/projects/{pid}/export').status_code==422
    twice=http.post(f'/api/projects/{pid}/config',json={'config':config,'apply':True}).json()
    assert not twice['conflicts'];assert twice['project']['paragraphs'][1]['en']==result['paragraphs'][1]['en']
    config['sourceSha256']='wrong'
    assert http.post(f'/api/projects/{pid}/config',json={'config':config}).status_code==422

def test_config_restores_translation_and_pending_draft(http):
    p=uploaded(http);pid=p['id'];item=p['paragraphs'][1];ids=[u['id'] for u in item['units']]
    new=api.translation_candidate(item,{'target_units':[{'id':'z1','text':'我爱你。','source_ids':[ids[0]]},{'id':'z2','text':'我们住在北京。','source_ids':[ids[1]]}],'unresolved':[]})
    p['paragraphs'][1]=new;new['draftZh']='我爱她。我们住在北京。';new['status']='pending';api.store.save(p)
    config=http.get(f'/api/projects/{pid}/config').json();fresh=uploaded(http)
    result=http.post(f'/api/projects/{fresh["id"]}/config',json={'config':config,'apply':True}).json()['project']
    restored=result['paragraphs'][1]
    assert restored['zh']=='我爱你。我们住在北京。';assert restored['draftZh'].startswith('我爱她');assert restored['status']=='pending';assert restored['groups']

def test_merge_disjoint_and_conflict():
    assert merge_text('One two three.','ONE two three.','One two THREE.')=='ONE two THREE.'
    assert merge_text('abc','aXbc','aXbc')=='aXbc'
    with pytest.raises(StateError):merge_text('abc','aXbc','aYbc')

def test_cross_file_rebase_requires_unique_exact_original(tmp_path):
    s=Store(tmp_path);p=s.create(fixture_doc(),'sample.docx');item=p['paragraphs'][1]
    source=deepcopy(item);source['id']='old_para'
    config={'sourceSha256':'a'*64,'operations':[{'type':'replace_text','paragraphId':'old_para','beforeEn':item['originalEn'],'afterEn':item['en'].replace('you','her')}],'paragraphStates':[source]}
    rebased,evidence=rebase_config(p,config);assert rebased['operations'][0]['paragraphId']==item['id'];assert evidence[0]['method']=='unique_exact_text'
    p['paragraphs'].append({**deepcopy(item),'id':'duplicate'})
    with pytest.raises(StateError,match='唯一'):rebase_config(p,config)

def test_credentials_not_exported(http,tmp_path):
    settings=http.get('/api/settings').json();settings['providers'][0]['apiKey']='synthetic-test-secret'
    response=http.post('/api/settings',json=settings);assert response.status_code==200;assert 'synthetic-test-secret' not in response.text;assert response.json()['providers'][0]['hasKey']
    p=uploaded(http);assert 'synthetic-test-secret' not in http.get(f'/api/projects/{p["id"]}/config').text
    assert http.post('/api/settings',json=settings,headers={'Origin':'https://unrelated.example'}).status_code==403

def test_model_out_of_order_cannot_commit(tmp_path,monkeypatch):
    store=Store(tmp_path/'projects');monkeypatch.setattr(api,'store',store)
    p=store.create(fixture_doc(),'source.docx');item=p['paragraphs'][1];ids=[u['id'] for u in item['units']]
    p['paragraphs'][1]=api.translation_candidate(item,{'target_units':[{'id':'z1','text':'我爱你。','source_ids':[ids[0]]},{'id':'z2','text':'我们住在北京。','source_ids':[ids[1]]}],'unresolved':[]})
    store.save(p);store.draft(p,item['id'],'我爱她。我们住在北京。',0)
    async def scenario():
        started=asyncio.Event();release=asyncio.Event()
        class Fake:
            def read_settings(self):return {}
            async def generate(self,task,payload,**kwargs):
                started.set();await release.wait();units=deepcopy(payload['source_units']);units[0]['text']='I love her. '
                return {'data':{'english_units':units,'links':[{'source_ids':[u['id']],'target_ids':[v['id']]} for u,v in zip(units,payload['target_units'])],'unresolved':[]},'meta':{'model':'fixed-response'}}
        monkeypatch.setattr(api,'client',Fake())
        job=asyncio.create_task(api.run_model(p['id'],item['id'],{'task':'rewrite_en'}));await started.wait()
        live=store.get(p['id']);current=store.paragraph(live,item['id']);store.draft(live,item['id'],'我爱他们。我们住在北京。',current['revision'])
        release.set();await job
        current=store.paragraph(store.get(p['id']),item['id']);assert current['en'].startswith('I love you.');assert current['draftZh'].startswith('我爱他们');assert current['status']=='pending'
    asyncio.run(scenario())

@pytest.mark.parametrize('content',['not json','{"unresolved":', '[]'])
def test_invalid_model_json(content):
    with pytest.raises(ModelError):parse_json(content)

def test_invalid_docx_is_clear_error(http):
    response=http.post('/api/projects',files={'file':('broken.docx',b'not a docx')})
    assert response.status_code==422;assert 'DOCX' in response.json()['detail']

@pytest.mark.parametrize('operations',[{},[{'type':'replace_text','paragraphId':'p00001','beforeEn':5,'afterEn':'x'}]])
def test_malformed_config_is_rejected_without_mutation(http,operations):
    p=uploaded(http);response=http.post(f'/api/projects/{p["id"]}/config',json={'apply':True,'config':{'schemaVersion':'1.0','sourceSha256':p['sourceSha256'],'operations':operations}})
    assert response.status_code==422;assert 'schema' in response.json()['detail']
    assert http.get(f'/api/projects/{p["id"]}').json()['revision']==0
