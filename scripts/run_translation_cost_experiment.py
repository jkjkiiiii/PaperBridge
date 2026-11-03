"""Run an isolated, resumable MT + DeepSeek mapping experiment with HTTP usage.

Full source documents, translated text and the ledger remain under .data by
default. This script never changes global task assignments or account settings.
"""
from __future__ import annotations
import argparse
import asyncio
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import httpx
from server.app import translation_candidate, context_for
from server.llm import ModelClient
from server.reference_policy import is_skipped_reference
from server.retranslation import RetranslationJobs
from server.state import Store, save_json
from server.translation_router import TranslationRouter
from server.usage_cost import reconcile_usage, markdown_report

CONTEXT=ContextVar('experiment-call',default={})


def utc_now():return datetime.now(timezone.utc).isoformat()


class ExperimentClient(ModelClient):
    def __init__(self,data_dir,config):
        super().__init__(data_dir);self.config=deepcopy(config)
    def read_settings(self):return deepcopy(self.config)
    async def generate(self,task,payload,**kwargs):
        token=CONTEXT.set({'task':task,'paragraphId':payload.get('paragraph_id')})
        try:return await super().generate(task,payload,**kwargs)
        finally:CONTEXT.reset(token)


class ExperimentRouter(TranslationRouter):
    async def generate(self,task,payload,**kwargs):
        token=CONTEXT.set({'task':task,'paragraphId':payload.get('paragraph_id')})
        try:return await super().generate(task,payload,**kwargs)
        finally:CONTEXT.reset(token)


def instrument_http(ledger,ledger_path,llm_host):
    """Capture usage before any model JSON/mapping validation, including retries."""
    base=httpx.AsyncClient
    def flush():save_json(ledger_path,ledger)
    async def request_hook(request):
        if request.method!='POST':return
        try:body=json.loads(request.content)
        except (ValueError,TypeError):body={}
        if not isinstance(body,dict):body={}
        if request.url.host==llm_host and request.url.path.endswith('/chat/completions'):
            collection='requests'
            row={'requestId':uuid4().hex,**CONTEXT.get(),'startedAt':utc_now(),
                 'requestedModel':body.get('model'),'model':body.get('model'),
                 'requestBodyChars':len(request.content.decode('utf-8')),
                 'statusCode':None,'usage':None}
        elif request.url.host=='translate.volcengineapi.com' and request.url.params.get('Action')=='TranslateText':
            collection='translationRequests'
            texts=body.get('TextList',[])
            row={'requestId':uuid4().hex,**CONTEXT.get(),'startedAt':utc_now(),
                 'service':'volcengine','textItems':len(texts),
                 'sourceCharacters':sum(len(t) for t in texts),'statusCode':None}
        else:return
        ledger.setdefault(collection,[]).append(row)
        request.extensions['experimentRow']=(collection,len(ledger[collection])-1)
        request.extensions['experimentPerf']=time.monotonic()
        flush()
    async def response_hook(response):
        location=response.request.extensions.get('experimentRow')
        if location is None:return
        await response.aread()
        collection,index=location;row=ledger[collection][index]
        row.update(statusCode=response.status_code,finishedAt=utc_now(),
                   seconds=round(time.monotonic()-response.request.extensions['experimentPerf'],3))
        try:raw=response.json()
        except ValueError:raw={}
        if not isinstance(raw,dict):raw={}
        if collection=='requests':
            row['usage']=raw.get('usage');row['model']=raw.get('model',row.get('requestedModel'))
            choices=raw.get('choices') or []
            if choices:row['finishReason']=choices[0].get('finish_reason')
        elif raw.get('ResponseMetadata',{}).get('Error'):
            row['serviceErrorCode']=raw['ResponseMetadata']['Error'].get('Code')
        flush()
    class MeteredClient(base):
        def __init__(self,*args,**kwargs):
            original=kwargs.pop('event_hooks',{}) or {}
            hooks={name:list(values) for name,values in original.items()}
            hooks.setdefault('request',[]).append(request_hook)
            hooks.setdefault('response',[]).append(response_hook)
            super().__init__(*args,event_hooks=hooks,**kwargs)
    httpx.AsyncClient=MeteredClient
    return base


def balance_snapshot(client,provider):
    try:
        with httpx.Client(trust_env=False,timeout=20) as transport:
            result=transport.get(provider['baseUrl'].rstrip('/')+'/user/balance',headers=client.headers(provider))
        return {'capturedAt':utc_now(),'statusCode':result.status_code,
                'balance':result.json() if result.is_success else None}
    except Exception as exc:return {'capturedAt':utc_now(),'errorType':type(exc).__name__}


def balance_delta(before, after):
    """Account-wide balance movement is supporting evidence, not attribution."""
    def values(snapshot):
        output={}
        for row in (snapshot.get('balance') or {}).get('balance_infos',[]):
            try:output[row['currency']]=Decimal(str(row['total_balance']))
            except (KeyError,InvalidOperation):continue
        return output
    a,b=values(before),values(after)
    return {'currencyDeltas':{currency:str(a[currency]-b[currency]) for currency in a.keys()&b.keys()},
        'interpretation':'Account-wide before-minus-after balance; concurrent usage, credits and provider billing timing prevent treating this alone as the experiment invoice.'}


async def run(args):
    out=args.output_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    data=args.data_dir.resolve();store=Store(data/'projects');base_client=ModelClient(data)
    state_file=out/'run-state.json';ledger_file=out/'usage-ledger.json'
    if args.resume:
        state=json.loads(state_file.read_text('utf-8'))
        ledger=json.loads(ledger_file.read_text('utf-8'))
        project=store.get(state['projectId']);config=deepcopy(project['retranslation']['settings'])
    else:
        if state_file.exists():raise ValueError('Output already contains a run. Use --resume or a new directory.')
        config=base_client.read_settings()
        profile=next((p for p in config['profiles'] if p['id']==args.model_profile),None)
        if profile is None:raise ValueError('Requested model profile does not exist')
        provider=next(p for p in config['providers'] if p['id']==profile['providerId'])
        if urlsplit(provider['baseUrl']).hostname!='api.deepseek.com':raise ValueError('This measured experiment requires the official DeepSeek endpoint')
        config['routes']={task:profile['id'] for task in ('translate_align','rewrite_en','repair_alignment')}
        profile['contextTokens']=max(profile.get('contextTokens',0),args.context_tokens)
        profile['maxTokens']=args.max_tokens
        config['translation']['providerId']=args.translation_service
        source=args.source.resolve().read_bytes()
        original=store.create(source,args.source.name)
        client=ExperimentClient(data,config);router=ExperimentRouter(client,data)
        project=RetranslationJobs().create(store,router,original)
        state={'sourceProjectId':original['id'],'projectId':project['id'],'source':str(args.source.resolve()),
               'sourceSha256':sha256(source).hexdigest(),'startedAt':utc_now()}
        save_json(state_file,state)
        ledger={'context':{'sourceSha256':state['sourceSha256'],'scope':'Dedicated MT Chinese translation plus fixed-text DeepSeek sentence mapping; no editing rewrite calls.',
                           'referencePolicy':'References omitted from translation and mapping.'},'requests':[],'translationRequests':[]}
        save_json(ledger_file,ledger)
    client=ExperimentClient(data,config);router=ExperimentRouter(client,data)
    provider,profile=client.resolve(config,'repair_alignment')
    if urlsplit(provider['baseUrl']).hostname!='api.deepseek.com':raise ValueError('Pinned provider is not official DeepSeek')
    print(json.dumps({'projectId':project['id'],'model':profile['model'],'status':'starting'},ensure_ascii=True),flush=True)
    if not args.resume:save_json(out/'balance-before.json',balance_snapshot(client,provider))
    else:
        project['retranslation'].update(status='running',stopRequested=False,error='')
        store.save(project)
    previous=instrument_http(ledger,ledger_file,'api.deepseek.com')
    jobs=RetranslationJobs()
    async def progress():
        last=None
        while True:
            current=store.get(project['id']);batch=current['retranslation']
            marker=(batch['completed'],batch['failed'],batch['status'])
            if marker!=last:
                print(json.dumps({'projectId':project['id'],'status':batch['status'],'completed':batch['completed'],'failed':batch['failed'],'total':batch['total'],'skipped':batch.get('skipped',0)},ensure_ascii=True),flush=True);last=marker
            await asyncio.sleep(2)
    reporter=asyncio.create_task(progress())
    try:await jobs.run(store,router,project['id'],translation_candidate,context_for)
    finally:
        reporter.cancel();await asyncio.gather(reporter,return_exceptions=True)
        httpx.AsyncClient=previous
        save_json(ledger_file,ledger)
    balance_after=balance_snapshot(client,provider)
    save_json(out/'balance-after.json',balance_after)
    final=store.get(project['id']);paragraphs=final['paragraphs']
    skipped=[p for p in paragraphs if is_skipped_reference(p) and not p['deleted']]
    skipped_ids={p['id'] for p in skipped}
    leaked=[r['paragraphId'] for kind in ('requests','translationRequests') for r in ledger[kind] if r.get('paragraphId') in skipped_ids]
    summary={'projectId':project['id'],'sourceProjectId':state['sourceProjectId'],'sourceSha256':state['sourceSha256'],
        'status':final['retranslation']['status'],'batch':{k:final['retranslation'][k] for k in ('total','completed','failed','skipped') if k in final['retranslation']},
        'paragraphs':len(paragraphs),'skippedReferenceParagraphs':len(skipped),'skippedReferenceCharacters':sum(len(p['en']) for p in skipped),
        'bodyCharacters':sum(len(p['en']) for p in paragraphs if not p['deleted'] and not is_skipped_reference(p)),
        'referenceRequestsFound':leaked,'machineTranslationRequests':len(ledger['translationRequests']),
        'machineTranslationCharacters':sum(r['sourceCharacters'] for r in ledger['translationRequests']),
        'mappingFallbackParagraphs':[p['id'] for p in paragraphs if p.get('modelMeta',{}).get('alignmentMethod')=='paragraph-fallback'],
        'failedParagraphs':[{'id':p['id'],'error':p.get('error','')} for p in paragraphs if p['status']=='failed'],
        'allNonReferenceReady':all(p['status']=='ready' for p in paragraphs if not p['deleted'] and p['en'].strip() and not is_skipped_reference(p)),
        'finishedAt':utc_now()}
    before_file=out/'balance-before.json'
    if before_file.exists():summary['balanceMovement']=balance_delta(json.loads(before_file.read_text('utf-8')),balance_after)
    save_json(out/'experiment-summary.json',summary)
    report=reconcile_usage(ledger,args.holiday)
    save_json(out/'cost-report.json',report)
    (out/'cost-report.md').write_text(markdown_report(report),'utf-8')
    if summary['allNonReferenceReady']:
        (out/'attention-translated-project.json').write_text(json.dumps(final,ensure_ascii=False,indent=2),'utf-8')
        (out/'attention-current-english.docx').write_bytes(store.export(final))
    print(json.dumps({k:summary[k] for k in ('projectId','status','paragraphs','skippedReferenceParagraphs','referenceRequestsFound','allNonReferenceReady')},ensure_ascii=True),flush=True)
    print(json.dumps({k:report[k] for k in ('requestCount','totals','rmbAtPublishedRates','costCoverageComplete')},ensure_ascii=True),flush=True)
    if leaked:raise RuntimeError('Reference requests found in ledger')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--model-profile',required=True)
    parser.add_argument('--translation-service',required=True)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'.data/attention-cost-experiment')
    parser.add_argument('--data-dir',type=Path,default=ROOT/'.data')
    parser.add_argument('--context-tokens',type=int,default=64000)
    parser.add_argument('--max-tokens',type=int,default=8192)
    parser.add_argument('--holiday',action='append',default=[])
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    asyncio.run(run(args))


if __name__=='__main__':main()
