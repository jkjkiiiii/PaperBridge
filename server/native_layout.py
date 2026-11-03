"""Word PDF display geometry. Ambiguous content never receives a guessed anchor."""
from pathlib import Path
from hashlib import sha256
from collections import Counter, defaultdict
import re
import json
from uuid import uuid4
import unicodedata
import pymupdf

VERSION = b'native-layout-v7'
RASTER_VERSION = b'native-layout-v2'

def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text) if not c.isspace() and c not in '\u00ad\u200b')

def geometry(pdf: Path, paragraphs, original=False, language="en"):
    """Match whole unique paragraph strings; coordinates remain PDF page points."""
    document = pymupdf.open(pdf)
    pages = [{'width': p.rect.width, 'height': p.rect.height, 'regions': []} for p in document]
    records = []
    recurring = defaultdict(set)
    for page_index, page in enumerate(document):
        for block in page.get_text('rawdict')['blocks']:
            for line_index, line in enumerate(block.get('lines', [])):
                line_chars, line_positions = [], []
                for span in line.get('spans', []):
                    for char in span.get('chars', []):
                        text = normalized(char['c'])
                        for c in text:
                            line_chars.append(c)
                            line_positions.append((page_index, tuple(line['bbox']), tuple(char['bbox'])))
                text = ''.join(line_chars)
                top, bottom = line['bbox'][1], line['bbox'][3]
                band = 'top' if bottom < page.rect.height * .08 else ('bottom' if top > page.rect.height * .92 else None)
                number = bool(band and text in (str(page_index + 1), f'Page{page_index + 1}', f'Page{page_index + 1}of{len(document)}'))
                identity = (band, text, round(top / page.rect.height, 2))
                if band and text: recurring[identity].add(page_index)
                records.append((line_chars, line_positions, number, identity))
    chars, positions, body_chars, body_positions = [], [], [], []
    for line_chars, line_positions, number, identity in records:
        chars.extend(line_chars); positions.extend(line_positions)
        if not number and not (identity[0] and len(recurring[identity]) >= 2):
            body_chars.extend(line_chars); body_positions.extend(line_positions)
    full, body = ''.join(chars), ''.join(body_chars)
    anchors={}
    for _,name,_,destination in document.get_toc(False):
        if destination.get('kind')==1 and 'to' in destination:
            point=destination['to'];anchors[name]=(destination['page'],point.x,point.y)
    # Remove only PDF line-final hyphens for a secondary exact comparison.
    dehyphen_chars=[];dehyphen_positions=[]
    for i,(char,pos) in enumerate(zip(body_chars,body_positions)):
        if char in '-‐' and i+1<len(body_positions) and body_positions[i+1][1]!=pos[1] and i and body_chars[i-1].isalpha() and body_chars[i+1].isalpha():continue
        dehyphen_chars.append(char);dehyphen_positions.append(pos)
    native_streams=[(full,positions),(body,body_positions),(''.join(dehyphen_chars),dehyphen_positions)]
    def native_run(text,point,native):
        if not text or point is None:return None
        for stream,coords in native_streams:
            matches=[];start=stream.find(text)
            while start>=0:
                page,_,box=coords[start]
                width=native.get('cellWidth') if native.get('inTable') else (pages[point[0]]['width']-point[1] if native.get('inTable') is False else 8)
                origin=anchors.get(native.get('paragraph'),point)
                right=origin[1]+width-3 if native.get('inTable') and width else point[1]+max(8,(width or 8)-3)
                if page==point[0] and box[0]>=point[1]-3 and box[0]<=right and abs(box[1]-point[2])<=18:
                    matches.append(coords[start:start+len(text)])
                start=stream.find(text,start+1)
            if len(matches)==1:return matches[0]
            if len(matches)>1:return None
        return None
    def rects_for(selected):
        lines=defaultdict(list)
        for page,line,box in selected:lines[(page,line)].append(box)
        result=defaultdict(list)
        for (page,_),boxes in lines.items():
            result[page].append([min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)])
        return result
    eligible = []
    for p in paragraphs:
        if not original and p.get('deleted'): continue
        if original and p.get('inserted'): continue
        text = p.get('originalEn' if original else 'en', '')
        if language == 'zh' and not original and p.get('translationPolicy') != 'skip_reference': text = p.get('zh') or p.get('en', '')
        for token in p.get('zeroWidthBookmarkTokens', []): text = text.replace(token, '')
        eligible.append((p, normalized(text)))
    counts = Counter(text for _, text in eligible)
    unmapped = []
    for p, text in eligible:
        def visible(value):
            for token in p.get('zeroWidthBookmarkTokens', []): value = value.replace(token, '')
            return normalized(value)
        native=p.get('nativeAnchors')
        if native:
            raw=p.get('originalEn' if original else 'en','')
            units=p.get('originalUnits' if original else 'units',[])
            if language=='zh' and not original and p.get('translationPolicy')!='skip_reference':
                raw=p.get('zh') or p.get('en','');units=p.get('targetUnits',[]) if p.get('zh') else []
            selected=[];unit_coords=defaultdict(list);matched_runs=0
            valid_units=(native['text']==raw and ''.join(u.get('text','') for u in units)==raw)
            cursor=0
            for unit in units:
                lo,hi=unit.get('start'),unit.get('end')
                if not isinstance(lo,int) or not isinstance(hi,int) or lo!=cursor or hi<=lo or raw[lo:hi]!=unit.get('text'):
                    valid_units=False;break
                cursor=hi
            valid_units=valid_units and cursor==len(raw) and len({u.get('id') for u in units})==len(units)
            for run in native['runs']:
                content=normalized(run['text'])
                coords=native_run(content,anchors.get(run['name']),native)
                if coords is None:continue
                matched_runs+=1;selected.extend(coords)
                if valid_units:
                    for unit in units:
                        lo=max(run['start'],unit['start']);hi=min(run['end'],unit['end'])
                        if hi<=lo or raw[unit['start']:unit['end']]!=unit['text']:continue
                        prefix=normalized(run['text'][:lo-run['start']]);part=normalized(run['text'][lo-run['start']:hi-run['start']]);suffix=normalized(run['text'][hi-run['start']:])
                        if prefix+part+suffix==content:unit_coords[unit['id']].extend(coords[len(prefix):len(prefix)+len(part)])
            per_page=rects_for(selected)
            unit_pages=defaultdict(list)
            for uid,coords in unit_coords.items():
                for page,rects in rects_for(coords).items():unit_pages[page].append({'id':uid,'rects':rects})
            for page,rects in per_page.items():
                pages[page]['regions'].append({'paragraphId':p['id'],'rects':rects,'units':unit_pages[page],
                    'status':'word-text' if matched_runs==len(native['runs']) else 'word-text-partial'})
            if per_page:continue
            point=anchors.get(native['paragraph'])
            if point and text:
                page,x,y=point
                pages[page]['regions'].append({'paragraphId':p['id'],'rects':[[x,y,x+8,y+8]],'units':[],'status':'word-anchor'})
                continue
            # Empty source paragraphs intentionally have no invisible clickable area.
            if not text:unmapped.append(p['id']);continue
        # Very short and numeric-only text is not a reliable page anchor.
        if not text or '⟦' in text or counts[text] != 1 or len(text) < 8 or not any(c.isalpha() for c in text):
            unmapped.append(p['id']); continue
        start = full.find(text)
        matched_positions = positions
        status = 'unique-text'
        if start >= 0 and full.find(text, start + 1) >= 0:
            unmapped.append(p['id']); continue
        if start < 0:
            # Only recover cross-page matches by excluding evidenced margin
            # furniture. Never skip arbitrary body text or resolve duplicates.
            start = body.find(text)
            if start < 0 or body.find(text, start + 1) >= 0 or len({v[0] for v in body_positions[start:start + len(text)]}) < 2:
                unmapped.append(p['id']); continue
            matched_positions = body_positions
            status = 'cross-page-text'
        def rectangles(selected):
            lines = defaultdict(list)
            for page_index, line, box in selected:
                lines[(page_index, line)].append(box)
            by_page = defaultdict(list)
            for (page_index, _), boxes in lines.items():
                by_page[page_index].append([min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)])
            return by_page
        by_page = rectangles(matched_positions[start:start + len(text)])
        unit_pages = defaultdict(list)
        raw = p.get('originalEn' if original else 'en', '')
        units = p.get('originalUnits' if original else 'units', [])
        if language == 'zh' and not original and p.get('translationPolicy') != 'skip_reference':
            raw = p.get('zh') or p.get('en', '')
            units = p.get('targetUnits', []) if p.get('zh') else []
        # Every unit must exactly cover its source range. Unknown/obsolete units
        # downgrade to paragraph mapping, never search for a repeated sentence.
        cursor = 0
        valid = bool(units) and p.get('translationPolicy') != 'skip_reference'
        for unit in units:
            lo, hi = unit.get('start'), unit.get('end')
            if not isinstance(lo, int) or not isinstance(hi, int) or lo != cursor or hi <= lo or hi > len(raw) or raw[lo:hi] != unit.get('text'):
                valid = False; break
            cursor = hi
        valid = valid and cursor == len(raw) and len({u.get('id') for u in units}) == len(units)
        if valid:
            for unit in units:
                lo, hi = unit['start'], unit['end']
                prefix, content, suffix = visible(raw[:lo]), visible(raw[lo:hi]), visible(raw[hi:])
                # Normalization can combine characters across a boundary. Only
                # accept offsets when normalization is compositional here.
                if prefix + content + suffix != text: continue
                for page_index, rects in rectangles(matched_positions[start+len(prefix):start+len(prefix)+len(content)]).items():
                    unit_pages[page_index].append({'id': unit['id'], 'rects': rects})
        for page_index, rects in by_page.items():
            pages[page_index]['regions'].append({'paragraphId': p['id'], 'rects': rects, 'units': unit_pages[page_index], 'status': status})
    document.close()
    return pages, unmapped

def atomic_write(path, payload):
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        temporary.write_bytes(payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def native_layout(pdf: Path, paragraphs, cache: Path, revision: int, original=False, language="en"):
    data = pdf.read_bytes()
    # Geometry fixes do not invalidate unchanged page PNGs.
    key = sha256(RASTER_VERSION + data).hexdigest()
    folder = cache / key
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / 'source.pdf'
    if not target.exists(): atomic_write(target, data)
    # Layout is independent of project bookkeeping revision, but sentence IDs,
    # offsets and correspondence groups must invalidate its semantic overlay.
    fields = ('id', 'originalEn', 'en', 'zh', 'inserted', 'deleted', 'units', 'originalUnits', 'targetUnits', 'groups', 'translationPolicy', 'zeroWidthBookmarkTokens', 'nativeAnchors')
    signature = {'original': original, 'language': language,
        'paragraphs': [{k:p.get(k) for k in fields} for p in paragraphs]}
    geometry_key = sha256(VERSION + json.dumps(signature, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    geometry_file = folder / (geometry_key + '.json')
    cache_hit = False
    try:
        value = json.loads(geometry_file.read_text('utf-8'))
        pages, unmapped = value['pages'], value['unmapped']
        cache_hit = True
    except (OSError, ValueError, KeyError, TypeError):
        pages, unmapped = geometry(target, paragraphs, original, language)
        atomic_write(geometry_file, json.dumps({'pages':pages,'unmapped':unmapped}, ensure_ascii=False).encode('utf-8'))
    for i, page in enumerate(pages):
        page['imageUrl'] = f'/api/native-page/{key}/{i}.png'
    return {'revision': revision, 'key': key, 'geometryKey': geometry_key, 'cacheHit': cache_hit,
        'original': original, 'language': language, 'pages': pages, 'unmapped': unmapped}


def raster_page(cache: Path, key: str, page: int):
    if not re.fullmatch(r'[a-f0-9]{64}', key) or page < 0: raise ValueError('Invalid page')
    folder = cache / key
    pdf = folder / 'source.pdf'
    if not pdf.exists(): raise ValueError('Page snapshot not found')
    output = folder / f'{page}.png'
    if output.exists() and output.stat().st_size > 0:
        return output
    with pymupdf.open(pdf) as doc:
        if page >= len(doc): raise ValueError('Page out of range')
        if not output.exists():
            # Memory stays bounded by one page; images are requested lazily.
            pix = doc[page].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
            atomic_write(output, pix.tobytes('png'))
    return output
