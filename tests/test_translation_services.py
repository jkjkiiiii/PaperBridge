import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import httpx
import pytest
import server.translation_services as service


@pytest.fixture(autouse=True)
def no_real_wait_for_protocol_fixtures(monkeypatch):
    # Rate admission itself has dedicated virtual-clock concurrency tests.
    class Immediate:
        async def acquire(self, key, limit): pass
    monkeypatch.setattr(service,'REQUEST_LIMITER',Immediate())


def provider(kind):
    row = next(x for x in service.CATALOG if x['kind'] == kind)
    return {'id':kind,'kind':kind,'name':row['name'],'baseUrl':row['baseUrl']}


def test_volcengine_fixed_signature_vector():
    body = b'{"TextList":["Hello"],"TargetLanguage":"zh"}'
    headers = service.volcengine_headers(body,'test-ak','test-sk',now=datetime(2026,11,3,tzinfo=timezone.utc))
    assert headers['x-date'] == '20261103T000000Z'
    assert headers['authorization'] == ('HMAC-SHA256 Credential=test-ak/20261103/cn-north-1/translate/request, '
        'SignedHeaders=content-type;host;x-content-sha256;x-date, '
        'Signature=40a45e4f0f322eaad5fd35d27844002f177a135e5727296584710694fb69f1e3')
    assert service.volcengine_headers(body+b' ','test-ak','test-sk',now=datetime(2026,11,3,tzinfo=timezone.utc))['authorization'] != headers['authorization']


@pytest.mark.parametrize('kind',['volcengine','deepl','azure','libretranslate'])
def test_provider_protocol_and_exact_order(monkeypatch,kind):
    seen = []
    real = httpx.AsyncClient
    def reply(request):
        seen.append(request)
        body = json.loads(request.content)
        if kind == 'volcengine':
            assert request.url.params['Action'] == 'TranslateText'
            assert 'HMAC-SHA256 Credential=' in request.headers['authorization']
            assert body['TextList'] == ['Hello.','World.']
            raw = {'TranslationList':[{'Translation':'你好。'},{'Translation':'世界。'}], 'ResponseMetadata':{'Error':None}}
        elif kind == 'deepl':
            assert request.url.path == '/v2/translate'
            assert request.headers['authorization'] == 'DeepL-Auth-Key fake-key'
            assert body['source_lang'] == 'EN' and body['target_lang'] == 'ZH'
            raw = {'translations':[{'text':'你好。'},{'text':'世界。'}]}
        elif kind == 'azure':
            assert request.url.params['to'] == 'zh-Hans'
            assert request.headers['Ocp-Apim-Subscription-Region'] == 'eastasia'
            assert body == [{'Text':'Hello.'},{'Text':'World.'}]
            raw = [{'translations':[{'text':'你好。'}]},{'translations':[{'text':'世界。'}]}]
        else:
            assert body['q'] == ['Hello.','World.'] and body['api_key'] == 'fake-key'
            raw = {'translatedText':['你好。','世界。']}
        return httpx.Response(200,json=raw)
    monkeypatch.setattr(service.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(reply),**kw))
    result=asyncio.run(service.translate(['Hello.','World.'],'en','zh',provider(kind),
        {'accessKeyId':'fake-ak','secretAccessKey':'fake-sk','apiKey':'fake-key','region':'eastasia'}))
    assert result == ['你好。','世界。'] and len(seen) == 1


def test_limits_and_no_billable_retry(monkeypatch):
    seen=[];real=httpx.AsyncClient
    def reply(r):
        seen.append(r)
        raise httpx.ReadTimeout('slow',request=r)
    monkeypatch.setattr(service.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(reply),**kw))
    with pytest.raises(service.TranslationServiceError,match='不会自动重发'):
        asyncio.run(service.translate(['hello'],'en','zh',provider('volcengine'),{'accessKeyId':'ak','secretAccessKey':'sk'}))
    assert len(seen)==1
    assert list(service.batches(['x'*3000,'x'*3000],16,5000)) == [['x'*3000],['x'*3000]]
    with pytest.raises(service.TranslationServiceError):list(service.batches(['x'*5001],16,5000))


def test_result_count_and_embedded_service_errors(monkeypatch):
    real=httpx.AsyncClient
    for raw,match in [({'TranslationList':[]},'不完整'),({'ResponseMetadata':{'Error':{'Code':'AccessDenied','Message':'sensitive request'}}},'AccessDenied')]:
        monkeypatch.setattr(service.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=raw)),**kw))
        with pytest.raises(service.TranslationServiceError,match=match) as exc:
            asyncio.run(service.translate(['hello'],'en','zh',provider('volcengine'),{'accessKeyId':'ak','secretAccessKey':'sk'}))
        assert 'sensitive request' not in str(exc.value)


def test_configuration_does_not_accept_plaintext_secret_or_unknown_selection():
    value={'providerId':'volcengine','providers':[provider('volcengine')]}
    service.validate_translation_settings(value)
    bad=deepcopy(value);bad['providers'][0]['secretAccessKey']='must-not-persist'
    with pytest.raises(service.TranslationServiceError,match='凭据'):service.validate_translation_settings(bad)
    bad=deepcopy(value);bad['providerId']='missing'
    with pytest.raises(service.TranslationServiceError):service.validate_translation_settings(bad)
    bad=deepcopy(value);bad['providers'][0]['baseUrl']='http://example.com'
    with pytest.raises(service.TranslationServiceError,match='官方'):service.validate_translation_settings(bad)
    assert all('freeTier' in item and item['docsUrl'].startswith('https://') for item in service.translation_catalog()['providers'])


def test_internal_long_paragraph_chunks_keep_input_count_and_order(monkeypatch):
    requests = []
    real = httpx.AsyncClient
    def reply(r):
        batch = json.loads(r.content)['TextList']
        requests.append(batch)
        assert len(batch) <= 16
        assert sum(map(len,batch)) <= 5000
        assert all(text.strip() for text in batch)
        # Identity response exposes any boundary loss/reordering in the planner.
        return httpx.Response(200,json={'TranslationList':[{'Translation':text} for text in batch]})
    monkeypatch.setattr(service.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(reply),**kw))
    texts = ['First short paragraph.', 'A complete scientific sentence. ' * 260,
             'noWhitespace' * 600, 'Final paragraph.', '', ' ' * 6000,
             'A sentence.' + ' ' * 5100]
    translated = asyncio.run(service.translate(texts,'en','zh',provider('volcengine'),{'accessKeyId':'ak','secretAccessKey':'sk'}))
    assert translated == texts
    assert len(translated) == len(texts)
    assert len(requests) > 1


def test_chunk_boundaries_and_trimmed_separator_restoration():
    text = 'First complete sentence. Another complete sentence. Last sentence.'
    chunks = service.split_translation_text(text,40)
    assert ''.join(chunks) == text
    assert chunks[0] == 'First complete sentence. '
    assert all(len(chunk) <= 40 for chunk in chunks)
    assert service.merge_translation_chunks(chunks,[chunk.strip() for chunk in chunks]) == text
    assert service.split_translation_text('x'*81,40) == ['x'*40,'x'*40,'x']
