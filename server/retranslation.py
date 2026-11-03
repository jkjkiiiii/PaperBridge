"""Resumable sequential translation into an independent project version."""
import asyncio
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
from .state import StateError, now
from .documents import DocumentError
from .llm import ModelError, ModelOutputError


class RetranslationJobs:
    def __init__(self):
        self.tasks = {}

    def create(self, store, client, source):
        if source.get('retranslation', {}).get('status') == 'running':
            raise StateError('请暂停当前全文重译后再创建其他重译版本。')
        # Strict export validates English baseline; drafts cannot silently vanish.
        if any(p.get('draftZh', '') != p.get('zh', '') for p in source['paragraphs'] if not p['deleted']):
            raise StateError('请先完成或撤销中文草稿，再从当前英文创建重译版本。')
        data = store.export(source)
        settings = deepcopy(client.read_settings())
        provider, profile = client.resolve(settings, 'translate_align')
        for item in settings.get('providers', []):
            item.pop('apiKey', None); item.pop('hasKey', None)
        name = Path(source['name']).stem + ' · 重译 ' + now().replace(':', '-')[:19] + '.docx'
        project = store.create(data, name)
        project['retranslation'] = {'status': 'running', 'sourceProjectId': source['id'],
            'model': profile['model'], 'settings': settings, 'started': now(),
            'total': len([p for p in project['paragraphs'] if p['en'].strip()]),
            'completed': 0, 'failed': 0, 'stopRequested': False}
        self.count(project)
        store.save(project)
        return project

    @staticmethod
    def count(project):
        batch = project['retranslation']
        relevant = [p for p in project['paragraphs'] if not p['deleted'] and p['en'].strip()]
        batch['completed'] = sum(p['status'] == 'ready' for p in relevant)
        batch['failed'] = sum(p['status'] == 'failed' for p in relevant)

    def launch(self, store, client, project, candidate, context):
        pid = project['id']
        if pid in self.tasks and not self.tasks[pid].done():
            raise StateError('全文重译正在执行。')
        self.tasks[pid] = asyncio.create_task(self.run(store, client, pid, candidate, context))
        self.tasks[pid].add_done_callback(lambda task: self.tasks.pop(pid, None))

    async def run(self, store, client, pid, candidate, context):
        try:
            project = store.get(pid)
            settings = deepcopy(project['retranslation']['settings'])
            for paragraph in project['paragraphs']:
                current = store.get(pid); batch = current['retranslation']
                if batch.get('stopRequested'):
                    batch['status'] = 'paused'; self.count(current); store.save(current); return
                live = store.paragraph(current, paragraph['id'])
                if live['deleted'] or not live['en'].strip() or live['status'] == 'ready': continue
                snapshot = deepcopy(live); revision = live['revision']; job = uuid4().hex
                payload = {'paragraph_id': live['id'], 'revision': revision,
                    'source_units': live['units'], 'protected_tokens': live['protected'],
                    'context': context(current, live)}
                live.update(status='running', error='', job=job); store.save(current)
                try:
                    for attempt in range(2):
                        try:
                            response = await client.generate('translate_align', payload, settings=settings, cache=False)
                            translated = candidate(snapshot, response['data']); break
                        except (StateError, ModelOutputError) as exc:
                            if attempt: raise
                            payload = {**payload, 'validation_error': str(exc),
                                'repair_instruction': 'Return a corrected complete translation within the original scope.'}
                    current = store.get(pid); live = store.paragraph(current, paragraph['id'])
                    if live['revision'] != revision or live.get('job') != job: continue
                    translated.update(revision=revision + 1, modelMeta=response['meta'])
                    current['paragraphs'][current['paragraphs'].index(live)] = translated
                    store.event(current, translated, 'translate_align', {'model': response['meta']})
                except (StateError, DocumentError, ModelError) as exc:
                    current = store.get(pid); live = store.paragraph(current, paragraph['id'])
                    if live['revision'] == revision and live.get('job') == job:
                        live.update(status='failed', error=str(exc))
                        current['revision'] += 1
                self.count(current); store.save(current)
            current = store.get(pid); self.count(current)
            current['retranslation']['status'] = 'completed' if current['retranslation']['completed'] == current['retranslation']['total'] else 'completed_with_errors'
            current['retranslation']['finished'] = now(); store.save(current)
        except asyncio.CancelledError:
            self.interrupt(store, pid)
            raise
        except Exception as exc:
            self.interrupt(store, pid, str(exc))

    def interrupt(self, store, pid, error='任务中断，可继续重译未完成段落。'):
        current = store.get(pid)
        for p in current['paragraphs']:
            if p['status'] == 'running': p.update(status='failed', error=error)
        current['retranslation'].update(status='interrupted', error=error)
        self.count(current); store.save(current)

    def resume(self, store, project):
        if project['retranslation']['status'] == 'running': raise StateError('全文重译正在执行。')
        project['retranslation'].update(status='running', stopRequested=False, error='')
        store.save(project)

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks: task.cancel()
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)
