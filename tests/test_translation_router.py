import asyncio
from copy import deepcopy
import json
import pytest

import server.translation_router as module
from server.translation_router import TranslationRouter
from server.documents import split_units
from server.llm import ModelClient, ModelError
from server.app import translation_candidate
from server.state import impact, StateError


class Client:
    def __init__(self, root, fail=False):
        self.settings = ModelClient(root).read_settings()
        self.settings['translation'] = {'providerId': 'machine', 'providers': [
            {'id': 'machine', 'kind': 'volcengine', 'name': 'Machine test', 'baseUrl': 'https://example.test'}]}
        self.calls, self.fail = [], fail
    def read_settings(self): return deepcopy(self.settings)
    def resolve(self, settings, task): return settings['providers'][0], settings['profiles'][0]
    async def generate(self, task, payload, settings, cache):
        self.calls.append((task, deepcopy(payload)))
        if self.fail: raise ModelError('mapping service unavailable')
        assert task == 'repair_alignment'
        return {'data': {'links': [{'source_ids': [u['id'] for u in payload['source_units']],
            'target_ids': [u['id'] for u in payload['target_units']]}], 'unresolved': []},
            'meta': {'model': 'mapping-only'}}


def payload(text='First sentence. Second sentence.'):
    return {'paragraph_id': 'p1', 'source_units': split_units(text, 'p1_'), 'protected_tokens': []}


def test_machine_text_is_verbatim_and_llm_only_maps(tmp_path, monkeypatch):
    client = Client(tmp_path); calls = []
    async def translate(texts, source, target, provider, credentials):
        calls.append((texts, source, target, provider['id'], credentials))
        return ['第一句。第二句。']
    monkeypatch.setattr(module, 'translate', translate)
    (tmp_path/'translation-secrets.json').write_text(json.dumps({'machine': {'secretAccessKey': 'private-test-secret'}}))
    router = TranslationRouter(client, tmp_path)
    first = asyncio.run(router.generate('translate_align', payload()))
    assert ''.join(u['text'] for u in first['data']['target_units']) == '第一句。第二句。'
    assert client.calls[0][0] == 'repair_alignment'
    assert [u['text'] for u in client.calls[0][1]['target_units']] == ['第一句。', '第二句。']
    assert calls[0][:4] == (['First sentence. Second sentence.'], 'en', 'zh', 'machine')
    second = asyncio.run(router.generate('translate_align', payload()))
    assert second['meta']['cached'] and len(calls) == 1 and len(client.calls) == 1
    assert 'private-test-secret' not in ''.join(p.read_text('utf-8') for p in (tmp_path/'translation-cache').glob('*.json'))
    settings = client.read_settings(); settings['glossary'] = [{'en': 'first', 'zh': '一'}]
    asyncio.run(router.generate('translate_align', payload(), settings=settings))
    assert len(calls) == 2


def test_protected_objects_never_leave_translation_boundary(tmp_path, monkeypatch):
    client = Client(tmp_path); sent = []
    async def translate(texts, *args):
        sent.extend(texts); return ['前文', '后文']
    monkeypatch.setattr(module, 'translate', translate)
    p = payload('Before ⟦P000⟧ after.')
    result = asyncio.run(TranslationRouter(client, tmp_path).generate('translate_align', p))
    assert sent == ['Before', 'after.']
    assert ''.join(u['text'] for u in result['data']['target_units']) == '前文 ⟦P000⟧ 后文'


def test_protected_only_paragraph_keeps_identity_without_external_calls(tmp_path, monkeypatch):
    async def unexpected(*args):
        raise AssertionError('Protected-only paragraphs must not call translation')
    monkeypatch.setattr(module, 'translate', unexpected)
    client = Client(tmp_path)
    source = payload('⟦P000⟧ (1)')
    result = asyncio.run(TranslationRouter(client, tmp_path).generate('translate_align', source))
    assert not client.calls
    assert result['meta']['alignmentMethod'] == 'protected-identity'
    assert ''.join(u['text'] for u in result['data']['target_units']) == '⟦P000⟧ (1)'
    assert [u['source_ids'] for u in result['data']['target_units']] == [[u['id']] for u in source['source_units']]


def test_mapping_failure_keeps_machine_translation_and_marks_coarse_scope(tmp_path, monkeypatch):
    async def translate(*args): return ['第一句。第二句。']
    monkeypatch.setattr(module, 'translate', translate)
    result = asyncio.run(TranslationRouter(Client(tmp_path, True), tmp_path).generate('translate_align', payload()))
    assert result['meta']['alignmentMethod'] == 'paragraph-fallback'
    assert result['meta']['alignmentWarning']
    p = {'units': payload()['source_units'], 'en': 'First sentence. Second sentence.', 'protected': [], 'inserted': False}
    ready = translation_candidate(p, result['data']); ready['draftZh'] = '修改第一句。第二句。'
    with pytest.raises(StateError, match='多对多'): impact(ready)


def test_fixed_text_repair_accepts_known_merge_and_preserves_notes(tmp_path, monkeypatch):
    async def never_translate(*args): raise AssertionError('No MT during fixed-text repair')
    monkeypatch.setattr(module, 'translate', never_translate)
    class Merged(Client):
        async def generate(self, task, value, **kwargs):
            return {'data': {'links': [{'source_ids': [u['id'] for u in value['source_units']],
                'target_ids': [u['id'] for u in value['target_units']]}], 'unresolved': [],
                'notes': ['Two source sentences share one target unit.']}, 'meta': {'usage': {'total_tokens': 100}}}
    result = asyncio.run(TranslationRouter(Merged(tmp_path),tmp_path).align_text(payload(),'第一和第二句合并。'))
    assert result['meta']['alignmentMethod']=='llm'
    assert result['meta']['alignmentNotes']
    assert result['data']['target_units'][0]['source_ids']==['p1_s1','p1_s2']
    assert result['data']['target_units'][0]['text']=='第一和第二句合并。'


def test_genuine_unresolved_mapping_is_still_blocked_and_diagnosed(tmp_path):
    class Unresolved(Client):
        async def generate(self, *args, **kwargs):
            return {'data': {'links': [], 'unresolved': ['Second sentence is missing.']},
                    'meta': {'usage': {'total_tokens': 100}}}
    result=asyncio.run(TranslationRouter(Unresolved(tmp_path),tmp_path).align_text(payload(),'只有第一句。'))
    assert result['meta']['alignmentMethod']=='paragraph-fallback'
    assert result['meta']['alignmentFailure']=={'category':'unresolved','details':['Second sentence is missing.']}
    assert result['meta']['alignmentModel']['usage']['total_tokens']==100


def test_translation_errors_do_not_fallback_to_llm(tmp_path, monkeypatch):
    async def translate(*args): raise ModelError('quota exhausted')
    monkeypatch.setattr(module, 'translate', translate)
    client = Client(tmp_path)
    with pytest.raises(ModelError, match='quota'):
        asyncio.run(TranslationRouter(client, tmp_path).generate('translate_align', payload()))
    assert not client.calls


def test_pinned_service_cannot_send_replaced_credentials_to_old_endpoint(tmp_path, monkeypatch):
    client = Client(tmp_path); settings = client.read_settings(); called = []
    async def translate(*args): called.append(args); return ['翻译']
    monkeypatch.setattr(module, 'translate', translate)
    current = deepcopy(settings['translation']); current['providers'][0]['baseUrl'] = 'https://different.test'
    (tmp_path/'translation-settings.json').write_text(json.dumps(current))
    (tmp_path/'translation-secrets.json').write_text(json.dumps({'machine': {'apiKey': 'replacement-secret'}}))
    with pytest.raises(ModelError, match='任务启动后已更改'):
        asyncio.run(TranslationRouter(client, tmp_path).generate('translate_align', payload(), settings=settings))
    assert not called and not client.calls


def test_legacy_llm_mode_and_nontranslation_tasks_are_passthrough(tmp_path):
    class Passthrough(Client):
        async def generate(self, task, payload, settings, cache): return {'task': task, 'cache': cache}
    client = Passthrough(tmp_path); client.settings.pop('translation')
    router = TranslationRouter(client, tmp_path)
    assert asyncio.run(router.generate('translate_align', payload(), cache=False)) == {'task': 'translate_align', 'cache': False}
    assert asyncio.run(router.generate('rewrite_en', {}))['task'] == 'rewrite_en'


def test_full_retranslation_pins_machine_service_and_rebuilds_maps(tmp_path, monkeypatch):
    from io import BytesIO
    from docx import Document
    from server.retranslation import RetranslationJobs
    from server.state import Store
    from server.app import context_for
    document = Document(); document.add_paragraph('First sentence. Second sentence.')
    document.add_table(rows=1, cols=1).cell(0, 0).text = '42'
    stream = BytesIO(); document.save(stream)
    store = Store(tmp_path/'projects'); source = store.create(stream.getvalue(), 'source.docx')
    before = deepcopy(store.get(source['id']))
    client = Client(tmp_path); seen = []
    async def translate(texts, source, target, config, credentials):
        seen.append(config['id']); return ['第一句。第二句。']
    monkeypatch.setattr(module, 'translate', translate)
    router = TranslationRouter(client, tmp_path); jobs = RetranslationJobs()
    new = jobs.create(store, router, source)
    client.settings['translation']['providerId'] = 'changed-after-start'
    asyncio.run(jobs.run(store, router, new['id'], translation_candidate, context_for))
    finished = store.get(new['id'])
    assert finished['retranslation']['status'] == 'completed'
    assert seen == ['machine']  # numeric table cell did not hit MT or LLM
    assert finished['paragraphs'][0]['groups']
    assert finished['paragraphs'][0]['modelMeta']['cached'] is False
    assert all(task == 'repair_alignment' for task, _ in client.calls)
    assert store.get(source['id']) == before
