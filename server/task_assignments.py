"""One authoritative task routing choice, separate from service credentials."""
from copy import deepcopy
import json
from .state import StateError, save_json


def read_task_assignments(folder, config=None):
    path = folder / 'task-assignments.json'
    if path.exists():
        return json.loads(path.read_text('utf-8-sig'))
    if config is None:
        from .llm import ModelClient
        from .translation_settings import read_translation_settings
        config = ModelClient(folder)._read_llm_settings()
        config['translation'] = read_translation_settings(folder)
    routes = config['routes']
    translation = config.get('translation', {}).get('providerId', 'llm')
    return {'initialTranslation': {'kind': 'llm' if translation == 'llm' else 'translation_api',
            'id': routes['translate_align'] if translation == 'llm' else translation},
        'mappingModelId': routes['repair_alignment'], 'rewriteModelId': routes['rewrite_en']}


def validate_task_assignments(value, config):
    if not isinstance(value, dict) or not isinstance(value.get('initialTranslation'), dict):
        raise StateError('请为初始翻译、句子映射和英文回写选择服务。')
    initial = value['initialTranslation']
    models = {p['id'] for p in config['profiles']}
    services = {p['id'] for p in config.get('translation', {}).get('providers', [])}
    kind, identifier = initial.get('kind'), initial.get('id')
    if kind not in ('llm', 'translation_api') or not isinstance(identifier, str) or identifier not in (models if kind == 'llm' else services):
        raise StateError('初始翻译服务不存在，请先添加并保存相应模型或翻译 API。')
    for key, label in [('mappingModelId', '句子映射'), ('rewriteModelId', '英文回写')]:
        if not isinstance(value.get(key), str) or value[key] not in models:
            raise StateError(f'{label}只能选择已保存的通用 LLM。')
    return {'initialTranslation': {'kind': kind, 'id': identifier},
        'mappingModelId': value['mappingModelId'], 'rewriteModelId': value['rewriteModelId']}


def apply_task_assignments(folder, config):
    assignments = read_task_assignments(folder, config)
    routes = config['routes']
    initial = assignments['initialTranslation']
    config['translation']['providerId'] = initial['id'] if initial['kind'] == 'translation_api' else 'llm'
    if initial['kind'] == 'llm': routes['translate_align'] = initial['id']
    routes['repair_alignment'] = assignments['mappingModelId']
    routes['rewrite_en'] = assignments['rewriteModelId']
    return config


def save_task_assignments(folder, value, config):
    clean = validate_task_assignments(value, config)
    save_json(folder / 'task-assignments.json', clean)
    return clean


def validate_profile_removal(folder, config):
    if not (folder / 'task-assignments.json').exists(): return
    from .translation_settings import read_translation_settings
    proposed = deepcopy(config)
    proposed['translation'] = read_translation_settings(folder)
    validate_task_assignments(read_task_assignments(folder), proposed)


def selected_translation_provider(folder):
    path = folder / 'task-assignments.json'
    if not path.exists(): return None
    initial = read_task_assignments(folder)['initialTranslation']
    return initial['id'] if initial['kind'] == 'translation_api' else 'llm'
