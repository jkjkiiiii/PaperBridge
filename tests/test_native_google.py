import asyncio
from copy import deepcopy
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from server.llm import ModelClient, ModelError, ModelOutputError, request_body, response_data
import server.app as api

RESULT={'target_units':[{'id':'z1','text':'两个细胞。','source_ids':['s1']}],'unresolved':[]}


def test_native_google_generation(tmp_path,monkeypatch):
    client=ModelClient(tmp_path);settings=client.read_settings()
    settings['providers'][0].update(protocol='google_genai',baseUrl='https://generativelanguage.googleapis.com/v1beta')
    settings['profiles'][0].update(model='models/gemini-test',outputMode='schema',extraBody={})
    real=httpx.AsyncClient
    def respond(request):
        assert request.url.path=='/v1beta/models/gemini-test:generateContent'
        assert request.headers['x-goog-api-key']=='local'
        assert 'authorization' not in request.headers and 'key' not in request.url.params
        body=json.loads(request.content)
        assert body['systemInstruction']['parts'][0]['text']
        assert body['contents'][0]['role']=='user'
        assert 'model' not in body and 'stream' not in body and 'messages' not in body
        assert body['generationConfig']['responseMimeType']=='application/json'
        assert body['generationConfig']['responseJsonSchema']['additionalProperties'] is False
        return httpx.Response(200,json={'modelVersion':'gemini-test','candidates':[{'finishReason':'STOP','content':{'parts':[{'thought':True,'text':'hidden'},{'text':json.dumps(RESULT)}]}}],
            'usageMetadata':{'promptTokenCount':22,'candidatesTokenCount':31,'totalTokenCount':53,'thoughtsTokenCount':3}})
    monkeypatch.setattr('server.llm.httpx.AsyncClient',lambda **kw:real(transport=httpx.MockTransport(respond),**kw))
    result=asyncio.run(client.generate('translate_align',{'source_units':[{'id':'s1','text':'Two cells.'}]},settings=settings,cache=False))
    assert result['data']==RESULT
    assert result['meta']['usage']['completion_tokens_details']['reasoning_tokens']==3


@pytest.mark.parametrize('raw',[
    {'promptFeedback':{'blockReason':'SAFETY'}},
    {'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'{}'}]}}]},
    {'candidates':[]},
])
def test_google_rejects_incomplete(raw):
    with pytest.raises(ModelOutputError):response_data('google_genai',raw)


def test_google_contract_override_rejected():
    provider={'protocol':'google_genai'}
    profile={'model':'test','extraBody':{'generationConfig':{'responseJsonSchema':{}}}}
    with pytest.raises(ModelError):request_body(provider,profile,'translate_align','system','user')


def test_google_models_paginate_and_filter(tmp_path,monkeypatch):
    client=ModelClient(tmp_path);real=httpx.AsyncClient;calls=[]
    def respond(request):
        calls.append(request)
        assert request.headers['x-goog-api-key']=='draft-key'
        if not request.url.params.get('pageToken'):
            return httpx.Response(200,json={'models':[{'name':'models/embed','supportedGenerationMethods':['embedContent']}], 'nextPageToken':'next'})
        return httpx.Response(200,json={'models':[{'name':'models/gemini-test','supportedGenerationMethods':['generateContent']}]})
    monkeypatch.setattr('server.llm.httpx.AsyncClient',lambda **kw:real(transport=httpx.MockTransport(respond),**kw))
    result=asyncio.run(client.models({'id':'draft','apiKey':'draft-key','protocol':'google_genai','baseUrl':'https://example.com/v1beta'}))
    assert result==['gemini-test'] and len(calls)==2


def test_draft_discovery_does_not_leak_stored_key(tmp_path,monkeypatch):
    client=ModelClient(tmp_path);settings=client.read_settings()
    monkeypatch.setattr(api,'DATA',tmp_path);monkeypatch.setattr(api,'client',client);monkeypatch.setattr(api,'store',api.Store(tmp_path/'projects'))
    monkeypatch.setattr(client,'secret',lambda pid:'saved-secret')
    observed=[]
    async def models(provider):observed.append(provider);return ['one']
    monkeypatch.setattr(client,'models',models)
    with TestClient(api.app) as c:
        draft=deepcopy(settings['providers'][0]);draft['baseUrl']='https://different.example/v1'
        assert c.post('/api/settings/models',json={'provider':draft}).status_code==200
        assert observed[-1]['apiKey']=='local'
        draft['baseUrl']=settings['providers'][0]['baseUrl']
        assert c.post('/api/settings/models',json={'provider':draft}).status_code==200
        assert observed[-1]['apiKey']=='saved-secret'
        assert not (tmp_path/'settings.json').exists()
        catalog=c.get('/api/provider-catalog').json()
        assert next(x for x in catalog['providers'] if x['id']=='google')['protocol']=='google_genai'


def test_provider_scheme_protocol_and_availability_guard():
    provider={'id':'p','baseUrl':'https://example.com/v1','protocol':'openai_chat','presetId':'google'}
    with pytest.raises(api.StateError,match='协议不匹配'):
        api.validate_model_settings({'providers':[provider],'profiles':[]})
    provider.update(protocol='anthropic_messages',presetId='kimi-code')
    with pytest.raises(api.StateError,match='会员订阅'):
        api.validate_model_settings({'providers':[provider],'profiles':[]})
