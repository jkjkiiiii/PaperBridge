import asyncio
from copy import deepcopy
import json
import httpx
import pytest
import server.translation_services as services
from server.translation_settings import save_translation_settings, public_settings
from server.translation_router import public_translation
from server.retranslation import RetranslationJobs
from server.state import Store
from server.llm import ModelClient
from test_documents import fixture_doc


def config():
    return {'id':'throttled','kind':'volcengine','name':'Volc',
            'baseUrl':'https://translate.volcengineapi.com',
            'maxRequestsPerSecond':5,'maxCharsPerRequest':1800,'maxParagraphsPerRequest':8}


def test_controls_persist_and_pin_without_credentials(tmp_path):
    provider = config()
    knobs = {key:provider[key] for key in services.REQUEST_DEFAULTS}
    saved = save_translation_settings(tmp_path, {'providerId':provider['id'],'providers':[
        {**provider,'credentials':{'accessKeyId':'test-ak','secretAccessKey':'test-sk'}}]})
    assert all(saved['providers'][0][key] == value for key,value in knobs.items())
    source = Store(tmp_path/'projects')
    document = source.create(fixture_doc(),'controls.docx')
    client = ModelClient(tmp_path)
    job = RetranslationJobs().create(source,client,document)
    pinned = job['retranslation']['settings']['translation']['providers'][0]
    assert all(pinned[key] == value for key,value in knobs.items())
    assert 'test-sk' not in json.dumps(job)
    changed = public_settings(tmp_path)
    changed['providers'][0]['maxCharsPerRequest'] = 100
    save_translation_settings(tmp_path,changed)
    assert pinned['maxCharsPerRequest'] == 1800
    assert public_translation({'translation':saved})['providers'][0]['maxParagraphsPerRequest'] == 8


@pytest.mark.parametrize('key,value', [('maxRequestsPerSecond',0),('maxRequestsPerSecond',True),
    ('maxRequestsPerSecond',1.5),('maxCharsPerRequest',5001),('maxParagraphsPerRequest',17)])
def test_invalid_volc_controls_rejected(key,value):
    provider = config(); provider[key] = value
    with pytest.raises(services.TranslationServiceError):
        services.validate_translation_settings({'providerId':provider['id'],'providers':[provider]})


def test_rolling_rate_limit_shared_between_concurrent_calls_and_provider_isolation():
    clock = [0.0]
    waits = []
    async def sleep(delay):
        waits.append(delay); clock[0] += delay
        await asyncio.sleep(0)
    limiter = services.RollingRequestLimiter(clock=lambda:clock[0],sleep=sleep)
    starts = []
    async def call():
        await limiter.acquire('same-provider',2)
        starts.append(clock[0])
    async def run():
        await asyncio.gather(*(call() for _ in range(8)))
        before = clock[0]
        await limiter.acquire('different-provider',2)
        assert clock[0] == before
    asyncio.run(run())
    assert len(starts) == 8 and waits
    for start in starts:
        assert sum(start <= stamp < start + 1 for stamp in starts) <= 2


def test_configured_payload_caps_split_without_changing_paragraph_count(monkeypatch):
    requests, admissions = [], []
    real = httpx.AsyncClient
    class Recording:
        async def acquire(self,key,limit): admissions.append((key,limit))
    monkeypatch.setattr(services,'REQUEST_LIMITER',Recording())
    def respond(request):
        texts = json.loads(request.content)['TextList']
        requests.append(texts)
        assert len(texts) <= 2 and sum(map(len,texts)) <= 32
        return httpx.Response(200,json={'TranslationList':[{'Translation':text} for text in texts]})
    monkeypatch.setattr(services.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(respond),**kw))
    provider = config(); provider.update(maxCharsPerRequest=32,maxParagraphsPerRequest=2)
    texts = ['First sentence. Another sentence. ' * 4,'Short.','Last.']
    result = asyncio.run(services.translate(texts,'en','zh',provider,{'accessKeyId':'ak','secretAccessKey':'sk'}))
    assert result == texts and len(requests) > 1
    assert len(admissions) == len(requests) and all(rate == 5 for _,rate in admissions)
