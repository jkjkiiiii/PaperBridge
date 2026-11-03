"""Safe display labels and confirmation tokens; historical metadata is not inferred from live settings."""
from collections import Counter
from hashlib import sha256
import hmac
import json
import secrets
from .translation_router import public_translation
from .llm import ModelError

_SIGNING_KEY=secrets.token_bytes(32)


def next_labels(client, settings):
    selected=public_translation(settings)
    if selected['providerId']=='llm':
        provider,profile=client.resolve(settings,'translate_align')
        model=str(profile['model'])
        return {'translationLabel':f"{provider.get('name') or provider['id']} · {model}",
                'alignmentLabel':f'随初译生成 · {model}'}
    provider=next((x for x in selected['providers'] if x['id']==selected['providerId']),None)
    if provider is None:raise ModelError('选中的翻译服务不存在，请重新配置翻译 API。')
    alignment_provider,profile=client.resolve(settings,'repair_alignment')
    return {'translationLabel':f"{provider.get('name') or provider['kind']} · 翻译 API",
            'alignmentLabel':f"{alignment_provider.get('name') or alignment_provider['id']} · {profile['model']}"}


def provenance(project, client):
    translations=Counter();alignments=Counter();unknown=0;total=0
    for p in project.get('paragraphs',[]):
        meta=p.get('modelMeta') if isinstance(p.get('modelMeta'),dict) else {}
        service=meta.get('translationService') if isinstance(meta.get('translationService'),dict) else {}
        if p.get('deleted') or not p.get('zh') or p.get('translationPolicy')=='skip_reference':continue
        if service.get('kind')=='identity' or meta.get('model')=='numeric-identity':continue
        total+=1
        # A rewrite model generated English, not the initial Chinese translation.
        # Without retained translation evidence, label it unknown.
        if meta.get('task') not in (None,'translate_align'):
            unknown+=1;continue
        model=meta.get('model')
        if isinstance(model,str) and model.strip():
            label=model + (' · 翻译 API' if service.get('kind') else '')
            translations[label]+=1
        else:unknown+=1
        align=meta.get('alignmentModel') or {}
        if meta.get('alignmentMethod') in ('positional','paragraph-fallback','fallback','fallback-paragraph'):
            alignments['降级映射']+=1
        elif isinstance(align,dict) and isinstance(align.get('model'),str):
            alignments[align['model']]+=1
        elif meta.get('task')=='translate_align' and model and not service:
            alignments[f'随初译生成 · {model}']+=1
    status='none' if not total else 'multiple' if len(translations)>1 else 'unknown' if unknown else 'single'
    labels=list(translations)
    label='尚无译文' if not total else '来源未知（历史记录不足）' if not labels else '、'.join(labels)
    if len(labels)>1:label='混合来源：'+label
    if labels and unknown:label+='；部分来源未知'
    result={'translationLabel':label,'alignmentLabel':'、'.join(alignments) if alignments else ('尚无映射' if not total else '映射来源记录不足'),
            'status':status,'sources':[{'label':k,'count':v} for k,v in translations.items()],
            'translatedParagraphs':total,'unknownParagraphs':unknown}
    pinned=project.get('retranslation',{}).get('settings')
    if pinned:
        try:result['planned']=next_labels(client,pinned)
        except (ModelError,KeyError,TypeError):pass
    return result


def plan_token(project,settings,source):
    # Include the complete state, not just revision: external config edits and
    # in-progress changes must invalidate confirmation as well.
    payload=json.dumps([project,settings,sha256(source).hexdigest()],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    return hmac.new(_SIGNING_KEY,payload,sha256).hexdigest()


def plan(project,client,settings,source):
    return {'current':provenance(project,client),'next':next_labels(client,settings),
            'planToken':plan_token(project,settings,source),'sourceRevision':project['revision']}


def with_provenance(project,client):
    return {**project,'translationProvenance':provenance(project,client)}
