import asyncio
import json
import httpx
import pytest
from scripts.run_translation_cost_experiment import instrument_http, CONTEXT
from server.llm import parse_json, ModelOutputError


def test_http_metering_precedes_output_validation_and_counts_retry(tmp_path):
    async def run():
        ledger={'requests':[],'translationRequests':[]}
        calls=0
        def handler(request):
            nonlocal calls
            calls+=1
            return httpx.Response(200,json={'model':'deepseek-flash',
                'choices':[{'message':{'content':'bad JSON' if calls==1 else '{"unresolved":[]}'},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':100,'prompt_cache_hit_tokens':20,'prompt_cache_miss_tokens':80,'completion_tokens':10,'total_tokens':110}})
        previous=instrument_http(ledger,tmp_path/'ledger.json','api.deepseek.com')
        marker=CONTEXT.set({'task':'repair_alignment','paragraphId':'p1'})
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                response=await client.post('https://api.deepseek.com/chat/completions',json={'model':'deepseek-flash','messages':[]})
                with pytest.raises(ModelOutputError):parse_json(response.json()['choices'][0]['message']['content'])
                response=await client.post('https://api.deepseek.com/chat/completions',json={'model':'deepseek-flash','messages':[]})
                assert parse_json(response.json()['choices'][0]['message']['content'])=={'unresolved':[]}
        finally:
            CONTEXT.reset(marker);httpx.AsyncClient=previous
        saved=json.loads((tmp_path/'ledger.json').read_text('utf-8'))
        assert len(saved['requests'])==2
        assert all(r['usage']['total_tokens']==110 and r['paragraphId']=='p1' for r in saved['requests'])
        assert 'messages' not in json.dumps(saved)
    asyncio.run(run())


def test_volc_metering_records_counts_not_text_or_headers(tmp_path):
    async def run():
        ledger={'requests':[],'translationRequests':[]}
        def handler(request):return httpx.Response(200,json={'TranslationList':[{'Translation':'中文'}]})
        previous=instrument_http(ledger,tmp_path/'ledger.json','api.deepseek.com')
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                await client.post('https://translate.volcengineapi.com/?Action=TranslateText&Version=2020-06-01',
                    json={'TextList':['Private text A','Private text B']},headers={'Authorization':'not-to-be-recorded'})
        finally:httpx.AsyncClient=previous
        assert ledger['translationRequests'][0]['textItems']==2
        assert ledger['translationRequests'][0]['sourceCharacters']==28
        serialized=json.dumps(ledger)
        assert 'Private text' not in serialized and 'Authorization' not in serialized and 'not-to-be-recorded' not in serialized
    asyncio.run(run())
