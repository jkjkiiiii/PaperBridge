"""Dedicated machine-translation providers, independent of LLM wire protocols.

No unofficial web scraping, hidden provider fallback, or automatic billable retry.
Credentials are supplied by the local secret store, never by this catalogue.
"""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
import asyncio
from collections import deque
import hmac
import json
import re
import threading
import time
from urllib.parse import urlsplit
import httpx
from .llm import ModelError


class TranslationServiceError(ModelError):
    pass


# These are payload safety caps, not throughput promises for an account.
SERVICE_LIMITS = {'volcengine': (16, 5000), 'deepl': (50, 30000),
                  'azure': (1000, 50000), 'libretranslate': (100, 40000)}
REQUEST_DEFAULTS = {'maxRequestsPerSecond': 5, 'maxCharsPerRequest': 1800,
                    'maxParagraphsPerRequest': 8}


class RollingRequestLimiter:
    """One-process rolling-second admission, shared across async calls/loops.

    The tiny synchronous critical section only updates timestamps; waiting
    always uses an asynchronous sleep and never holds a lock.
    """
    def __init__(self, clock=None, sleep=None):
        self.clock = clock or time.monotonic
        self.sleep = sleep or asyncio.sleep
        self.lock = threading.Lock()
        self.windows = {}

    async def acquire(self, key, limit):
        while True:
            with self.lock:
                now = self.clock()
                window = self.windows.setdefault(key, deque())
                while window and window[0] <= now - 1:
                    window.popleft()
                if len(window) < limit:
                    window.append(now)
                    return
                delay = max(0.001, window[0] + 1 - now)
            await self.sleep(delay)


REQUEST_LIMITER = RollingRequestLimiter()


CATALOG = [
    {'kind':'volcengine','name':'火山引擎机器翻译','baseUrl':'https://translate.volcengineapi.com',
     'region':'cn-north-1','fields':[{'key':'accessKeyId','label':'Access Key ID','secret':True,'required':True},
       {'key':'secretAccessKey','label':'Secret Access Key','secret':True,'required':True}],
     'freeTier':'官方当前说明：文本翻译每月前 200 万字符免费；需开通服务，超额按量计费。',
     'docsUrl':'https://docs.volcengine.com/docs/machine-translation/text-translation-api?lang=zh',
     'pricingUrl':'https://docs.volcengine.com/docs/MachineTranslation/Productbilling?lang=zh'},
    {'kind':'deepl','name':'DeepL API','baseUrl':'https://api-free.deepl.com',
     'fields':[{'key':'apiKey','label':'DeepL API Key','secret':True,'required':True}],
     'freeTier':'旧 API Free 为每月 50 万字符且不再新购；新 API Developer 免费总量 100 万字符、不按月重置。按账户方案选择 Free 或 Pro 端点。',
     'docsUrl':'https://developers.deepl.com/api-reference/translate/request-translation',
     'pricingUrl':'https://support.deepl.com/hc/en-us/articles/360021200939-DeepL-API-plans'},
    {'kind':'azure','name':'Azure Translator','baseUrl':'https://api.cognitive.microsofttranslator.com',
     'fields':[{'key':'apiKey','label':'Translator Key','secret':True,'required':True},
       {'key':'region','label':'资源区域（按资源要求填写）','secret':False,'required':False}],
     'freeTier':'官方 F0 免费层每月 200 万字符；需创建 F0 资源，付费层不等同于免费层。',
     'docsUrl':'https://learn.microsoft.com/en-us/azure/ai-services/translator/text-translation/reference/v3/translate',
     'pricingUrl':'https://azure.microsoft.com/en-us/pricing/details/translator/'},
    {'kind':'libretranslate','name':'LibreTranslate（自托管）','baseUrl':'http://127.0.0.1:5000',
     'fields':[{'key':'apiKey','label':'API Key（自托管可选）','secret':True,'required':False}],
     'freeTier':'开源自托管可自行运行；服务器和模型有资源成本，公共实例不保证免费或可用。',
     'docsUrl':'https://docs.libretranslate.com/api/operations/translate/',
     'pricingUrl':'https://docs.libretranslate.com/guides/installation/'},
]


def translation_catalog():
    return {'providers': CATALOG, 'checkedAt':'2026-11-03',
            'notes':'免费额度和可开通资格以服务商及当前账户为准；专用翻译与 LLM 映射调用分别计费。'}


def validate_translation_settings(value):
    if not isinstance(value, dict) or not isinstance(value.get('providers', []), list):
        raise TranslationServiceError('翻译配置必须包含服务列表')
    rows = value.get('providers', [])
    ids = []
    for p in rows:
        if not isinstance(p, dict) or not isinstance(p.get('id'), str) or not p['id'] or p['id'] == 'llm':
            raise TranslationServiceError('翻译服务 ID 无效')
        ids.append(p['id'])
        if p.get('kind') not in {x['kind'] for x in CATALOG}:
            raise TranslationServiceError('不支持的专用翻译服务')
        url = urlsplit(p.get('baseUrl', ''))
        if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise TranslationServiceError('翻译服务地址需为有效 HTTP(S) 基础地址，不能包含凭据或查询参数')
        if p['kind'] == 'volcengine' and (url.hostname != 'translate.volcengineapi.com' or url.scheme != 'https' or url.path not in ('','/')):
            raise TranslationServiceError('火山翻译签名服务需使用官方 HTTPS 地址')
        timeout = p.get('timeout',60)
        if isinstance(timeout, bool) or not isinstance(timeout,(int,float)) or not 1 <= timeout <= 600:
            raise TranslationServiceError('翻译等待时间需为 1 至 600 秒')
        count_cap, char_cap = SERVICE_LIMITS[p['kind']]
        for key, cap in (('maxRequestsPerSecond',100),('maxCharsPerRequest',char_cap),
                         ('maxParagraphsPerRequest',count_cap)):
            selected = p.get(key,REQUEST_DEFAULTS[key])
            if isinstance(selected,bool) or not isinstance(selected,int) or not 1 <= selected <= cap:
                raise TranslationServiceError(f'{key} 需为 1 至 {cap} 的整数')
        # Public configuration cannot accidentally persist plaintext credentials.
        if any(k in p for k in ('accessKeyId','secretAccessKey','apiKey','credentials')):
            raise TranslationServiceError('翻译凭据必须通过独立凭据字段保存')
    if len(set(ids)) != len(ids): raise TranslationServiceError('翻译服务 ID 不能重复')
    if value.get('providerId','llm') != 'llm' and value['providerId'] not in ids:
        raise TranslationServiceError('当前翻译服务不存在')


def volcengine_headers(body: bytes, access_key: str, secret_key: str,
                      region='cn-north-1', now=None):
    now = now or datetime.now(timezone.utc)
    stamp = now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    date = stamp[:8]
    payload_hash = sha256(body).hexdigest()
    headers = {'content-type':'application/json', 'host':'translate.volcengineapi.com',
               'x-content-sha256':payload_hash,'x-date':stamp}
    signed = ';'.join(sorted(headers))
    canonical_headers = ''.join(f'{key}:{headers[key]}\n' for key in sorted(headers))
    canonical = '\n'.join(['POST','/','Action=TranslateText&Version=2020-06-01',canonical_headers,signed,payload_hash])
    scope = f'{date}/{region}/translate/request'
    string_to_sign = '\n'.join(['HMAC-SHA256',stamp,scope,sha256(canonical.encode()).hexdigest()])
    key = secret_key.encode()
    for part in (date,region,'translate','request'):
        key = hmac.new(key,part.encode(),sha256).digest()
    signature = hmac.new(key,string_to_sign.encode(),sha256).hexdigest()
    headers['authorization'] = f'HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={signed}, Signature={signature}'
    return headers


def batches(texts, count, characters):
    current, size = [], 0
    for text in texts:
        if len(text) > characters:
            raise TranslationServiceError('内部翻译分片超过服务请求限制')
        if current and (len(current) >= count or size + len(text) > characters):
            yield current
            current, size = [], 0
        current.append(text); size += len(text)
    if current: yield current


def split_translation_text(text, limit):
    """Split API payload only, never the document paragraph or its stable ID.

    Prefer the last sentence boundary, then whitespace. A single oversized token
    must use a code-point boundary to obey the upstream hard request limit.
    Concatenating the chunks reconstructs the input exactly.
    """
    chunks = []
    while len(text) > limit:
        window = text[:limit]
        sentence = list(re.finditer(r'[.!?。！？][\"\'”’\)\]]*(?:\s+|(?=[\u3400-\u9fff])|$)', window))
        boundary = sentence[-1].end() if sentence else 0
        # Do not emit a tiny sentence and leave most of a payload unused.
        if boundary < limit // 2:
            spaces = list(re.finditer(r'\s+', window))
            boundary = spaces[-1].end() if spaces else limit
        chunks.append(text[:boundary])
        text = text[boundary:]
    if text: chunks.append(text)
    return chunks


def merge_translation_chunks(source_chunks, translated_chunks):
    result = ''
    for index, value in enumerate(translated_chunks):
        if index and result and value and not result[-1].isspace() and not value[0].isspace():
            # Most services trim boundary whitespace. Preserve an original
            # separator so Latin-language outputs cannot glue adjacent words.
            separator = re.search(r'\s+$', source_chunks[index - 1])
            if separator: result += separator.group()
        result += value
    return result


async def translate(texts, source, target, config, credentials):
    if not isinstance(texts,list) or not all(isinstance(t,str) for t in texts):
        raise TranslationServiceError('待翻译文本必须为字符串列表')
    if not texts: return []
    validate_translation_settings({'providerId':config.get('id'), 'providers':[config]})
    kind = config['kind']; credentials = credentials or {}
    required = ('accessKeyId','secretAccessKey') if kind == 'volcengine' else (() if kind == 'libretranslate' else ('apiKey',))
    if any(not isinstance(credentials.get(k),str) or not credentials[k].strip() for k in required):
        raise TranslationServiceError('此翻译服务缺少必要凭据，请在翻译服务设置中填写')
    base = config['baseUrl'].rstrip('/')
    count_cap, char_cap = SERVICE_LIMITS[kind]
    size = (min(config.get('maxParagraphsPerRequest',8),count_cap),
            min(config.get('maxCharsPerRequest',1800),char_cap))
    request_rate = config.get('maxRequestsPerSecond',5)
    limiter_key = (kind,config['id'],base)
    plan = [split_translation_text(text, size[1]) if text.strip() else [] for text in texts]
    flattened = [chunk for chunks in plan for chunk in chunks if chunk.strip()]
    result = []
    timeout = httpx.Timeout(connect=10, read=config.get('timeout',60),write=30,pool=10)
    async with httpx.AsyncClient(trust_env=False,timeout=timeout) as client:
        for batch in batches(flattened,*size):
            headers = {'Content-Type':'application/json'}
            params = None
            if kind == 'volcengine':
                data = {'TargetLanguage':target,'TextList':batch}
                if source and source != 'auto': data['SourceLanguage'] = source
                body = json.dumps(data,ensure_ascii=False,separators=(',',':')).encode()
                headers = volcengine_headers(body,credentials['accessKeyId'],credentials['secretAccessKey'],config.get('region','cn-north-1'))
                url = base + '/?Action=TranslateText&Version=2020-06-01'
            elif kind == 'deepl':
                data = {'text':batch,'target_lang':target.upper()}
                if source and source != 'auto': data['source_lang'] = source.upper()
                body = json.dumps(data,ensure_ascii=False).encode()
                headers['Authorization'] = 'DeepL-Auth-Key ' + credentials['apiKey']
                url = base + '/v2/translate'
            elif kind == 'azure':
                body = json.dumps([{'Text':t} for t in batch],ensure_ascii=False).encode()
                params = {'api-version':'3.0','to':'zh-Hans' if target == 'zh' else target}
                if source and source != 'auto': params['from'] = source
                headers['Ocp-Apim-Subscription-Key'] = credentials['apiKey']
                region = credentials.get('region') or config.get('region')
                if region: headers['Ocp-Apim-Subscription-Region'] = region
                url = base + '/translate'
            else:
                data = {'q':batch,'source':source or 'auto','target':target,'format':'text'}
                if credentials.get('apiKey'): data['api_key'] = credentials['apiKey']
                body = json.dumps(data,ensure_ascii=False).encode()
                url = base + '/translate'
            try:
                await REQUEST_LIMITER.acquire(limiter_key,request_rate)
                response = await client.post(url,headers=headers,params=params,content=body)
            except httpx.ReadTimeout as exc:
                raise TranslationServiceError('等待翻译服务超时；本次不会自动重发，避免重复计费，请稍后重试') from exc
            except (httpx.HTTPError, OSError) as exc:
                raise TranslationServiceError('翻译服务连接或传输失败；未切换到其他服务，原文与草稿已保留') from exc
            if response.status_code >= 400:
                raise TranslationServiceError(f'翻译服务 HTTP {response.status_code}；请检查凭据、开通状态、区域和额度，不会自动转发其他服务')
            try:
                raw = response.json()
                if kind == 'volcengine':
                    if raw.get('ResponseMetadata',{}).get('Error'):
                        code = str(raw['ResponseMetadata']['Error'].get('Code','unknown'))[:80]
                        raise TranslationServiceError(f'火山翻译返回错误代码 {code}；请检查权限、开通状态与额度')
                    values = [v['Translation'] for v in raw['TranslationList']]
                elif kind == 'deepl': values = [v['text'] for v in raw['translations']]
                elif kind == 'azure': values = [v['translations'][0]['text'] for v in raw]
                else:
                    values = raw['translatedText']
                    if isinstance(values,str): values = [values]
                if not isinstance(values,list) or len(values) != len(batch) or not all(isinstance(x,str) and (x.strip() or not before.strip()) for x,before in zip(values,batch)):
                    raise ValueError('result shape')
            except (ValueError,KeyError,IndexError,TypeError,AttributeError) as exc:
                if isinstance(exc,TranslationServiceError): raise
                raise TranslationServiceError('翻译服务返回不完整或不兼容的结果，未提交译文') from exc
            result.extend(values)
    restored, cursor = [], 0
    for original, chunks in zip(texts, plan):
        values = []
        for chunk in chunks:
            if chunk.strip():
                values.append(result[cursor]); cursor += 1
            else: values.append(chunk)
        restored.append(merge_translation_chunks(chunks, values) if chunks else original)
    return restored
