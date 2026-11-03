import asyncio
from copy import deepcopy
import pytest
from server.retranslation import RetranslationJobs
from server.state import Store, StateError
from server.llm import ModelClient
from server.app import translation_candidate, context_for
from test_documents import fixture_doc


class FakeClient:
    def __init__(self, path):
        self.settings = ModelClient(path).read_settings()
        self.settings['profiles'][0]['model'] = 'new-model'
        self.calls = []
    def read_settings(self): return deepcopy(self.settings)
    def resolve(self, settings, task): return settings['providers'][0], settings['profiles'][0]
    async def generate(self, task, payload, settings, cache):
        self.calls.append((settings['profiles'][0]['model'], cache))
        return {'data': {'target_units': [{'id': f'z{i}', 'text': unit['text'], 'source_ids': [unit['id']]}
            for i, unit in enumerate(payload['source_units'])], 'unresolved': []}, 'meta': {'model': settings['profiles'][0]['model']}}


def test_new_version_preserves_edited_english_and_source_and_pins_model(tmp_path):
    store = Store(tmp_path/'projects'); source = store.create(fixture_doc(), 'paper.docx')
    source['paragraphs'][1]['en'] = source['paragraphs'][1]['en'].replace('you', 'her')
    store.save(source); before = store.get(source['id']); original_bytes = store.source(source)
    client = FakeClient(tmp_path); jobs = RetranslationJobs()
    new = jobs.create(store, client, source)
    assert new['id'] != source['id']
    assert new['paragraphs'][1]['en'] == source['paragraphs'][1]['en']
    assert not new['paragraphs'][1]['zh'] and not new['paragraphs'][1]['groups']
    client.settings['profiles'][0]['model'] = 'changed-after-start'
    asyncio.run(jobs.run(store, client, new['id'], translation_candidate, context_for))
    finished = store.get(new['id'])
    assert finished['retranslation']['status'] == 'completed'
    assert finished['retranslation']['completed'] == finished['retranslation']['total']
    assert all(model == 'new-model' and cache is False for model, cache in client.calls)
    assert finished['paragraphs'][1]['groups'] and finished['paragraphs'][1]['targetUnits']
    assert store.get(source['id']) == before and store.source(source) == original_bytes


def test_dirty_source_cannot_silently_lose_draft(tmp_path):
    store = Store(tmp_path/'projects'); source = store.create(fixture_doc(), 'paper.docx')
    source['paragraphs'][1].update(status='pending', zh='old', draftZh='new')
    with pytest.raises(StateError): RetranslationJobs().create(store, FakeClient(tmp_path), source)
    assert len(list((tmp_path/'projects').iterdir())) == 1


def test_pause_resume_and_recover(tmp_path):
    store = Store(tmp_path/'projects'); source = store.create(fixture_doc(), 'paper.docx')
    client = FakeClient(tmp_path); jobs = RetranslationJobs(); new = jobs.create(store, client, source)
    new['retranslation']['stopRequested'] = True; store.save(new)
    asyncio.run(jobs.run(store, client, new['id'], translation_candidate, context_for))
    paused = store.get(new['id']); assert paused['retranslation']['status'] == 'paused' and not client.calls
    jobs.resume(store, paused)
    asyncio.run(jobs.run(store, client, new['id'], translation_candidate, context_for))
    done = store.get(new['id']); assert done['retranslation']['status'] == 'completed'
    calls = len(client.calls); done['retranslation']['status'] = 'interrupted'; store.save(done); jobs.resume(store, done)
    asyncio.run(jobs.run(store, client, new['id'], translation_candidate, context_for))
    assert len(client.calls) == calls


def test_startup_marks_batch_interrupted(tmp_path, monkeypatch):
    import server.app as api
    store = Store(tmp_path/'projects'); source = store.create(fixture_doc(), 'paper.docx')
    jobs = RetranslationJobs(); new = jobs.create(store, FakeClient(tmp_path), source)
    new['paragraphs'][1]['status'] = 'running'; store.save(new)
    monkeypatch.setattr(api, 'DATA', tmp_path); monkeypatch.setattr(api, 'store', store)
    api.recover()
    recovered = store.get(new['id'])
    assert recovered['retranslation']['status'] == 'interrupted'
    assert recovered['paragraphs'][1]['status'] == 'untranslated'
