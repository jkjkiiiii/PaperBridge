from __future__ import annotations
import asyncio
from copy import deepcopy
from hashlib import sha256
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile
from lxml.etree import XMLSyntaxError
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import Response, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .documents import DocumentError, TOKEN, split_units, export_docx, build_chinese_preview
from .state import Store, StateError, save_json, now, units_with_offsets, validate_links, protected_ok, impact, merge_text, mapping_constraints, rebase_config, validate_config
from .llm import ModelClient, ModelError, ModelOutputError, TASKS, TEMPLATE_VERSION
from .provider_catalog import catalog, PROVIDERS
from .preview import render_preview, PreviewError
from .native_layout import native_layout, raster_page
from .preview_state import committed_preview
from .retranslation import RetranslationJobs
from .translation_router import TranslationRouter

ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('WORDMODIF_DATA',str(ROOT/'.data')))
store=Store(DATA/'projects'); client=ModelClient(DATA)
retranslation_jobs = RetranslationJobs()
@asynccontextmanager
async def lifespan(app):
    recover()
    yield
    await retranslation_jobs.close()
app=FastAPI(title='PaperBridge',version='0.1.0',lifespan=lifespan)

@app.middleware('http')
async def local_origin(request, call_next):
    origin=request.headers.get('origin')
    if origin and origin not in ('http://127.0.0.1:17865','http://localhost:17865','http://localhost:5173','http://127.0.0.1:5173'):
        return JSONResponse({'detail':'不允许来自其他站点的请求'},status_code=403)
    segments = request.url.path.strip('/').split('/')
    if request.method == 'POST' and len(segments) >= 4 and segments[:2] == ['api', 'projects'] and segments[3] in ('paragraphs', 'config'):
        try:
            if store.get(segments[2]).get('retranslation', {}).get('status') == 'running':
                return JSONResponse({'detail': '全文重译进行中，请暂停任务后再编辑。'}, status_code=409)
        except StateError:
            pass
    return await call_next(request)

for error_type in (StateError,DocumentError,ModelError):
    @app.exception_handler(error_type)
    async def domain_error(request, exc): return JSONResponse({'detail':str(exc)},status_code=422)

def recover():
    for file in (DATA/'projects').glob('*/project.json'):
        p=json.loads(file.read_text('utf-8')); changed=False
        for item in p['paragraphs']:
            if item['status']=='running': item['status']='pending' if item['draftZh']!=item['zh'] else ('untranslated' if not item['zh'] else 'needs_alignment'); item['error']='上次请求中断，可重试'; changed=True
        if p.get('retranslation', {}).get('status') == 'running':
            p['retranslation']['status'] = 'interrupted'; changed = True
        if changed: store.save(p)

@app.get('/api/health')
def health(): return {'ok':True,'templateVersion':TEMPLATE_VERSION}

@app.get('/api/projects')
def projects():
    result=[]
    for file in (DATA/'projects').glob('*/project.json'):
        p=json.loads(file.read_text('utf-8')); result.append({k:p[k] for k in ('id','name','created','revision')})
    return sorted(result,key=lambda p:p['created'],reverse=True)

@app.post('/api/projects')
async def upload(file:UploadFile=File(...)):
    if not (file.filename or '').lower().endswith('.docx'): raise StateError('只支持 .docx')
    data=await file.read(40*1024*1024+1)
    try:return store.create(data,file.filename)
    except (BadZipFile,XMLSyntaxError,KeyError) as exc:raise StateError('DOCX 压缩包或 XML 无效，请检查文件是否完整') from exc

@app.get('/api/projects/{pid}')
def project(pid:str): return store.get(pid)

@app.post('/api/projects/{pid}/retranslate')
async def retranslate(pid: str):
    router = TranslationRouter(client, DATA)
    project = retranslation_jobs.create(store, router, store.get(pid))
    retranslation_jobs.launch(store, router, project, translation_candidate, context_for)
    return project

@app.post('/api/projects/{pid}/retranslate/stop')
async def stop_retranslation(pid: str):
    project = store.get(pid)
    if not project.get('retranslation'): raise StateError('这不是全文重译项目。')
    project['retranslation']['stopRequested'] = True
    store.save(project)
    return project

@app.post('/api/projects/{pid}/retranslate/resume')
async def resume_retranslation(pid: str):
    project = store.get(pid)
    if not project.get('retranslation'): raise StateError('这不是全文重译项目。')
    retranslation_jobs.resume(store, project)
    retranslation_jobs.launch(store, TranslationRouter(client, DATA), project, translation_candidate, context_for)
    return project

@app.post('/api/projects/{pid}/paragraphs/{paragraph}/draft')
async def draft(pid:str,paragraph:str,body:dict):
    return store.draft(store.get(pid),paragraph,body['text'],body['revision'])

@app.post('/api/projects/{pid}/paragraphs/{paragraph}/action')
async def action(pid:str,paragraph:str,body:dict):
    p=store.get(pid); item=store.paragraph(p,paragraph); action=body['action']
    if action=='translation_policy':
        from .reference_policy import detect_references
        policy=body.get('policy')
        if policy not in ('translate','skip_reference'): raise StateError('无效的翻译策略。')
        if item['status']=='running': raise StateError('请等待当前模型任务结束后修改翻译策略。')
        if policy=='skip_reference' and item.get('draftZh','')!=item.get('zh',''):
            raise StateError('请先完成或撤销中文草稿，再跳过此段。')
        store.checkpoint(item); item['translationPolicyOverride']=policy
        if policy=='translate':
            item['units']=split_units(item['en'],item['id']+'_')
            item['originalUnits']=split_units(item['originalEn'],item['id']+'_')
            item['status']='ready' if item.get('zh') else 'untranslated'
        detect_references(p['paragraphs']); item['revision']+=1
        store.event(p,item,'translation_policy',{'policy':policy}); store.save(p); return p
    if action in ('undo','redo'): return store.undo(p,paragraph,action=='redo')
    if action=='insert': return store.insert(p,paragraph)
    if action=='delete': return store.delete(p,paragraph)
    if action=='reset':
        store.checkpoint(item); item.update(en=item['originalEn'],zh=item['initialZh'],draftZh=item['initialZh'],revision=item['revision']+1,error='')
        item['units']=split_units(item['en'],item['id']+'_'); item['targetUnits']=split_units(item['zh'],item['id']+'_z')
        item['groups']=[]; item['status']='needs_alignment' if item['zh'] else 'untranslated'
    elif action=='style':
        if body.get('policy') not in ('left','right',None): raise StateError('未知格式继承规则')
        item['stylePolicy']=body.get('policy'); item['revision']+=1
        if item['status']=='running':item['status']='pending' if item['draftZh']!=item['zh'] else ('untranslated' if not item['zh'] else 'ready')
    else: raise StateError('未知操作')
    store.event(p,item,action); store.save(p); return p

def context_for(p,item):
    idx=p['paragraphs'].index(item)
    def context_at(index):
        if not 0 <= index < len(p['paragraphs']): return ''
        other=p['paragraphs'][index]
        return '' if other.get('translationPolicy')=='skip_reference' else other['originalEn']
    return {'previous':context_at(idx-1)[-600:], 'next':context_at(idx+1)[:600]}

def translation_candidate(item,data):
    if data.get('unresolved'): raise StateError('模型报告歧义：'+'；'.join(map(str,data['unresolved'])))
    raw=data.get('target_units',[]); targets=units_with_offsets(raw)
    if not targets and item['en'].strip(): raise StateError('模型漏掉译文')
    text=''.join(u['text'] for u in targets); protected_ok(item['en'],text)
    groups=validate_links(item['units'],targets,[{'source_ids':u.get('source_ids',[]),'target_ids':[u['id']]} for u in raw])
    candidate=deepcopy(item); candidate.update(zh=text,initialZh=text,draftZh=text,targetUnits=targets,groups=groups,status='ready',error='')
    return candidate

def rewrite_candidate(item,data,targets,allowed,anchors):
    if data.get('unresolved'): raise StateError('模型报告歧义：'+'；'.join(map(str,data['unresolved'])))
    units=units_with_offsets(data.get('english_units',[])); before={u['id']:u['text'] for u in item['units']}
    after={u['id']:u['text'] for u in units}; allowed=set(allowed)
    deletes,fixed=mapping_constraints(item,targets,allowed)
    if set(deletes)&set(after):raise StateError('完整删除的中文句仍保留了对应英文；必须删除指定英文 ID')
    for uid,text in before.items():
        if uid not in allowed and after.get(uid)!=text: raise StateError('模型修改了范围外英文，结果已拒绝')
    present=[u['id'] for u in units if u['id'] in before]
    if present != [u['id'] for u in item['units'] if u['id'] in after]: raise StateError('模型重排了原始英文句子')
    last='START'
    for u in units:
        if u['id'] not in before:
            if not u['id'].startswith('new') or last not in anchors: raise StateError('模型在允许范围外新增英文句子')
        else: last=u['id']
    en=''.join(u['text'] for u in units); protected_ok(item['en'],en)
    if bool(en.strip())!=bool(item['draftZh'].strip()): raise StateError('模型输出与中文草稿存在整段遗漏')
    groups=validate_links(units,targets,data.get('links'),item['groups'])
    for locked in fixed:
        for tid in locked['target_ids']:
            actual=set().union(*(set(e['source_ids']) for e in data['links'] if tid in e['target_ids']))
            expected=set().union(*(set(e['source_ids']) for e in fixed if tid in e['target_ids']))
            if actual!=expected:raise StateError('模型重绑了未改动句子的映射，结果已拒绝')
    # Namespaced new IDs persist across future edits instead of colliding with next request.
    renames={u['id']:f'{item["id"]}_r{item["revision"]}_{u["id"]}' for u in units if u['id'] not in before}
    for u in units: u['id']=renames.get(u['id'],u['id'])
    for g in groups:
        g['source_ids']=[renames.get(x,x) for x in g['source_ids']]
        for edge in g['edges']: edge['source_ids']=[renames.get(x,x) for x in edge['source_ids']]
    candidate=deepcopy(item); candidate.update(en=en,zh=item['draftZh'],units=units,targetUnits=targets,groups=groups,status='ready',error='')
    return candidate

@app.post('/api/projects/{pid}/paragraphs/{paragraph}/model')
async def run_model(pid:str,paragraph:str,body:dict):
    p=store.get(pid); item=store.paragraph(p,paragraph); task=body.get('task','rewrite_en')
    if item.get('translationPolicy')=='skip_reference': raise StateError('参考文献已跳过，不调用翻译或句子映射。')
    if task not in TASKS: raise StateError('未知模型任务')
    if item['deleted']: raise StateError('段落已删除')
    if item['status']=='running': raise StateError('此段已有请求正在执行')
    if task=='translate_align' and item['zh']: raise StateError('已有译文，不能直接覆盖；请新建项目或使用编辑回写')
    snapshot=deepcopy(item); revision=item['revision']; job=uuid4().hex
    model_settings=client.read_settings()
    targets=[]; allowed=[]; anchors=[]
    payload={'paragraph_id':paragraph,'revision':revision,'context':context_for(p,item),'protected_tokens':item['protected'],'translationPolicy':item.get('translationPolicy','translate')}
    if task=='translate_align': payload['source_units']=item['units']
    elif task=='repair_alignment':
        # Re-segment the committed fixed text with the current boundary rules;
        # old projects may contain merged units from an earlier splitter.
        targets=split_units(item['zh'],f'{paragraph}_a{revision}_')
        payload.update(source_units=item['units'],target_units=targets)
    else:
        try: allowed,anchors=impact(item,body.get('allowedIds'))
        except StateError as exc:
            item.update(status='needs_alignment',error=str(exc)); store.save(p); raise
        targets=split_units(item['draftZh'],f'{paragraph}_z{revision}_')
        deletes,fixed=mapping_constraints(item,targets,allowed)
        payload.update(source_units=item['units'],original_english=item['originalEn'],chinese_before=item['zh'],
            target_units=targets,allowed_edit_ids=allowed,allowed_insert_after=anchors,must_delete_ids=deletes,fixed_links=fixed)
    item.update(status='running',job=job,error=''); store.save(p)
    try:
        for attempt in range(2):
            try:
                response=await TranslationRouter(client, DATA).generate(task,payload,settings=model_settings,cache=not body.get('noCache',False))
                if task=='translate_align': candidate=translation_candidate(snapshot,response['data'])
                elif task=='rewrite_en': candidate=rewrite_candidate(snapshot,response['data'],targets,allowed,anchors)
                else:
                    if response['data'].get('unresolved'): raise StateError('模型仍无法确定映射，请手工修正')
                    candidate=deepcopy(snapshot); candidate['groups']=validate_links(snapshot['units'],targets,response['data'].get('links'),snapshot['groups'])
                    candidate['targetUnits']=targets
                    candidate['status']='pending' if candidate['draftZh']!=candidate['zh'] else 'ready'; candidate['error']=''
                    response['meta']={**snapshot.get('modelMeta',{}), 'alignmentMethod':'llm',
                        'alignmentModel':response['meta'], 'alignmentNotes':response['data'].get('notes',[]),
                        'alignmentWarning':'', 'alignmentFailure':None}
                break
            except (StateError,ModelOutputError) as exc:
                if attempt: raise
                payload={**payload,'validation_error':str(exc),'repair_instruction':'Return a corrected complete result within the ORIGINAL allowed scope.'}
        current=store.get(pid); live=store.paragraph(current,paragraph)
        if live['revision']!=revision or live.get('job')!=job: return current
        # Dry-run actual package patch before accepting an English candidate.
        check=deepcopy(current['paragraphs']); check[current['paragraphs'].index(live)]=candidate
        export_docx(store.source(current),check)
        if task!='rewrite_en':
            live['history'].append(store.snapshot(snapshot)); live['redo']=[]
        history=live['history']; redo=live['redo']
        candidate.update(history=history,redo=redo,revision=revision+1,modelMeta=response['meta'])
        current['paragraphs'][current['paragraphs'].index(live)]=candidate
        store.event(current,candidate,task,{'model':response['meta']}); store.save(current); return current
    except (StateError,DocumentError,ModelError) as exc:
        current=store.get(pid); live=store.paragraph(current,paragraph)
        if live['revision']==revision and live.get('job')==job:
            live.update(status='failed',error=str(exc)); store.save(current)
        return current

@app.post('/api/projects/{pid}/paragraphs/{paragraph}/mapping')
async def manual_mapping(pid:str,paragraph:str,body:dict):
    p=store.get(pid); item=store.paragraph(p,paragraph)
    if item.get('translationPolicy')=='skip_reference': raise StateError('参考文献不建立句子映射。')
    if body.get('revision')!=item['revision']: raise StateError('映射已过期，请重新打开')
    groups=validate_links(item['units'],item['targetUnits'],body['links'],item['groups'])
    store.checkpoint(item); item.update(groups=groups,revision=item['revision']+1,error='',mappingSource='manual',
        status='pending' if item['draftZh']!=item['zh'] else 'ready')
    store.event(p,item,'manual_mapping'); store.save(p); return p

@app.get('/api/projects/{pid}/config')
def get_config(pid:str):
    config=store.config(store.get(pid))
    return Response(json.dumps(config,ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':'attachment; filename="changes.json"'})

@app.get('/api/projects/{pid}/export')
def download(pid:str):
    p=store.get(pid); data=store.export(p)
    return Response(data,media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition':f'attachment; filename="edited-r{p["revision"]}.docx"','X-Project-Revision':str(p['revision'])})

@app.get('/api/projects/{pid}/preview')
def preview(pid:str, original:bool=True):
    p=store.get(pid)
    snapshot, pending = committed_preview(p)
    data=store.source(p) if original else export_docx(store.source(p), snapshot['paragraphs'])
    try: pdf=render_preview(data, DATA/'previews')
    except PreviewError as exc: raise HTTPException(status_code=503, detail=str(exc)) from exc
    return FileResponse(pdf,media_type='application/pdf',headers={
        'Content-Disposition':'inline; filename="word-preview.pdf"',
        'X-Project-Revision':str(p['revision']), 'Cache-Control':'no-store'})

@app.get('/api/projects/{pid}/native-layout')
def native_pages(pid: str, original: bool = False, language: str = "en", diff: bool = False):
    p = store.get(pid)
    if language not in ('en', 'zh'): raise HTTPException(status_code=422, detail='Unsupported language')
    if language == 'zh' and original: raise HTTPException(status_code=422, detail='Original document is English')
    from . import layout_cache
    source = store.source(p)
    response_key = layout_cache.key(source, p, language, original, diff)
    cached = layout_cache.get(response_key)
    if cached is not None: return cached
    snapshot, pending = committed_preview(p)
    if any(x.get('protected') for x in snapshot['paragraphs']):
        from .documents import zero_width_bookmark_tokens
        bookmarks = zero_width_bookmark_tokens(store.source(p))
        for item in snapshot['paragraphs']:
            item['zeroWidthBookmarkTokens'] = bookmarks.get(item['id'], [])
    diff = diff and not original
    changed = []
    if diff:
        from .diff_preview import build_diff_preview
        data, geometry_paragraphs, changed = build_diff_preview(store.source(p), snapshot['paragraphs'], language)
    else:
        data = build_chinese_preview(store.source(p), snapshot['paragraphs']) if language == 'zh' else (store.source(p) if original else export_docx(store.source(p), snapshot['paragraphs']))
        geometry_paragraphs = snapshot['paragraphs']
    try:
        if source.startswith(b'PK'):
            from .native_anchors import prepare_native_anchors
            data, geometry_paragraphs = prepare_native_anchors(data, geometry_paragraphs, original)
        pdf = render_preview(data, DATA/'previews')
        result = native_layout(pdf, geometry_paragraphs, DATA/'native-pages', p['revision'], original, language)
        result.update(diff=diff, diffParagraphs=changed, diffMapping='paragraph-only-for-changed' if diff else None)
        result.update(pendingParagraphs=pending, disabledUnitParagraphs=[x['id'] for x in pending], snapshotKind='last-synced' if pending else 'current')
        result['responseCacheHit'] = False
        layout_cache.put(response_key, result)
        return result
    except PreviewError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@app.get('/api/native-page/{key}/{page}.png')
def native_image(key: str, page: int):
    try: image = raster_page(DATA/'native-pages', key, page)
    except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(image, media_type='image/png', headers={'Cache-Control':'private, max-age=31536000, immutable'})

@app.post('/api/projects/{pid}/config')
async def import_config(pid:str,body:dict):
    p=store.get(pid); config=body.get('config',{})
    validate_config(config)
    if config.get('schemaVersion')!='1.0': raise StateError('不支持的 config schema 版本')
    config,migration=rebase_config(p,config)
    candidate=deepcopy(p); conflicts=[]; count=0; imported_ids=set(); merged_ids=set()
    states={x['id']:x for x in config.get('paragraphStates',[])}
    original={x['id']:x for x in candidate['paragraphs']}
    for op in config.get('operations',[]):
        pid_=op.get('paragraphId'); kind=op.get('type'); existing=next((x for x in candidate['paragraphs'] if x['id']==pid_),None)
        if kind=='insert_paragraph':
            if existing:
                if existing['en']!=op.get('afterEn'): conflicts.append({'paragraphId':pid_,'reason':'新增段落 ID 冲突'})
                continue
            anchor=next((x for x in candidate['paragraphs'] if x['id']==op.get('inheritFrom') and not x['deleted']),None)
            if not anchor: conflicts.append({'paragraphId':pid_,'reason':'插入锚点不存在或已删除'}); continue
            source=states.get(pid_)
            if not source or not source.get('inserted'): conflicts.append({'paragraphId':pid_,'reason':'缺少新增段落状态'}); continue
            item=deepcopy(source); item.update(history=[],redo=[],originalEn='',originalUnits=[],inserted=True,deleted=False,container='body',protected=[],hasSection=False)
            candidate['paragraphs'].insert(candidate['paragraphs'].index(anchor)+1,item)
        elif kind in ('replace_text','delete_paragraph'):
            if existing is None or existing['originalEn']!=op.get('beforeEn'): conflicts.append({'paragraphId':pid_,'reason':'原文前置条件不匹配'}); continue
            if existing['draftZh']!=existing['zh'] or existing['status']=='running': conflicts.append({'paragraphId':pid_,'reason':'本地有未完成编辑'}); continue
            if existing['deleted'] and kind!='delete_paragraph': conflicts.append({'paragraphId':pid_,'reason':'段落已删除，与文字编辑冲突'}); continue
            if kind=='delete_paragraph' and existing['en']!=existing['originalEn']:
                conflicts.append({'paragraphId':pid_,'reason':'段落删除与本地文字修改冲突'}); continue
            if existing['en']!=existing['originalEn'] and existing['en']!=op.get('afterEn'):
                try:
                    merged_en=merge_text(existing['originalEn'],existing['en'],op.get('afterEn',''))
                    if existing['initialZh']!=op.get('beforeZh'):raise StateError('中文翻译基线不同，无法自动合并')
                    merged_zh=merge_text(existing['initialZh'],existing['zh'],op.get('afterZh',''))
                except StateError as exc:conflicts.append({'paragraphId':pid_,'reason':str(exc)});continue
                existing.update(en=merged_en,zh=merged_zh,draftZh=merged_zh,units=split_units(merged_en,pid_+'_merge'),targetUnits=split_units(merged_zh,pid_+'_zmerge'),groups=[],status='needs_alignment',error='不重叠文字已合并，请重新对齐后导出',revision=existing['revision']+1)
                merged_ids.add(pid_); imported_ids.add(pid_); count+=1;continue
            item=existing
            if kind=='delete_paragraph': item['deleted']=True
        else: conflicts.append({'paragraphId':pid_,'reason':'未知操作类型'}); continue
        if not isinstance(op.get('afterEn'),str): raise StateError('afterEn 必须为文字')
        item['en']=op['afterEn']; item['stylePolicy']=op.get('stylePolicy'); item['revision']+=1
        source=states.get(pid_)
        if source and source.get('en')==item['en'] and not item['deleted']:
            try:
                units=units_with_offsets(source['units']); target=units_with_offsets(source['targetUnits'])
                if ''.join(u['text'] for u in units)!=item['en'] or ''.join(u['text'] for u in target)!=source['zh']: raise StateError('状态文本不一致')
                protected_ok(item['en'],source['zh']);protected_ok(source['zh'],source.get('draftZh',source['zh']))
                groups=validate_links(units,target,[edge for g in source['groups'] for edge in g.get('edges',[g])])
                item.update(units=units,targetUnits=target,groups=groups,zh=source['zh'],initialZh=source.get('initialZh',''),draftZh=source.get('draftZh',source['zh']),status='ready')
                if item['draftZh']!=item['zh']: item['status']='pending'
            except (StateError,KeyError): item['status']='needs_alignment'; item['groups']=[]
        elif not item['deleted']:
            item.update(units=split_units(item['en'],item['id']+'_imp'),groups=[],status='needs_alignment',error='config 英文已变更，需核对中文并重新对齐')
        imported_ids.add(pid_);count+=1
    # Restore translation-only and pending draft state even when no English patch exists.
    for pid_,source in states.items():
        if pid_ in imported_ids:continue
        item=next((x for x in candidate['paragraphs'] if x['id']==pid_),None)
        if item is None or source.get('originalEn')!=item['originalEn']:continue
        if item['zh']:
            incoming_draft=source.get('draftZh',source.get('zh',''))
            if source.get('en')!=item['en'] or incoming_draft==item['draftZh']:continue
            if source.get('initialZh')!=item['initialZh']:
                conflicts.append({'paragraphId':pid_,'reason':'中文翻译基线不同，需人工选择版本'});continue
            try:
                merged=merge_text(item['initialZh'],item['draftZh'],incoming_draft)
                protected_ok(item['zh'],merged)
            except StateError as exc:conflicts.append({'paragraphId':pid_,'reason':str(exc)});continue
            if merged!=item['draftZh']:
                store.checkpoint(item);item.update(draftZh=merged,revision=item['revision']+1,status='pending' if merged!=item['zh'] else 'ready');count+=1
            continue
        if item['en']!=item['originalEn']:continue
        if source.get('en')!=item['en']:continue
        try:
            units=units_with_offsets(source['units']);targets=units_with_offsets(source['targetUnits'])
            if ''.join(x['text'] for x in units)!=item['en'] or ''.join(x['text'] for x in targets)!=source['zh']:raise StateError('文本与映射状态不一致')
            groups=validate_links(units,targets,[e for g in source['groups'] for e in g.get('edges',[g])])
            protected_ok(item['en'],source['zh']);protected_ok(source['zh'],source.get('draftZh',source['zh']))
        except (KeyError,StateError):continue
        item.update(units=units,targetUnits=targets,groups=groups,zh=source['zh'],initialZh=source.get('initialZh',source['zh']),draftZh=source.get('draftZh',source['zh']),history=[],redo=[],revision=item['revision']+1,
            status='pending' if source.get('draftZh',source['zh'])!=source['zh'] else 'ready')
        count+=1
    if conflicts: return {'conflicts':conflicts,'applied':False,'count':count,'migration':migration}
    export_docx(store.source(p),candidate['paragraphs'])
    if not body.get('apply'): return {'conflicts':[],'applied':False,'count':count,'migration':migration}
    candidate['revision']+=1; candidate['events'].append({'id':uuid4().hex,'type':'import_config','time':now(),'revision':candidate['revision']})
    store.save(candidate); return {'conflicts':[],'applied':True,'project':candidate,'count':count,'migration':migration}

@app.get('/api/settings')
def settings():
    s=client.read_settings()
    for provider in s['providers']: provider['hasKey']=bool(client.secret(provider['id']))
    return s


@app.get('/api/task-assignments')
def task_assignments_get():
    from .task_assignments import read_task_assignments
    return read_task_assignments(DATA, client.read_settings())


@app.post('/api/task-assignments')
def task_assignments_save(body:dict):
    from .task_assignments import save_task_assignments
    return save_task_assignments(DATA, body, client.read_settings())


@app.get('/api/provider-catalog')
def provider_catalog(): return catalog()

def validate_model_settings(config):
    from urllib.parse import urlsplit
    if not isinstance(config.get('providers'),list) or not isinstance(config.get('profiles'),list): raise StateError('服务和模型配置必须是列表')
    providers = config['providers']; profiles = config['profiles']
    for rows in (providers, profiles):
        if any(not isinstance(row,dict) for row in rows): raise StateError('服务和模型配置项必须为对象')
        ids = [p.get('id') for p in rows]
        if any(not isinstance(i,str) or not i for i in ids) or len(set(ids)) != len(ids): raise StateError('配置 ID 必须非空且不能重复')
    for provider in providers:
        preset=next((p for p in PROVIDERS if p['id']==provider.get('presetId')),None)
        if preset and preset.get('available') is False:
            raise StateError(preset['notes'])
        if preset and preset['id'] != 'custom' and provider.get('protocol') != preset['protocol']:
            raise StateError('所选厂商方案与接口协议不匹配，请重新选择方案或切换自定义服务')
        url = urlsplit(provider.get('baseUrl',''))
        if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.query or url.fragment: raise StateError('接口地址需为有效 HTTP(S) 基础地址，不能含凭据、查询参数或片段')
        if provider.get('protocol') not in ('openai_chat','openai_responses','anthropic_messages','google_genai'): raise StateError('不支持的服务协议')
        value = provider.get('timeout',180)
        if not isinstance(value,(int,float)) or isinstance(value,bool) or not 1 <= value <= 3600: raise StateError('生成等待时间需为1至3600秒')
    for profile in profiles:
        if profile.get('providerId') not in [p['id'] for p in providers]: raise StateError('模型引用的服务不存在')
        if not isinstance(profile.get('model'),str) or not profile['model'].strip(): raise StateError('请填写模型 ID')
        for key in ('maxTokens','contextTokens'):
            value = profile.get(key)
            if not isinstance(value,int) or isinstance(value,bool) or value < 1 or value > 2000000: raise StateError('token 预算需为有效正整数')
        if profile.get('outputMode') not in ('json','schema','text'): raise StateError('未知结构化输出模式')
        if profile['contextTokens'] <= profile['maxTokens']: raise StateError('上下文预算需大于输出预算')
        value = profile.get('temperature')
        if value is not None and (not isinstance(value,(int,float)) or isinstance(value,bool) or not 0 <= value <= 2): raise StateError('温度需在0至2之间')
        if not isinstance(profile.get('extraBody',{}),dict): raise StateError('高级参数必须是 JSON 对象')


@app.post('/api/settings')
async def set_settings(body:dict):
    config=deepcopy(body); config.pop('translation',None); validate_model_settings(config); secret_file=DATA/'secrets.json'
    from .task_assignments import validate_profile_removal
    validate_profile_removal(DATA, config)
    if (DATA/'task-assignments.json').exists():
        config['routes'] = client.read_settings()['routes']
    secrets=json.loads(secret_file.read_text('utf-8-sig')) if secret_file.exists() else {}
    for provider in config.get('providers',[]):
        if not provider.get('baseUrl','').startswith(('http://','https://')): raise StateError('接口地址必须为 HTTP(S) URL')
        key=provider.pop('apiKey',None); provider.pop('hasKey',None)
        if key: secrets[provider['id']]=key
    for task in TASKS: client.resolve(config,task)
    save_json(secret_file,secrets); save_json(DATA/'settings.json',config); return settings()

@app.post('/api/settings/test')
async def test_settings(body:dict):
    config=client.read_settings(); task=body.get('task','translate_align')
    if task not in TASKS:raise StateError('未知任务')
    profile_id = body.get('profileId')
    if profile_id and not any(p['id'] == profile_id for p in config['profiles']): raise StateError('模型配置不存在')
    config['routes']['translate_align']=profile_id or config['routes'][task]
    response=await client.generate('translate_align',{'paragraph_id':'connection-test','source_units':[{'id':'s1','text':'The sample contains two cells.'}]},settings=config,cache=False)
    source=[{'id':'s1','text':'The sample contains two cells.'}]
    candidate=translation_candidate({'units':source,'en':source[0]['text']},response['data'])
    return {'ok':True,'translation':candidate['zh'],'meta':response['meta']}

@app.get('/api/settings/models/{provider_id}')
async def discover(provider_id:str):
    provider=next((x for x in client.read_settings()['providers'] if x['id']==provider_id),None)
    if provider is None: raise StateError('服务不存在')
    return {'models':await client.models(provider)}


@app.post('/api/settings/models')
async def discover_draft(body:dict):
    from urllib.parse import urlsplit
    draft=deepcopy(body.get('provider',{}))
    if not isinstance(draft,dict): raise StateError('服务配置必须为对象')
    draft.setdefault('id','draft-discovery')
    validate_model_settings({'providers':[draft],'profiles':[]})
    saved=next((p for p in client.read_settings()['providers'] if p['id']==draft['id']),None)
    key=draft.pop('apiKey',None)
    if not key and saved and urlsplit(saved['baseUrl']).hostname == urlsplit(draft['baseUrl']).hostname:
        key=client.secret(saved['id'])
    # An untrusted draft ID must never retrieve another host's stored key.
    draft['id']='draft-discovery'
    draft['apiKey']=key or 'local'
    return {'models':await client.models(draft)}

@app.get('/api/translation-services/catalog')
def translation_services_catalog():
    from .translation_services import translation_catalog
    return translation_catalog()


@app.get('/api/translation-settings')
def translation_settings_get():
    from .translation_settings import public_settings
    return public_settings(DATA)


@app.post('/api/translation-settings')
def translation_settings_save(body:dict):
    from .translation_settings import save_translation_settings
    return save_translation_settings(DATA, body)


@app.post('/api/translation-settings/test')
async def translation_settings_test(body:dict):
    import time
    from .translation_settings import read_translation_settings, read_translation_secrets
    from .translation_services import translate
    selected=body.get('providerId','llm'); started=time.monotonic()
    if selected=='llm':
        result=await client.generate('translate_align', {'paragraph_id':'translation-service-test','source_units':[{'id':'s1','text':'The sample contains two cells.'}]},cache=False)
        candidate=translation_candidate({'units':[{'id':'s1','text':'The sample contains two cells.'}],'en':'The sample contains two cells.'},result['data'])
        return {'ok':True,'translation':candidate['zh'],'seconds':round(time.monotonic()-started,2)}
    provider=next((p for p in read_translation_settings(DATA)['providers'] if p['id']==selected),None)
    if provider is None:raise StateError('翻译服务配置不存在。')
    translated=await translate(['The sample contains two cells.'],'en','zh',provider,read_translation_secrets(DATA).get(selected,{}))
    return {'ok':True,'translation':translated[0],'seconds':round(time.monotonic()-started,2),'service':provider['kind']}


DIST=ROOT/'web'/'dist'
if DIST.exists():
    app.mount('/assets',StaticFiles(directory=DIST/'assets'),name='assets')
    @app.get('/')
    def index(): return FileResponse(DIST/'index.html')
