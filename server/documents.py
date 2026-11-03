"""Conservative, original-package DOCX patches. Never reconstruct the document."""
from __future__ import annotations

from copy import deepcopy
from difflib import SequenceMatcher
from hashlib import sha256
from io import BytesIO
import re
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree as E

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}
def tag(name): return f'{{{W}}}{name}'
TOKEN = re.compile(r'⟦P\d+⟧')

class DocumentError(ValueError): pass

def load_package(data: bytes):
    if len(data) > 40 * 1024 * 1024: raise DocumentError('文件超过 40 MB')
    with ZipFile(BytesIO(data)) as z:
        if len(z.infolist()) > 10000 or sum(x.file_size for x in z.infolist()) > 250 * 1024 * 1024:
            raise DocumentError('Word 解压大小超限')
        if len(set(z.namelist())) != len(z.namelist()): raise DocumentError('重复的 ZIP 部件')
        parts = {x.filename: z.read(x) for x in z.infolist()}
    if 'word/document.xml' not in parts: raise DocumentError('不是支持的 Word DOCX')
    parser = E.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    root = E.fromstring(parts['word/document.xml'], parser)
    if root.xpath('//w:ins|//w:del|//w:moveFrom|//w:moveTo', namespaces=NS):
        raise DocumentError('文档含未接受的 Word 修订，请先在副本中处理修订后导入；系统不会自动接受或拒绝。')
    return parts, root

def style_key(node):
    run = node.getparent()
    while run is not None and run.tag != tag('r'): run = run.getparent()
    pr = run.find(tag('rPr')) if run is not None else None
    # Include containing hyperlink, so its boundary cannot be crossed silently.
    parent = run.getparent() if run is not None else None
    link = E.tostring(parent, method='c14n').decode() if parent is not None and parent.tag == tag('hyperlink') else ''
    return (E.tostring(pr, method='c14n').decode() if pr is not None else '') + link

def css_style(node):
    r = node.getparent()
    while r is not None and r.tag != tag('r'): r = r.getparent()
    pr = r.find(tag('rPr')) if r is not None else None
    out = {}
    if pr is None: return out
    for n, css, value in [('b', 'fontWeight', 'bold'), ('i', 'fontStyle', 'italic')]:
        el = pr.find(tag(n))
        if el is not None and el.get(tag('val')) not in ('0', 'false'): out[css] = value
    color = pr.find(tag('color'))
    if color is not None and re.fullmatch(r'[0-9a-fA-F]{6}', color.get(tag('val'), '')): out['color'] = '#' + color.get(tag('val'))
    size = pr.find(tag('sz'))
    if size is not None:
        try: out['fontSize'] = f'{int(size.get(tag("val"))) / 2}pt'
        except (ValueError, TypeError): pass
    va = pr.find(tag('vertAlign'))
    if va is not None: out['verticalAlign'] = {'superscript': 'super', 'subscript': 'sub'}.get(va.get(tag('val')), 'baseline')
    return out

def atoms(paragraph):
    result, field = [], 0
    def protected(node):
        result.append({'node': node, 'text': f'⟦P{sum(a["protected"] for a in result):03}⟧', 'protected': True, 'style': {}})
    def walk(node):
        nonlocal field
        if node.tag == tag('pPr') or node.tag == tag('rPr'): return
        if node.tag == tag('r'):
            markers = node.findall(tag('fldChar'))
            if markers or field:
                protected(node)
                for m in markers:
                    kind = m.get(tag('fldCharType'))
                    if kind == 'begin': field += 1
                    if kind == 'end': field = max(0, field - 1)
                return
            for child in node: walk(child)
        elif node.tag == tag('hyperlink'):
            for child in node: walk(child)
        elif node.tag == tag('t'):
            result.append({'node': node, 'text': node.text or '', 'protected': False, 'style': css_style(node)})
        else: protected(node)
    for child in paragraph: walk(child)
    cursor = 0
    for a in result:
        a['start'], a['end'] = cursor, cursor + len(a['text']); cursor = a['end']
    return result

def split_units(text, prefix):
    """Offsets are Python Unicode code points; preserve every character exactly."""
    boundaries = []
    abbreviations = {'dr.', 'mr.', 'mrs.', 'prof.', 'fig.', 'figs.', 'eq.', 'eqs.', 'al.', 'vs.', 'e.g.', 'i.e.', 'etc.'}
    # Machine translations can place ASCII punctuation directly before Han
    # characters (e.g. a preserved formula followed by '.然而'). Keep the
    # existing decimal/abbreviation safeguards while recognizing this boundary.
    for m in re.finditer(r'[.!?。！？]+[\"”’\)\]]*(?:\s+|$)|[.!?]+[\"”’\)\]]*(?=[\u3400-\u9fff])|[。！？]+', text):
        end = m.end(); before = text[:m.start()+1]
        tail = re.search(r'[A-Za-z]+(?:\.[A-Za-z]+)*\.$', before)
        word = tail.group().lower() if tail else ''
        if word in abbreviations or re.search(r'(?:\b[A-Za-z]\.){1,}$', before): continue
        boundaries.append(end)
    boundaries.append(len(text))
    units, start = [], 0
    for end in sorted(set(boundaries)):
        if end > start:
            units.append({'id': f'{prefix}s{len(units)+1}', 'text': text[start:end], 'start': start, 'end': end}); start = end
    return units

def extract(data):
    parts, root = load_package(data)
    paragraphs = []
    # Exclude nested text-box paragraphs: preserve their outer drawing as one object.
    elements = root.xpath('//w:body//w:p[not(ancestor::w:p)]', namespaces=NS)
    for i, p in enumerate(elements):
        aa = atoms(p); text = ''.join(a['text'] for a in aa); pid = f'p{i+1:05}'
        pstyle = p.find('w:pPr/w:pStyle', NS)
        paragraphs.append({'id': pid, 'index': i, 'originalEn': text, 'en': text,
            'zh': '', 'initialZh': '', 'draftZh': '', 'units': split_units(text, pid + '_'),
            'groups': [], 'status': 'untranslated' if text.strip() else 'ready', 'revision': 0,
            'deleted': False, 'inserted': False, 'inheritFrom': None,
            'container': 'table' if any(a.tag == tag('tc') for a in p.iterancestors()) else 'body',
            'paragraphStyle': pstyle.get(tag('val')) if pstyle is not None else 'Normal',
            'runs': [{k: a[k] for k in ('text', 'start', 'end', 'protected', 'style')} for a in aa],
            'protected': TOKEN.findall(text), 'hasSection': p.find('w:pPr/w:sectPr', NS) is not None})
    from .reference_policy import detect_references
    return detect_references(paragraphs)

def extract_layout(data):
    """Reading-order document tree; IDs share the immutable extraction baseline."""
    _, root = load_package(data)
    elements = root.xpath('//w:body//w:p[not(ancestor::w:p)]', namespaces=NS)
    ids = {p: f'p{i+1:05}' for i, p in enumerate(elements)}
    def integer(el, default=1):
        try: return max(0, int(el.get(tag('val')))) if el is not None else default
        except (ValueError, TypeError): return default
    def blocks(parent):
        result = []
        for child in parent:
            if child.tag == tag('p') and child in ids:
                result.append({'type': 'paragraph', 'id': ids[child]})
            elif child.tag == tag('tbl'):
                result.append(table(child))
            elif child.tag in (tag('sdt'), tag('sdtContent'), tag('customXml')):
                result.extend(blocks(child))
        return result
    def table(node):
        rows, previous = [], {}
        for tr in node.findall(tag('tr')):
            cells, current = [], {}
            col = integer(tr.find('w:trPr/w:gridBefore', NS), 0)
            if col:
                cells.append({'colSpan': col, 'rowSpan': 1, 'blocks': [], 'omitted': True})
            for tc in tr.findall(tag('tc')):
                span = max(1, integer(tc.find('w:tcPr/w:gridSpan', NS)))
                merge = tc.find('w:tcPr/w:vMerge', NS)
                content = blocks(tc)
                origin = previous.get(col)
                if merge is not None and merge.get(tag('val')) != 'restart' and origin and origin['colSpan'] == span:
                    origin['rowSpan'] += 1
                    origin['blocks'].extend(content)
                    cell = origin
                else:
                    cell = {'colSpan': span, 'rowSpan': 1, 'blocks': content}
                    cells.append(cell)
                if merge is not None:
                    current[col] = cell
                col += span
            rows.append({'cells': cells})
            previous = current
        widths = []
        for item in node.findall('w:tblGrid/w:gridCol', NS):
            try: widths.append(int(item.get(tag('w'), '0')))
            except ValueError: widths.append(0)
        return {'type': 'table', 'rows': rows, 'columnWidths': widths}
    return blocks(root.find(tag('body')))


def put_text(node, text):
    node.text = text
    node.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')

def patch_paragraph(p, new_text, style_policy=None):
    aa = atoms(p); old = ''.join(a['text'] for a in aa)
    if TOKEN.findall(old) != TOKEN.findall(new_text): raise DocumentError('保护对象不可新增、删除或重排')
    ops = list(SequenceMatcher(None, old, new_text, autojunk=False).get_opcodes())
    for kind, a, b, c, d in reversed(ops):
        if kind == 'equal': continue
        touched = [x for x in aa if x['start'] < b and x['end'] > a]
        if any(x['protected'] for x in touched): raise DocumentError('修改穿过保护对象，请调整编辑范围')
        replacement = new_text[c:d]
        if replacement and touched and len({style_key(x['node']) for x in touched}) > 1 and style_policy not in ('left', 'right'):
            raise DocumentError('跨不同格式的替换需指定继承来源：左侧或右侧')
        for x in touched:
            lo, hi = max(a, x['start']) - x['start'], min(b, x['end']) - x['start']
            current = x['node'].text or ''
            put_text(x['node'], current[:lo] + current[hi:])
        if replacement:
            candidates = [x for x in aa if not x['protected'] and x['start'] <= a <= x['end']]
            chosen = (touched[-1] if style_policy == 'right' else touched[0]) if touched else ((candidates[-1] if style_policy=='right' else candidates[0]) if candidates else None)
            if chosen is None:
                # No editable run at this boundary; create plain run at paragraph end only.
                if a != len(old): raise DocumentError('保护对象边界没有可继承文字格式')
                run = E.SubElement(p, tag('r')); node = E.SubElement(run, tag('t')); put_text(node, replacement)
            else:
                offset = max(0, a - chosen['start']) if chosen is (touched[0] if touched else chosen) else 0
                current = chosen['node'].text or ''
                put_text(chosen['node'], current[:offset] + replacement + current[offset:])

def export_docx(data, paragraphs):
    parts, root = load_package(data)
    elements = root.xpath('//w:body//w:p[not(ancestor::w:p)]', namespaces=NS)
    original_map = {f'p{i+1:05}': p for i, p in enumerate(elements)}
    mapping = dict(original_map)
    for item in paragraphs:
        if item['inserted']:
            if item['deleted']: continue
            origin = mapping.get(item['inheritFrom'])
            if origin is None or origin.getparent().tag != tag('body'):
                raise DocumentError('首期新增段落必须以正文段落为锚点')
            p = E.Element(tag('p'))
            pr = origin.find(tag('pPr'))
            if pr is not None:
                pr = deepcopy(pr)
                for el in list(pr):
                    if el.tag == tag('sectPr'): pr.remove(el)
                p.append(pr)
            run = E.SubElement(p, tag('r'))
            props = origin.find('w:r/w:rPr', NS)
            if props is not None: run.append(deepcopy(props))
            put_text(E.SubElement(run, tag('t')), item['en'])
            origin.addnext(p); mapping[item['id']] = p
        else:
            p = mapping[item['id']]
            if item['deleted']:
                if item['protected'] or item['hasSection'] or item['container'] != 'body':
                    raise DocumentError('带对象、分节符或位于表格中的段落不能直接删除')
            elif item['en'] != item['originalEn']:
                patch_paragraph(p, item['en'], item.get('stylePolicy'))
    for item in paragraphs:
        if item['deleted'] and not item['inserted']:
            p = mapping[item['id']]; p.getparent().remove(p)
    # Nothing changed: return exact original archive.
    if all(not p['inserted'] and not p['deleted'] and p['en'] == p['originalEn'] for p in paragraphs): return data
    parts['word/document.xml'] = E.tostring(root, encoding='UTF-8', xml_declaration=True, standalone=True)
    out = BytesIO()
    with ZipFile(out, 'w', ZIP_DEFLATED) as z:
        for path, payload in parts.items(): z.writestr(path, payload)
    return out.getvalue()

def build_chinese_preview(data, paragraphs):
    """Disposable translated layout copy; never a replacement for English export.

    Inherits the first affected run style for translated spans. Exact semantic
    emphasis across languages is not inferred. Untranslated paragraphs stay English.
    """
    preview = deepcopy(paragraphs)
    for item in preview:
        if item.get('deleted'):
            continue
        if item.get('translationPolicy') == 'skip_reference':
            continue
        if item.get('status') in ('pending', 'running', 'failed', 'needs_alignment', 'conflict') or item.get('draftZh', '') != item.get('zh', ''):
            raise DocumentError('中文页面有未同步修改，请先完成回写。')
        if item.get('zh') or item.get('status') == 'ready':
            item['en'] = item.get('zh', '')
        item['stylePolicy'] = 'left'
    return export_docx(data, preview)


def package_hashes(data):
    with ZipFile(BytesIO(data)) as z: return {n: sha256(z.read(n)).hexdigest() for n in z.namelist()}
