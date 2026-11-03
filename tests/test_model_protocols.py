import asyncio
from copy import deepcopy
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from server.llm import ModelClient, ModelOutputError, request_body, response_data
import server.app as api

RESULT = {'target_units':[{'id':'z1','text':'两个细胞。','source_ids':['s1']}], 'unresolved':[]}


@pytest.mark.parametrize('protocol',['openai_chat','openai_responses'])
def test_alignment_notes_valid_for_strict_schemas(protocol):
    from server.llm import SCHEMAS
    _,body=request_body({'protocol':protocol},{'model':'test','outputMode':'schema'},'repair_alignment','template','{}')
    schema=(body['text']['format'] if protocol=='openai_responses' else body['response_format']['json_schema'])['schema']
    assert set(schema['required'])==set(schema['properties'])
    assert 'notes' in schema['required']
    assert 'notes' not in SCHEMAS['repair_alignment']['required']

@pytest.mark.parametrize('protocol,path', [('openai_chat','/chat/completions'),('openai_responses','/responses'),('anthropic_messages','/messages')])
def test_protocol_generation(tmp_path, monkeypatch, protocol, path):
    client = ModelClient(tmp_path)
    settings = client.read_settings()
    settings['providers'][0]['protocol'] = protocol
    settings['profiles'][0].update(outputMode='schema', extraBody={})
    real = httpx.AsyncClient
    requests = []
    def respond(request):
        requests.append(request)
        body = json.loads(request.content)
        assert request.url.path.endswith(path)
        if protocol == 'openai_chat':
            assert body['response_format']['json_schema']['strict']
            value = {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(RESULT)}}]}
        elif protocol == 'openai_responses':
            assert body['text']['format']['type'] == 'json_schema'
            assert body['store'] is False
            assert 'max_output_tokens' in body and 'messages' not in body
            value = {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(RESULT)}]}]}
        else:
            assert request.headers['x-api-key'] == 'local'
            assert request.headers['anthropic-version'] == '2023-06-01'
            assert body['tool_choice']['name'] == 'submit_result'
            assert body['tools'][0]['input_schema']['additionalProperties'] is False
            value = {'stop_reason':'tool_use','content':[{'type':'tool_use','name':'submit_result','input':RESULT}]}
        return httpx.Response(200,json=value)
    monkeypatch.setattr('server.llm.httpx.AsyncClient',lambda **kw:real(transport=httpx.MockTransport(respond),**kw))
    result = asyncio.run(client.generate('translate_align',{'source_units':[{'id':'s1','text':'Two cells.'}]},settings=settings,cache=False))
    assert result['data'] == RESULT
    assert len(requests) == 1

@pytest.mark.parametrize('protocol,raw',[
 ('openai_responses',{'status':'incomplete','output':[]}),
 ('openai_responses',{'status':'completed','output':[{'type':'message','content':[{'type':'refusal','refusal':'No'}]}]}),
 ('anthropic_messages',{'stop_reason':'max_tokens','content':[]}),
 ('anthropic_messages',{'stop_reason':'tool_use','content':[{'type':'tool_use','name':'wrong','input':RESULT}]}),
])
def test_protocol_rejects_incomplete_or_wrong_contract(protocol,raw):
    with pytest.raises(ModelOutputError): response_data(protocol,raw)


def test_selected_profile_probe_leaves_routes_unchanged(tmp_path,monkeypatch):
    client = ModelClient(tmp_path)
    settings = client.read_settings()
    second = deepcopy(settings['profiles'][0]);second.update(id='second',model='selected')
    settings['profiles'].append(second)
    monkeypatch.setattr(api,'DATA',tmp_path)
    monkeypatch.setattr(api,'store',api.Store(tmp_path/'projects'))
    monkeypatch.setattr(api,'client',client)
    monkeypatch.setattr(client,'read_settings',lambda:deepcopy(settings))
    async def generate(task,payload,settings=None,cache=True):
        assert settings['routes']['translate_align'] == 'second'
        return {'data':RESULT,'meta':{'model':'selected'}}
    monkeypatch.setattr(client,'generate',generate)
    with TestClient(api.app) as c:
        response = c.post('/api/settings/test',json={'profileId':'second'})
        assert response.status_code == 200
        assert response.json()['meta']['model'] == 'selected'
        assert c.post('/api/settings/test',json={'profileId':'missing'}).status_code == 422
    assert settings['routes']['translate_align'] != 'second'


def test_settings_rejects_invalid_profile_budget():
    config = {
      'providers':[{'id':'p','baseUrl':'https://example.com/v1','protocol':'openai_chat','timeout':600}],
      'profiles':[{'id':'m','providerId':'p','model':'model','outputMode':'schema','maxTokens':200,'contextTokens':100}],
    }
    with pytest.raises(api.StateError): api.validate_model_settings(config)
