from copy import deepcopy
import json
import pytest
from fastapi.testclient import TestClient
import server.app as api
from server.llm import ModelClient
from server.state import save_json
from server.translation_settings import save_translation_settings


@pytest.fixture
def configured(tmp_path, monkeypatch):
    client = ModelClient(tmp_path)
    config = client.read_settings()
    original = config['profiles'][0]
    config['profiles'].append({**deepcopy(original), 'id':'second-model', 'model':'second-model'})
    save_json(tmp_path/'settings.json', config)
    save_translation_settings(tmp_path, {'providerId':'native-api', 'providers':[
        {'id':'native-api','kind':'libretranslate','name':'Native MT','baseUrl':'http://localhost:5000',
         'credentials':{'apiKey':'private-native-key'}}]})
    monkeypatch.setattr(api, 'DATA', tmp_path)
    monkeypatch.setattr(api, 'client', client)
    with TestClient(api.app) as http:
        yield tmp_path, client, http, original['id']


def choices(original, kind='translation_api', identifier='native-api'):
    return {'initialTranslation':{'kind':kind,'id':identifier},
        'mappingModelId':'second-model', 'rewriteModelId':original}


def test_legacy_migration_preserves_existing_selection_without_write(configured):
    folder, client, http, original = configured
    assert http.get('/api/task-assignments').json() == {
        'initialTranslation':{'kind':'translation_api','id':'native-api'},
        'mappingModelId':original,'rewriteModelId':original}
    assert not (folder/'task-assignments.json').exists()
    assert client.read_settings()['translation']['providerId']=='native-api'


def test_save_reload_and_stale_configuration_cannot_override_tasks(configured):
    folder, client, http, original = configured
    desired = choices(original)
    assert http.post('/api/task-assignments',json=desired).json()==desired
    fresh = ModelClient(folder).read_settings()
    assert fresh['routes']['repair_alignment']=='second-model'
    assert fresh['routes']['rewrite_en']==original
    assert fresh['routes']['translate_align']==original
    stale=deepcopy(fresh);stale['routes']={k:original for k in stale['routes']}
    assert http.post('/api/settings',json=stale).status_code==200
    translation=http.get('/api/translation-settings').json();translation['providerId']='llm'
    assert http.post('/api/translation-settings',json=translation).status_code==200
    assert http.get('/api/task-assignments').json()==desired
    assert ModelClient(folder).read_settings()['translation']['providerId']=='native-api'
    assert 'private-native-key' not in (folder/'task-assignments.json').read_text()
    assert 'private-native-key' not in http.get('/api/settings').text


def test_initial_translation_llm_and_mapping_validation(configured):
    folder, client, http, original = configured
    value=choices(original,'llm','second-model')
    assert http.post('/api/task-assignments',json=value).status_code==200
    state=client.read_settings()
    assert state['translation']['providerId']=='llm'
    assert state['routes']['translate_align']=='second-model'
    before=(folder/'task-assignments.json').read_bytes()
    for field in ['mappingModelId','rewriteModelId']:
        invalid=deepcopy(value);invalid[field]='native-api'
        assert http.post('/api/task-assignments',json=invalid).status_code==422
        assert (folder/'task-assignments.json').read_bytes()==before
    invalid=deepcopy(value);invalid['initialTranslation']['id']='unsaved-model'
    assert http.post('/api/task-assignments',json=invalid).status_code==422


def test_deleting_assigned_model_or_api_is_rejected(configured):
    folder, client, http, original = configured
    assert http.post('/api/task-assignments',json=choices(original)).status_code==200
    proposed=client.read_settings()
    proposed['profiles']=[p for p in proposed['profiles'] if p['id']!='second-model']
    assert http.post('/api/settings',json=proposed).status_code==422
    assert http.post('/api/translation-settings',json={'providerId':'llm','providers':[]}).status_code==422
    assert client.read_settings()['translation']['providers'][0]['id']=='native-api'
