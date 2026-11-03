from copy import deepcopy
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from server.preview_state import committed_preview
from server.documents import export_docx, build_chinese_preview, extract
from server.state import Store, StateError
from test_documents import fixture_doc


def test_pending_snapshots_preserve_draft_and_strict_export(tmp_path, monkeypatch):
    import server.app as api
    store = Store(tmp_path/'projects')
    project = store.create(fixture_doc(), 'demo.docx')
    item = project['paragraphs'][1]
    item.update(zh='我爱你。我们住在北京。', draftZh='我爱她。我们住在北京。', status='pending')
    store.save(project)
    original = deepcopy(project)
    snapshot, pending = committed_preview(project)
    assert project == original
    assert snapshot['paragraphs'][1]['draftZh'] == item['zh']
    assert snapshot['paragraphs'][1]['units'] == []
    assert pending == [{'id':item['id'], 'status':'pending', 'error':''}]
    assert extract(export_docx(store.source(project), snapshot['paragraphs']))[1]['en'] == item['en']
    assert extract(build_chinese_preview(store.source(project), snapshot['paragraphs']))[1]['en'] == item['zh']
    with pytest.raises(StateError): store.export(project)
    monkeypatch.setattr(api, 'store', store)
    monkeypatch.setattr(api, 'DATA', tmp_path)
    pdf = tmp_path/'fake.pdf'; pdf.write_bytes(b'%PDF-test')
    monkeypatch.setattr(api, 'render_preview', lambda data,cache: pdf)
    monkeypatch.setattr(api, 'native_layout', lambda pdf, paragraphs, cache, revision, original, language: {'revision':revision,'pages':[]})
    with TestClient(api.app) as client:
        for language in ('en','zh'):
            result = client.get(f'/api/projects/{project["id"]}/native-layout?language={language}')
            assert result.status_code == 200
            assert result.json()['snapshotKind'] == 'last-synced'
            assert result.json()['disabledUnitParagraphs'] == [item['id']]
        assert client.get(f'/api/projects/{project["id"]}/preview?original=false').status_code == 200
        assert client.get(f'/api/projects/{project["id"]}/export').status_code == 422
    assert store.get(project['id'])['paragraphs'][1]['draftZh'] == item['draftZh']


def test_conflict_uses_safe_history_or_original_without_mutating():
    base = {'id':'p1','en':'Committed text.','originalEn':'Original text.','zh':'已同步。','draftZh':'已同步。','status':'ready','units':[],'targetUnits':[],'groups':[]}
    bad = dict(base, en='Unverified text.',zh='未验证。',draftZh='用户草稿。',status='conflict',history=[deepcopy(base)])
    project = {'paragraphs':[bad]}; original=deepcopy(project)
    snapshot, pending=committed_preview(project)
    assert snapshot['paragraphs'][0]['en']=='Committed text.'
    assert snapshot['paragraphs'][0]['zh']=='已同步。'
    assert project==original
    bad['history']=[]
    snapshot,_=committed_preview(project)
    assert snapshot['paragraphs'][0]['en']=='Original text.'
    assert snapshot['paragraphs'][0]['zh']==''
    assert bad['draftZh']=='用户草稿。'
