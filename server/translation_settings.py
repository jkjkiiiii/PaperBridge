"""Local configuration and secret boundary for dedicated translation services."""
from copy import deepcopy
import json
from urllib.parse import urlsplit
from .state import StateError, save_json

PUBLIC_KEYS = ('id', 'kind', 'name', 'baseUrl', 'region', 'timeout',
               'maxRequestsPerSecond', 'maxCharsPerRequest', 'maxParagraphsPerRequest')
SECRET_KEYS = ('accessKeyId', 'secretAccessKey', 'apiKey')


def read_translation_settings(folder):
    path = folder / 'translation-settings.json'
    result = json.loads(path.read_text('utf-8-sig')) if path.exists() else {'providerId': 'llm', 'providers': []}
    from .task_assignments import selected_translation_provider
    assigned = selected_translation_provider(folder)
    if assigned is not None: result['providerId'] = assigned
    return result


def read_translation_secrets(folder):
    path = folder / 'translation-secrets.json'
    return json.loads(path.read_text('utf-8-sig')) if path.exists() else {}


def public_settings(folder):
    result = deepcopy(read_translation_settings(folder))
    secrets = read_translation_secrets(folder)
    for provider in result['providers']:
        fields = [key for key in SECRET_KEYS if secrets.get(provider['id'], {}).get(key)]
        provider.update(credentialFields=fields, hasCredentials=bool(fields))
    return result


def save_translation_settings(folder, body):
    from .translation_services import validate_translation_settings
    if not isinstance(body, dict) or not isinstance(body.get('providers'), list):
        raise StateError('翻译服务配置必须包含 providers 列表。')
    from .task_assignments import selected_translation_provider
    assigned = selected_translation_provider(folder)
    safe = {'providerId': assigned if assigned is not None else body.get('providerId', 'llm'), 'providers': []}
    secrets = read_translation_secrets(folder)
    existing = {p['id']: p for p in read_translation_settings(folder)['providers']}
    for item in body['providers']:
        if not isinstance(item, dict): raise StateError('翻译服务必须为对象。')
        provider = {k: deepcopy(item[k]) for k in PUBLIC_KEYS if k in item}
        credentials = item.get('credentials', {})
        if not isinstance(credentials, dict) or any(k not in SECRET_KEYS or not isinstance(v, str) or len(v) > 4096 for k,v in credentials.items()):
            raise StateError('翻译凭据字段不合法。')
        old = existing.get(provider.get('id'))
        if old and (old.get('kind') != provider.get('kind') or urlsplit(old['baseUrl']).hostname != urlsplit(provider.get('baseUrl','')).hostname):
            # Never carry stored keys to another host or a different service kind.
            secrets.pop(provider['id'], None)
        current = secrets.setdefault(provider.get('id', ''), {})
        for key, value in credentials.items():
            if value.strip(): current[key] = value.strip()
        safe['providers'].append(provider)
    if safe['providerId'] != 'llm' and safe['providerId'] not in [p.get('id') for p in safe['providers']]:
        raise StateError('此翻译 API 正用于初始翻译，请先在任务分配中切换服务再删除配置。')
    validate_translation_settings(safe)
    save_json(folder / 'translation-secrets.json', secrets)
    save_json(folder / 'translation-settings.json', safe)
    return public_settings(folder)
