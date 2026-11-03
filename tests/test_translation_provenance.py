from copy import deepcopy
import json
from fastapi.testclient import TestClient
from server.llm import ModelClient
from server.state import Store
from server.translation_provenance import provenance,plan,next_labels
from server.retranslation import RetranslationJobs
from test_documents import fixture_doc


def test_historical_mixed_unknown_and_rewrite_are_not_live_settings(tmp_path):
    client=ModelClient(tmp_path)
    p={'revision':1,'paragraphs':[
        {'zh':'甲','modelMeta':{'task':'translate_align','model':'historical-A','apiKey':'do-not-expose'}},
        {'zh':'乙','modelMeta':{'task':'translate_align','model':'historical-B','translationService':{'kind':'azure','id':'old'}}},
        {'zh':'丙','modelMeta':{'task':'rewrite_en','model':'English-rewrite-model'}},
        {'zh':'丁'},
        {'zh':'123','modelMeta':{'model':'numeric-identity'}}]}
    result=plan(p,client,client.read_settings(),b'source')
    assert result['current']['status']=='multiple'
    assert result['current']['unknownParagraphs']==2
    assert result['current']['translatedParagraphs']==4
    text=json.dumps(result)
    assert 'historical-A' in text and 'historical-B' in text
    assert 'English-rewrite-model' not in text and 'do-not-expose' not in text and 'apiKey' not in text
    assert client.read_settings()['profiles'][0]['model'] not in result['current']['translationLabel']


def test_planned_snapshot_is_not_completed_translation(tmp_path):
    client=ModelClient(tmp_path);pinned=client.read_settings();pinned['profiles'][0]['model']='pinned-old-model'
    p={'paragraphs':[{'zh':''}],'retranslation':{'status':'running','settings':pinned}}
    result=provenance(p,client)
    assert result['status']=='none' and result['translationLabel']=='尚无译文'
    assert 'pinned-old-model' in result['planned']['translationLabel']
    p['paragraphs']=[{'zh':'旧译文'}]
    result=provenance(p,client)
    assert result['status']=='unknown' and 'pinned-old-model' not in result['translationLabel']


def test_next_api_and_alignment_labels_are_safe(tmp_path):
    client=ModelClient(tmp_path);settings=client.read_settings()
    settings['providers'][0]['apiKey']='secret-llm'
    settings['translation']={'providerId':'mt','providers':[{'id':'mt','kind':'azure','name':'Selected MT',
        'baseUrl':'https://user:secret-host@example.test/key-in-path','apiKey':'secret-api'}]}
    result=next_labels(client,settings)
    assert result['translationLabel']=='Selected MT · 翻译 API'
    assert settings['profiles'][0]['model'] in result['alignmentLabel']
    assert 'secret' not in json.dumps(result)


def test_plan_token_rejects_settings_and_source_changes_without_launch(tmp_path,monkeypatch):
    import server.app as api
    store=Store(tmp_path/'projects');source=store.create(fixture_doc(),'paper.docx')
    llm=ModelClient(tmp_path);settings=llm.read_settings()
    monkeypatch.setattr(llm,'read_settings',lambda:deepcopy(settings))
    monkeypatch.setattr(api,'DATA',tmp_path);monkeypatch.setattr(api,'store',store);monkeypatch.setattr(api,'client',llm)
    jobs=RetranslationJobs();launches=[]
    monkeypatch.setattr(jobs,'launch',lambda *args:launches.append(args[2]['id']))
    monkeypatch.setattr(api,'retranslation_jobs',jobs)
    url=f'/api/projects/{source["id"]}'
    with TestClient(api.app) as http:
        assert http.get(url).json()['translationProvenance']['status']=='none'
        assert http.get(url+'/translation-provenance').json()==http.get(url).json()['translationProvenance']
        initial=http.get(url+'/retranslate-plan').json()
        settings['style']='changed style'
        assert http.post(url+'/retranslate',json={'planToken':initial['planToken']}).status_code==409
        fresh=http.get(url+'/retranslate-plan').json()
        changed=store.get(source['id']);changed['revision']+=1;store.save(changed)
        assert http.post(url+'/retranslate',json={'planToken':fresh['planToken']}).status_code==409
        assert not launches and len(list((tmp_path/'projects').iterdir()))==1
        latest=http.get(url+'/retranslate-plan').json()
        response=http.post(url+'/retranslate',json={'planToken':latest['planToken']})
        assert response.status_code==200
        new=response.json();assert new['translationProvenance']['status']=='none'
        assert new['translationProvenance']['planned']==latest['next']
        assert new['retranslation']['settings']['style']=='changed style'
        assert len(launches)==1
        assert http.post(url+'/retranslate',json={}).status_code==200
