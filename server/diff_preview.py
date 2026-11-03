"""Disposable visual redlines. Never used by the DOCX export endpoint."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import json
import subprocess
from lxml import etree as E
from .documents import export_docx, load_package, atoms, tag, put_text, NS, DocumentError


def display_diffs(pairs, language):
    root = Path(__file__).resolve().parents[1]
    # Exact same bounded English word/inflection policy as the structure view.
    script = """import {englishDisplayDiff} from './web/src/textDiff.mjs';
import {diffChars} from './web/node_modules/diff/lib/index.js';
let input='';for await(const c of process.stdin)input+=c;
const {pairs,language}=JSON.parse(input);
process.stdout.write(JSON.stringify(pairs.map(([a,b])=>(language==='en'?englishDisplayDiff:diffChars)(a,b))));"""
    try:
        result = subprocess.run(['node', '--input-type=module', '-e', script], input=json.dumps({'pairs':pairs,'language':language}),
            text=True, encoding='utf-8', capture_output=True, cwd=root, timeout=30,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode: raise ValueError(result.stderr)
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise DocumentError('差异页面生成失败：无法运行本地文字差异模块') from exc


def paint(paragraph, spans):
    # Split only editable text runs in a disposable package; preserve all run
    # properties and non-text children. Diff colors never enter source/export.
    for run in list(paragraph.iter(tag('r'))):
        children=[c for c in run if c.tag!=tag('rPr')]
        if len(children)<2: continue
        parent=run.getparent();at=parent.index(run)
        for i,child in enumerate(children):
            clone=E.Element(tag('r'),attrib=dict(run.attrib));props=run.find(tag('rPr'))
            if props is not None: clone.append(deepcopy(props))
            clone.append(deepcopy(child));parent.insert(at+i,clone)
        parent.remove(run)
    for atom in reversed(atoms(paragraph)):
        if atom['protected']: continue
        node = atom['node']; run = node.getparent()
        if run.tag != tag('r'): raise DocumentError('差异预览遇到不支持的文本结构')
        intervals = []
        cuts = {atom['start'], atom['end']}
        for lo, hi, kind in spans:
            if lo < atom['end'] and hi > atom['start']:
                cuts.update((max(lo, atom['start']), min(hi, atom['end'])))
        points = sorted(cuts)
        for lo, hi in zip(points, points[1:]):
            kind = next((k for a,b,k in spans if a <= lo and hi <= b), None)
            intervals.append((atom['text'][lo-atom['start']:hi-atom['start']], kind))
        if not any(k for _,k in intervals): continue
        parent = run.getparent(); at = parent.index(run)
        replacements = []
        for child in list(run):
            if child.tag == tag('rPr'): continue
            fragments = intervals if child is node else [(None,None)]
            for text, kind in fragments:
                clone = E.Element(tag('r'), attrib=dict(run.attrib))
                props = run.find(tag('rPr'))
                if props is not None: clone.append(deepcopy(props))
                if kind:
                    props = clone.find(tag('rPr'))
                    if props is None: props = E.SubElement(clone, tag('rPr'))
                    for name,value in [('color','C00000' if kind=='delete' else '008000'),
                                       ('strike','1' if kind=='delete' else '0'),
                                       ('u','single' if kind=='insert' else 'none')]:
                        old = props.find(tag(name))
                        if old is not None: props.remove(old)
                        E.SubElement(props,tag(name)).set(tag('val'),value)
                copy = deepcopy(child)
                if text is not None: put_text(copy,text)
                clone.append(copy); replacements.append(clone)
        parent.remove(run)
        for offset,clone in enumerate(replacements): parent.insert(at+offset,clone)


def build_diff_preview(data, paragraphs, language):
    preview = deepcopy(paragraphs)
    preview = [p for p in preview if not(p.get('inserted') and p.get('deleted'))]
    pairs = []
    for p in preview:
        if language == 'zh' and p.get('translationPolicy') != 'skip_reference':
            before = p.get('initialZh') or (p.get('originalEn','') if not p.get('zh') else '')
            after = p.get('zh') or p.get('en','')
        else: before,after = p.get('originalEn',''),p.get('en','')
        if p.get('inserted'): before = ''
        if p.get('deleted'): after = ''
        pairs.append((before,after))
    differences = display_diffs(pairs,language)
    changes = {}; changed = []
    for p, parts in zip(preview,differences):
        cursor=0; spans=[]; text=''
        for part in parts:
            value=part['value']; end=cursor+len(value)
            if part.get('removed') or part.get('added'):
                spans.append((cursor,end,'delete' if part.get('removed') else 'insert'))
            text+=value;cursor=end
        p.update(en=text,zh=text,deleted=False,stylePolicy='left')
        if spans:
            changed.append(p['id']);changes[p['id']]=spans
            p.update(units=[],originalUnits=[],targetUnits=[],groups=[])
        if language=='en': p['originalEn']=next(x['originalEn'] for x in paragraphs if x['id']==p['id'])
    # Original baseline must remain available to patch_paragraph/export checks.
    package=export_docx(data,preview)
    parts,root=load_package(package)
    elements=root.xpath('//w:body//w:p[not(ancestor::w:p)]',namespaces=NS)
    if len(elements)!=len(preview): raise DocumentError('差异页面结构定位失败')
    for p,element in zip(preview,elements):
        if p['id'] in changes: paint(element,changes[p['id']])
    parts['word/document.xml']=E.tostring(root,encoding='UTF-8',xml_declaration=True,standalone=True)
    out=BytesIO()
    with ZipFile(out,'w',ZIP_DEFLATED) as z:
        for name,payload in parts.items(): z.writestr(name,payload)
    return out.getvalue(),preview,changed
