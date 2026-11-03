"""Stable XML bookmarks in disposable render copies, resolved by Word to PDF points."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree as E
from hashlib import sha256
from .documents import load_package, atoms, tag, NS, DocumentError


def prepare_native_anchors(data, paragraphs, original=False):
    parts,root=load_package(data)
    nodes=root.xpath('//w:body//w:p[not(ancestor::w:p)]',namespaces=NS)
    display=[deepcopy(p) for p in paragraphs if not (p.get('inserted') if original else p.get('deleted'))]
    if len(nodes)!=len(display):raise DocumentError('原生页面段落结构与编辑索引不一致，无法建立安全锚点')
    numbers=[int(x.get(tag('id'))) for x in root.iter(tag('bookmarkStart')) if (x.get(tag('id')) or '').isdigit()]
    counter=max(numbers,default=0)+1
    existing={x.get(tag('name')) for x in root.iter(tag('bookmarkStart'))}
    # ZIP timestamps differ on each export; names must depend on package content.
    prefix='PB'+sha256(b''.join(name.encode('utf-8')+b'\0'+parts[name] for name in sorted(parts))).hexdigest()[:8]
    while any((name or '').startswith(prefix) for name in existing):prefix+='X'
    if len(prefix)>18:raise DocumentError('原生锚点命名冲突过多')
    def pair(name):
        nonlocal counter
        a=E.Element(tag('bookmarkStart'));a.set(tag('id'),str(counter));a.set(tag('name'),name)
        b=E.Element(tag('bookmarkEnd'));b.set(tag('id'),str(counter));counter+=1
        return a,b
    for index,(p,node) in enumerate(zip(display,nodes)):
        # One child per run lets bookmarks surround actual text, never formula internals.
        protected_runs={a['node'] for a in atoms(node) if a['protected'] and a['node'].tag==tag('r')}
        for run in list(node.iter(tag('r'))):
            owner=next((a for a in run.iterancestors() if a.tag==tag('p')),None)
            if run.getparent() is None or run in protected_runs or owner is not node:continue
            children=[x for x in run if x.tag!=tag('rPr')]
            if len(children)<2:continue
            parent=run.getparent();at=parent.index(run)
            for i,child in enumerate(children):
                clone=E.Element(tag('r'),attrib=dict(run.attrib));props=run.find(tag('rPr'))
                if props is not None:clone.append(deepcopy(props))
                clone.append(deepcopy(child));parent.insert(at+i,clone)
            parent.remove(run)
        aa=atoms(node);runs=[]
        actual=''.join(a['text'] for a in aa)
        expected=[p.get('originalEn','')] if original else [p.get('en',''),p.get('zh','')]
        if actual not in expected:raise DocumentError('原生页面段落文字与编辑索引不一致，拒绝猜测锚点')
        for j,atom in enumerate(aa):
            if atom['protected'] or not atom['text'].strip():continue
            name=f'{prefix}P{index:05}T{j:05}'
            run=atom['node'].getparent();parent=run.getparent()
            a,b=pair(name);at=parent.index(run);parent.insert(at,a);parent.insert(at+2,b)
            runs.append({'name':name,'start':atom['start'],'end':atom['end'],'text':atom['text']})
        name=f'{prefix}P{index:05}'
        a,b=pair(name);node.insert(1 if node.find(tag('pPr')) is not None else 0,a);node.append(b)
        cell=next((a for a in node.iterancestors() if a.tag==tag('tc')),None)
        width=None
        if cell is not None:
            tcw=cell.find('w:tcPr/w:tcW',NS)
            if tcw is not None and tcw.get(tag('type'))=='dxa':
                try:width=int(tcw.get(tag('w')))/20
                except (ValueError,TypeError):pass
        p['nativeAnchors']={'paragraph':name,'runs':runs,'text':''.join(x['text'] for x in aa),
                            'cellWidth':width,'inTable':cell is not None}
    parts['word/document.xml']=E.tostring(root,encoding='UTF-8',xml_declaration=True,standalone=True)
    out=BytesIO()
    with ZipFile(out,'w',ZIP_DEFLATED) as z:
        for name,payload in parts.items():z.writestr(name,payload)
    return out.getvalue(),display
