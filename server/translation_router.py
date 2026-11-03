"""Task boundary: machine translation supplies text; LLM only aligns that text."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import re
import time

from .documents import TOKEN, split_units
from .llm import ModelError
from .state import StateError, validate_links

VERSION = 'translation-router-v2'


async def translate(texts, source, target, config, credentials):
    # Imported at call time so old LLM-only projects have no optional boundary.
    from .translation_services import translate as service_translate
    return await service_translate(texts, source, target, config, credentials)


def public_translation(settings):
    """Only explicit non-secret service options enter saved jobs or cache keys."""
    value = settings.get('translation') or {'providerId': 'llm', 'providers': []}
    safe = {'providerId': value.get('providerId', 'llm'), 'providers': []}
    for provider in value.get('providers', []):
        safe['providers'].append({k: deepcopy(provider[k]) for k in
            ('id', 'kind', 'name', 'baseUrl', 'region', 'timeout',
             'maxRequestsPerSecond', 'maxCharsPerRequest', 'maxParagraphsPerRequest') if k in provider})
    return safe


class TranslationRouter:
    def __init__(self, client, data_dir):
        self.client, self.data_dir = client, Path(data_dir)

    def read_settings(self):
        return self.client.read_settings()

    def resolve(self, settings, task):
        return self.client.resolve(settings, task)

    def label(self, settings):
        selected = public_translation(settings)
        if selected['providerId'] == 'llm':
            return self.client.resolve(settings, 'translate_align')[1]['model']
        provider = next((p for p in selected['providers'] if p['id'] == selected['providerId']), None)
        if provider is None:
            raise ModelError('选中的翻译服务不存在，请重新配置翻译 API。')
        return provider.get('name') or provider['kind']

    async def generate(self, task, payload, settings=None, cache=True):
        if payload.get('translationPolicy') == 'skip_reference':
            raise ModelError('参考文献不参与翻译、映射或回写。')
        settings = settings or self.client.read_settings()
        if task == 'translate_align':
            source = payload.get('source_units', [])
            original = ''.join(u['text'] for u in source)
            if TOKEN.search(original) and not any(c.isalpha() for c in TOKEN.sub('', original)):
                return {'data': {'target_units': [
                    {'id': 'z' + str(i + 1), 'text': u['text'], 'source_ids': [u['id']]}
                    for i, u in enumerate(source)], 'unresolved': []}, 'meta': {
                    'task': task, 'model': 'Protected objects (identity)',
                    'alignmentMethod': 'protected-identity', 'seconds': 0, 'cached': False,
                    'translationService': {'id': 'protected-identity', 'kind': 'identity'},
                    'templateVersion': VERSION}}
        selected = public_translation(settings)
        if task != 'translate_align' or selected['providerId'] == 'llm':
            return await self.client.generate(task, payload, settings=settings, cache=cache)
        provider = next((p for p in selected['providers'] if p['id'] == selected['providerId']), None)
        if provider is None:
            raise ModelError('选中的翻译服务不存在，请重新配置翻译 API。')
        units = payload.get('source_units', [])
        text = ''.join(u['text'] for u in units)
        if not text.strip():
            raise ModelError('没有可翻译的文本。')
        # Credentials never form part of the request cache or returned metadata.
        llm_settings = {k: settings.get(k) for k in ('profiles', 'routes', 'glossary', 'style')}
        llm_settings['providers'] = [{k: p.get(k) for k in ('id', 'protocol', 'baseUrl', 'timeout')}
            for p in settings.get('providers', [])]
        signature = [VERSION, provider, 'en', 'zh', payload, llm_settings]
        key = sha256(json.dumps(signature, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        cache_dir = self.data_dir / 'translation-cache'; cache_dir.mkdir(parents=True, exist_ok=True)
        cached = cache_dir / (key + '.json')
        if cache and cached.exists():
            result = json.loads(cached.read_text('utf-8')); result['meta']['cached'] = True
            return result
        secret_file = self.data_dir / 'translation-secrets.json'
        secrets = json.loads(secret_file.read_text('utf-8-sig')) if secret_file.exists() else {}
        current_file = self.data_dir / 'translation-settings.json'
        if current_file.exists():
            current = json.loads(current_file.read_text('utf-8-sig'))
            latest = next((p for p in current.get('providers', []) if p.get('id') == provider['id']), None)
            if latest and any(latest.get(k) != provider.get(k) for k in ('kind', 'baseUrl', 'region')):
                # A pinned job must not send newly replaced credentials to its
                # former endpoint after this service ID is repurposed.
                raise ModelError('翻译服务地址或类型在任务启动后已更改；请使用新配置创建重译任务，当前草稿已保留。')
        credentials = secrets.get(provider['id'], {})
        started = time.time()
        # Do not expose Word field/image placeholders to translation engines.
        pieces = re.split('(' + TOKEN.pattern + ')', text)
        indices = [i for i, value in enumerate(pieces) if value.strip() and not TOKEN.fullmatch(value)]
        requests = [pieces[i].strip() for i in indices]
        if requests:
            translated = await translate(requests, 'en', 'zh', provider, credentials)
            if not isinstance(translated, list) or len(translated) != len(requests) or any(not isinstance(t, str) or not t.strip() or TOKEN.search(t) for t in translated):
                raise ModelError('翻译服务返回的文本数量或保护对象校验失败。')
            for index, result in zip(indices, translated):
                value = pieces[index]
                left = value[:len(value) - len(value.lstrip())]
                right = value[len(value.rstrip()):]
                pieces[index] = left + result.strip() + right
        chinese = ''.join(pieces)
        if TOKEN.findall(chinese) != TOKEN.findall(text):
            raise ModelError('翻译结果的保护对象校验失败。')
        aligned = await self.align_text(payload, chinese, settings=settings, cache=cache)
        result = {'data': aligned['data'], 'meta': {
            'task': task, 'model': provider.get('name') or provider['kind'],
            'translationService': {'id': provider['id'], 'kind': provider['kind']},
            **aligned['meta'], 'seconds': round(time.time() - started, 2),
            'cached': False, 'inputHash': key, 'templateVersion': VERSION,
        }}
        cached.write_text(json.dumps(result, ensure_ascii=False), 'utf-8')
        return result

    async def align_text(self, payload, chinese, settings=None, cache=True):
        """Re-align fixed machine text without another translation request."""
        if payload.get('translationPolicy') == 'skip_reference':
            raise ModelError('参考文献不参与翻译、映射或回写。')
        settings = settings or self.client.read_settings()
        units = payload.get('source_units', [])
        if TOKEN.findall(chinese) != TOKEN.findall(''.join(u['text'] for u in units)):
            raise ModelError('固定译文的保护对象与原文不一致。')
        targets = split_units(chinese, 'z')
        alignment_method, warning, mapping_meta = 'llm', '', None
        notes, failure = [], None
        try:
            mapped = await self.client.generate('repair_alignment', {
                'paragraph_id': payload.get('paragraph_id'), 'source_units': units,
                'target_units': targets, 'context': payload.get('context', {}),
                'protected_tokens': payload.get('protected_tokens', []),
            }, settings=settings, cache=cache)
            if mapped['data'].get('unresolved'):
                failure = {'category': 'unresolved', 'details': mapped['data']['unresolved']}
                raise StateError('映射有歧义')
            links = mapped['data'].get('links')
            validate_links(units, targets, links)
            mapping_meta = mapped.get('meta')
            notes = mapped['data'].get('notes', [])
        except (ModelError, StateError, KeyError, TypeError, ValueError) as exc:
            if failure is None:
                failure = {'category': 'model_error' if isinstance(exc, ModelError) else 'invalid_mapping',
                           'errorType': type(exc).__name__}
            if 'mapped' in locals():
                mapping_meta = mapped.get('meta')
            # Translation remains usable when mapping is unavailable, but never
            # claim a guessed one-to-one relationship or ask LLM to rewrite it.
            links = [{'source_ids': [u['id'] for u in units], 'target_ids': [u['id'] for u in targets]}]
            alignment_method = 'paragraph-fallback'
            warning = '句级映射暂不可用，当前按整段粗粒度对应；局部回写前请修复对应关系或明确修改范围。'
        output = []
        for unit in targets:
            source_ids = {sid for link in links if unit['id'] in link['target_ids'] for sid in link['source_ids']}
            output.append({'id': unit['id'], 'text': unit['text'],
                'source_ids': [u['id'] for u in units if u['id'] in source_ids]})
        return {'data': {'target_units': output, 'unresolved': []}, 'meta': {
            'alignmentMethod': alignment_method, 'alignmentWarning': warning,
            'alignmentNotes': notes, 'alignmentFailure': failure, 'alignmentModel': mapping_meta}}
