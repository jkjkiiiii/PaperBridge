from __future__ import annotations
from copy import deepcopy
from difflib import SequenceMatcher
from hashlib import sha256
import json
import re
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from jsonschema import validate, ValidationError
from .documents import extract, extract_layout, split_units, TOKEN, export_docx, DocumentError

class StateError(ValueError): pass
CONFIG_SCHEMA={'type':'object','required':['schemaVersion','sourceSha256','operations'],
 'properties':{'schemaVersion':{'const':'1.0'},'sourceSha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},
 'operations':{'type':'array','items':{'type':'object','required':['type','paragraphId','beforeEn','afterEn'],
    'properties':{'type':{'enum':['replace_text','insert_paragraph','delete_paragraph']},'paragraphId':{'type':'string','minLength':1},'beforeEn':{'type':'string'},'afterEn':{'type':'string'},'beforeZh':{'type':'string'},'afterZh':{'type':'string'},'inheritFrom':{'type':['string','null']},'stylePolicy':{'enum':['left','right',None]}}}},
 'paragraphStates':{'type':'array','items':{'type':'object','required':['id','originalEn','en','zh','draftZh','units','targetUnits','groups'],
    'properties':{'id':{'type':'string'},'originalEn':{'type':'string'},'en':{'type':'string'},'zh':{'type':'string'},'draftZh':{'type':'string'},'units':{'type':'array'},'targetUnits':{'type':'array'},'groups':{'type':'array'}}}}}}
def validate_config(config):
    try:validate(config,CONFIG_SCHEMA)
    except ValidationError as exc:raise StateError('config 不符合 schema：'+('.'.join(map(str,exc.absolute_path)) or '根对象')) from exc
def now(): return datetime.now(timezone.utc).isoformat()
def digest(value): return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp'); temp.write_text(json.dumps(value,ensure_ascii=False,indent=2), 'utf-8'); temp.replace(path)

def units_with_offsets(units):
    if not isinstance(units,list): raise StateError('句子列表格式错误')
    result, cursor, seen = [], 0, set()
    for unit in units:
        if not isinstance(unit,dict) or not isinstance(unit.get('id'),str) or not isinstance(unit.get('text'),str): raise StateError('句子缺少 ID 或文本')
        if unit['id'] in seen or not unit['text']: raise StateError('句子 ID 重复或文本为空')
        seen.add(unit['id']); end = cursor + len(unit['text'])
        result.append({'id':unit['id'],'text':unit['text'],'start':cursor,'end':end}); cursor = end
    return result

def validate_links(source, target, links, previous=()):
    if not isinstance(links,list): raise StateError('缺少映射列表')
    ss, ts = {x['id'] for x in source}, {x['id'] for x in target}
    covered_s, covered_t, groups = set(), set(), []
    for link in links:
        a, b = link.get('source_ids',[]), link.get('target_ids',[])
        if not isinstance(a,list) or not isinstance(b,list) or not a or not b or len(a)!=len(set(a)) or len(b)!=len(set(b)):
            raise StateError('对应关系为空或存在重复 ID')
        a,b = set(a),set(b)
        if not a <= ss or not b <= ts: raise StateError('映射包含未知句子 ID')
        covered_s |= a; covered_t |= b
        # Connected components give minimal independent groups; retain direct edges too.
        overlap = [g for g in groups if g[0]&a or g[1]&b]
        for g in overlap: a |= g[0]; b |= g[1]; groups.remove(g)
        groups.append((a,b))
    if covered_s != ss or covered_t != ts: raise StateError('映射未覆盖全部句子，不能提交')
    answer=[]
    for a,b in groups:
        a_order=[u['id'] for u in source if u['id'] in a]; b_order=[u['id'] for u in target if u['id'] in b]
        old = next((g for g in previous if set(g['source_ids']) == a), None)
        gid = old['id'] if old else 'g'+digest(a_order)[:10]
        color = old['color'] if old else (max([g['color'] for g in [*previous,*answer]],default=-1)+1)
        answer.append({'id':gid,'source_ids':a_order,'target_ids':b_order,'color':color,
            'kind':f'{len(a)}:{len(b)}','edges':[e for e in links if set(e['source_ids']) <= a and set(e['target_ids']) <= b]})
    return sorted(answer,key=lambda g:next(i for i,u in enumerate(source) if u['id'] in g['source_ids']))

def protected_ok(before, after):
    if TOKEN.findall(before) != TOKEN.findall(after): raise StateError('保护对象不可增加、删除或改变顺序')

def merge_text(base, local, incoming):
    """Three-way merge only disjoint original-coordinate edits; collisions are explicit."""
    if local==incoming or incoming==base:return local
    if local==base:return incoming
    def edits(text):return [(a,b,text[c:d]) for kind,a,b,c,d in SequenceMatcher(None,base,text,autojunk=False).get_opcodes() if kind!='equal']
    current=edits(local);extra=edits(incoming)
    for a,b,value in extra:
        if (a,b,value) in current:continue
        for x,y,_ in current:
            if max(a,x)<min(b,y) or (a==b and x<=a<=y) or (x==y and a<=x<=b):raise StateError('同一原文范围存在重叠修改')
        current.append((a,b,value))
    result=base
    for a,b,value in sorted(current,reverse=True):result=result[:a]+value+result[b:]
    return result

def rebase_config(project, config):
    """Only unique exact-text matches in unchanged plain paragraphs can migrate."""
    if not re.fullmatch(r'[a-f0-9]{64}',config.get('sourceSha256','')):raise StateError('原文件 SHA-256 格式无效')
    if config.get('sourceSha256')==project['sourceSha256']:return config,[]
    incoming=deepcopy(config);states={x['id']:x for x in incoming.get('paragraphStates',[])};remap={};evidence=[]
    current={x['id']:x for x in project['paragraphs'] if not x['inserted']}
    def resolve(pid,text=None):
        if pid in remap:return remap[pid]
        source=states.get(pid,{})
        text=text if text is not None else source.get('originalEn')
        if not text or source.get('protected'):raise StateError('不同原文件：目标段落含对象或缺少原文，无法可靠迁移')
        matches=[x for x in current.values() if x['originalEn']==text and not x['protected'] and (not source.get('container') or source['container']==x['container'])]
        if len(matches)!=1:raise StateError('不同原文件：原文目标不是唯一精确匹配，请人工处理')
        new=matches[0]['id']
        if new in remap.values():raise StateError('不同原文件：多个来源段落指向同一目标')
        remap[pid]=new;evidence.append({'oldParagraphId':pid,'newParagraphId':new,'method':'unique_exact_text'});return new
    inserted={op['paragraphId'] for op in incoming.get('operations',[]) if op.get('type')=='insert_paragraph'}
    for op in incoming.get('operations',[]):
        if op.get('type')!='insert_paragraph':resolve(op['paragraphId'],op.get('beforeEn'))
        elif op.get('inheritFrom') not in inserted:resolve(op['inheritFrom'])
    if not incoming.get('operations'):raise StateError('原文件哈希不同，缺少可独立核验的操作，不能自动恢复整份项目')
    for op in incoming['operations']:
        op['paragraphId']=remap.get(op['paragraphId'],op['paragraphId'])
        op['inheritFrom']=remap.get(op.get('inheritFrom'),op.get('inheritFrom'))
    result=[]
    for old,state in states.items():
        if old not in remap and old not in inserted:continue
        new=remap.get(old,old)
        def uid(value):return new+value[len(old):] if isinstance(value,str) and value.startswith(old+'_') else value
        state['id']=new;state['inheritFrom']=remap.get(state.get('inheritFrom'),state.get('inheritFrom'));state['history']=[];state['redo']=[]
        for field in ('units','targetUnits','originalUnits'):
            for unit in state.get(field,[]):unit['id']=uid(unit['id'])
        for group in state.get('groups',[]):
            for link in [group,*group.get('edges',[])]:
                for field in ('source_ids','target_ids'):link[field]=[uid(x) for x in link[field]]
        result.append(state)
    incoming['paragraphStates']=result;incoming['sourceSha256']=project['sourceSha256']
    return incoming,evidence

def impact(p, override=None):
    old, new = p['zh'], p['draftZh']
    if p['inserted'] and not p['en']: return [], ['START']
    touched=set(); insert_positions=[]
    for kind,a,b,c,d in SequenceMatcher(None,old,new,autojunk=False).get_opcodes():
        if kind=='equal': continue
        if kind=='insert': insert_positions.append(a)
        for u in p.get('targetUnits',[]):
            if (a<b and u['start']<b and u['end']>a) or (a==b and u['start']<=a<u['end']): touched.add(u['id'])
        if a==b and a==len(old) and p.get('targetUnits'): touched.add(p['targetUnits'][-1]['id'])
    allowed=set(); ambiguous=False
    for g in p['groups']:
        hits=set(g['target_ids'])&touched
        if hits:
            direct=set().union(*(set(e['source_ids']) for e in g.get('edges',[g]) if set(e['target_ids'])&hits))
            allowed |= direct
            if len(direct)>1 and hits != set(g['target_ids']): ambiguous=True
    if override is not None:
        if not set(override) <= {u['id'] for u in p['units']}: raise StateError('手工回写范围包含未知句子')
        allowed=set(override); ambiguous=False
    if ambiguous: raise StateError('局部编辑涉及多对多映射，请修正映射或明确选择允许回写的英文句子')
    ordered=[u['id'] for u in p['units'] if u['id'] in allowed]
    anchors=list(ordered)
    for i,u in enumerate(p['units']):
        if u['id'] in allowed: anchors.append(p['units'][i-1]['id'] if i else 'START')
    if not allowed and old != new: raise StateError('无法定位修改范围，请先修正映射')
    return ordered, list(dict.fromkeys(anchors))

def mapping_constraints(p, targets, allowed):
    """Structural evidence from exact edits, not a claim of semantic validation."""
    ops=list(SequenceMatcher(None,p['zh'],p['draftZh'],autojunk=False).get_opcodes())
    removed=set();same={}
    for unit in p.get('targetUnits',[]):
        if any(kind=='delete' and a<=unit['start'] and b>=unit['end'] for kind,a,b,c,d in ops):removed.add(unit['id'])
        for kind,a,b,c,d in ops:
            if kind=='equal' and a<=unit['start'] and b>=unit['end']:
                start=c+unit['start']-a;end=start+len(unit['text'])
                match=next((u for u in targets if u['start']==start and u['end']==end and u['text']==unit['text']),None)
                if match:same[unit['id']]=match['id']
    deletes=set();fixed=[]
    for g in p['groups']:
        if set(g['target_ids'])<=removed and set(g['source_ids'])<=set(allowed):deletes.update(g['source_ids'])
        if not set(g['source_ids'])&set(allowed) and all(x in same for x in g['target_ids']):
            for edge in g.get('edges',[g]):fixed.append({'source_ids':edge['source_ids'],'target_ids':[same[x] for x in edge['target_ids']]})
    return sorted(deletes),fixed

def numeric_table_cell(item):
    text = item.get('originalEn', '')
    return (item.get('container') == 'table' and bool(re.search(r'\d', text))
            and bool(re.fullmatch(r'[\d\s.,/:;%+\-−–—±×÷=<>≤≥()\[\]{}*†‡]+', text)))


def preserve_numeric_cell(item, events=()):
    """Copy unedited numeric table contents; never reinterpret dates or statistics."""
    if not numeric_table_cell(item) or item.get('inserted') or item.get('deleted') or item.get('protected'):
        return False
    if item['en'] != item['originalEn'] or item.get('draftZh', '') != item.get('zh', ''):
        return False
    if item.get('status') not in ('ready', 'untranslated') or item.get('redo'):
        return False
    if any(e.get('paragraphId') == item['id'] and e.get('type') != 'translate_align' for e in events):
        return False
    history = item.get('history', [])
    if history and not (len(history) == 1 and history[0].get('status') == 'untranslated'
                        and not history[0].get('zh') and not history[0].get('draftZh')
                        and history[0].get('en') == item['originalEn']):
        return False
    if item.get('numericIdentity') and item.get('zh') == item['originalEn']:
        return False
    text = item['originalEn']
    targets = [dict(u, id=u['id'] + '_numeric') for u in item['units']]
    links = [{'source_ids': [a['id']], 'target_ids': [b['id']]} for a, b in zip(item['units'], targets)]
    provenance = {'rule': 'numeric-table-identity-v1', 'previousZh': item.get('zh', ''),
                  'reason': 'Numeric-only table content copied verbatim; no user edits detected.'}
    item.update(zh=text, initialZh=text, draftZh=text, targetUnits=targets,
                groups=validate_links(item['units'], targets, links), status='ready', error='',
                numericIdentity=True, numericIdentityProvenance=provenance,
                modelMeta={'model': 'numeric-identity', 'seconds': 0})
    return True


class Store:
    def __init__(self, folder): self.folder=Path(folder); self.folder.mkdir(exist_ok=True,parents=True)
    def path(self,pid):
        if not re.fullmatch(r'[a-f0-9]{32}',pid): raise StateError('项目 ID 无效')
        return self.folder / pid
    def get(self,pid):
        file=self.path(pid)/'project.json'
        if not file.exists(): raise StateError('项目不存在')
        result=json.loads(file.read_text('utf-8'))
        for item in result['paragraphs']:
            item.setdefault('originalUnits',split_units(item['originalEn'],item['id']+'_'))
            preserve_numeric_cell(item, result.get('events', []))
        if 'layout' not in result:
            result['layout'] = extract_layout(self.source(result))
        return result
    def save(self,p): save_json(self.path(p['id'])/'project.json',p)
    def source(self,p): return (self.path(p['id'])/'original.docx').read_bytes()
    def create(self,data,name):
        paragraphs=extract(data); pid=uuid4().hex
        self.path(pid).mkdir(); (self.path(pid)/'original.docx').write_bytes(data)
        for p in paragraphs:
            p['targetUnits']=[]; p['history']=[]; p['redo']=[]; p['error']=''
            preserve_numeric_cell(p)
        project={'id':pid,'name':Path(name).name,'created':now(),'revision':0,'sourceSha256':sha256(data).hexdigest(),
            'paragraphs':paragraphs,'events':[], 'layout':extract_layout(data)}
        self.save(project); return project
    def paragraph(self,p,pid):
        result=next((x for x in p['paragraphs'] if x['id']==pid),None)
        if result is None: raise StateError('段落不存在')
        return result
    def event(self,p,item,kind,extra=None):
        p['revision']+=1
        p['events'].append({'id':uuid4().hex,'time':now(),'paragraphId':item['id'],'type':kind,'revision':p['revision'],**(extra or {})})
    @staticmethod
    def snapshot(item): return deepcopy({k:v for k,v in item.items() if k not in ('history','redo')})
    def checkpoint(self,item): item['history'].append(self.snapshot(item)); item['redo']=[]
    def draft(self,p,pid,text,revision):
        item=self.paragraph(p,pid)
        if item['revision'] != revision: raise StateError('编辑版本已变化，请刷新后重试')
        if item['deleted']: raise StateError('不能编辑已删除段落')
        if item['status']=='untranslated' and not item['inserted']: raise StateError('请先翻译该段落')
        if not isinstance(text,str) or len(text)>100000: raise StateError('段落长度超限')
        protected_ok(item['zh'],text)
        if text==item['draftZh']: return p
        self.checkpoint(item); item['draftZh']=text; item['revision']+=1
        item['status']='ready' if text==item['zh'] else 'pending'; item['error']=''
        self.event(p,item,'edit_chinese'); self.save(p); return p
    def undo(self,p,pid,redo=False):
        item=self.paragraph(p,pid); stack=item['redo' if redo else 'history']
        if not stack: return p
        snap=stack.pop(); reverse=item['history' if redo else 'redo']; reverse.append(self.snapshot(item))
        revision=item['revision']+1; history=item['history']; future=item['redo']
        item.clear(); item.update(snap); item.update(revision=revision,history=history,redo=future)
        if item['status']=='running': item['status']='pending'
        self.event(p,item,'redo' if redo else 'undo'); self.save(p); return p
    def insert(self,p,after):
        origin=self.paragraph(p,after)
        if origin['deleted'] or origin['container']!='body': raise StateError('只能在有效正文段落之后新增')
        item=deepcopy(origin); pid='n'+uuid4().hex[:12]
        item.update(id=pid,index=None,originalEn='',originalUnits=[],en='',zh='',initialZh='',draftZh='',units=[],targetUnits=[],groups=[],runs=[],protected=[],
            hasSection=False,inserted=True,inheritFrom=after,status='ready',revision=0,history=[],redo=[],error='')
        p['paragraphs'].insert(p['paragraphs'].index(origin)+1,item)
        # Keep explicit insertion chain consistent with visual order.
        idx=p['paragraphs'].index(item)
        if idx+1<len(p['paragraphs']) and p['paragraphs'][idx+1]['inserted'] and p['paragraphs'][idx+1]['inheritFrom']==after:
            p['paragraphs'][idx+1]['inheritFrom']=pid
        self.event(p,item,'insert_paragraph'); self.save(p); return p
    def delete(self,p,pid):
        item=self.paragraph(p,pid)
        if item['protected'] or item['hasSection'] or item['container']!='body': raise StateError('带保护对象、分节符或位于表格中的段落不能删除')
        if any(x['inserted'] and not x['deleted'] and x['inheritFrom']==pid for x in p['paragraphs']): raise StateError('此段为新增段落的锚点，请先处理其后新增段落')
        self.checkpoint(item); item['deleted']=not item['deleted']; item['revision']+=1
        self.event(p,item,'delete_paragraph' if item['deleted'] else 'restore_paragraph'); self.save(p); return p
    def config(self,p):
        operations=[]
        for i,item in enumerate(p['paragraphs']):
            if item['inserted'] and item['deleted']: continue
            if not item['inserted'] and not item['deleted'] and item['en']==item['originalEn']: continue
            op={'id':digest([item['id'],item['en'],item['deleted']])[:20],
                'type':'delete_paragraph' if item['deleted'] else ('insert_paragraph' if item['inserted'] else 'replace_text'),
                'paragraphId':item['id'],'paragraphIndex':item['index'],'beforeEn':item['originalEn'],'afterEn':item['en'],
                'beforeZh':item['initialZh'],'afterZh':item['zh'],'sentenceIds':[u['id'] for u in item['units']],
                'inheritFrom':item['inheritFrom'],'stylePolicy':item.get('stylePolicy'),'status':'ready' if item['deleted'] else item['status']}
            operations.append(op)
        return {'schemaVersion':'1.0','sourceSha256':p['sourceSha256'],'revision':p['revision'],
            'operations':operations,'paragraphStates':deepcopy(p['paragraphs']),'events':deepcopy(p['events'])}
    def export(self,p):
        bad=[x for x in p['paragraphs'] if not x['deleted'] and x['status'] not in ('ready','untranslated')]
        if bad: raise StateError(f'还有 {len(bad)} 段待回写或待解决；请完成、重试或撤销后导出')
        return export_docx(self.source(p),p['paragraphs'])
