from copy import deepcopy
import json
import pytest
from fastapi.testclient import TestClient
import server.app as api
from server.llm import ModelClient
from server.translation_settings import save_translation_settings, public_settings, read_translation_secrets


def test_separate_credentials_and_model_settings(tmp_path, monkeypatch):
    client = ModelClient(tmp_path)
    monkeypatch.setattr(api, 'DATA', tmp_path)
    monkeypatch.setattr(api, 'client', client)
    body = {'providerId':'volc', 'providers':[{'id':'volc','kind':'volcengine','name':'Volc',
        'baseUrl':'https://translate.volcengineapi.com','credentials':{'accessKeyId':'test-access','secretAccessKey':'test-secret'}}]}
    saved = save_translation_settings(tmp_path, body)
    assert saved['providers'][0]['credentialFields'] == ['accessKeyId','secretAccessKey']
    assert 'test-secret' not in json.dumps(saved)
    assert 'test-secret' not in (tmp_path/'translation-settings.json').read_text()
    assert read_translation_secrets(tmp_path)['volc']['secretAccessKey']=='test-secret'
    assert client.read_settings()['translation']['providerId']=='volc'
    config=client.read_settings()
    config['translation']={'providerId':'llm','providers':[]}
    with TestClient(api.app) as c:
        r=c.post('/api/settings',json=config)
        assert r.status_code==200, r.text
        assert r.json()['translation']['providerId']=='volc'
        assert 'test-secret' not in c.get('/api/translation-settings').text


def test_host_change_clears_credential_and_invalid_save_is_atomic(tmp_path):
    original={'providerId':'libre','providers':[{'id':'libre','kind':'libretranslate','name':'Local',
        'baseUrl':'http://localhost:5000','credentials':{'apiKey':'old-secret'}}]}
    save_translation_settings(tmp_path,original)
    changed=public_settings(tmp_path);changed['providers'][0]['baseUrl']='https://translation.example.com'
    save_translation_settings(tmp_path,changed)
    assert not public_settings(tmp_path)['providers'][0]['credentialFields']
    before=(tmp_path/'translation-secrets.json').read_bytes()
    invalid=deepcopy(original);invalid['providers'][0]['kind']='not-supported'
    with pytest.raises(ValueError):save_translation_settings(tmp_path,invalid)
    assert (tmp_path/'translation-secrets.json').read_bytes()==before


def test_api_probe_uses_saved_service_without_model(tmp_path,monkeypatch):
    from server import translation_services
    monkeypatch.setattr(api,'DATA',tmp_path)
    save_translation_settings(tmp_path,{'providerId':'local','providers':[{'id':'local','kind':'libretranslate','name':'Local','baseUrl':'http://localhost:5000'}]})
    async def translated(texts,source,target,config,credentials):
        assert texts==['The sample contains two cells.'] and config['id']=='local'
        return ['样本包含两个细胞。']
    monkeypatch.setattr(translation_services,'translate',translated)
    with TestClient(api.app) as c:
        r=c.post('/api/translation-settings/test',json={'providerId':'local'})
        assert r.status_code==200 and r.json()['ok'] and r.json()['service']=='libretranslate'
