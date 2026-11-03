"""Conservative reference-section detection without altering document text."""
import re

VERSION = 'references-v1'
HEADINGS = {'references', 'bibliography', 'reference list', 'works cited', '参考文献', '參考文獻'}


def clean_heading(text):
    text = re.sub(r'⟦P\d+⟧', '', text or '').strip()
    text = re.sub(r'^\s*(?:\d+(?:\.\d+)*[.、]?\s+)', '', text)
    return text.rstrip(':：').strip().casefold()


def heading_level(item):
    match = re.search(r'heading\s*([1-9])', item.get('paragraphStyle', ''), re.I)
    return int(match.group(1)) if match else None


def detect_references(paragraphs):
    inside = False
    reference_level = None
    for item in paragraphs:
        heading = clean_heading(item.get('originalEn', item.get('en', '')))
        level = heading_level(item)
        is_title = heading in HEADINGS and item.get('container', 'body') == 'body'
        appendix = bool(re.match(r'^(?:appendi(?:x|ces)\b|附录|附錄)', heading, re.I))
        if inside and not is_title and (appendix or (level is not None and (reference_level is None or level <= reference_level))):
            inside = False
        if is_title:
            inside = True
            reference_level = level
        bibliography_style = bool(re.search(r'bibliograph|reference\s*entry|cs[ls].*bibliog', item.get('paragraphStyle', ''), re.I))
        detected = is_title or inside or bibliography_style
        item['referenceDetected'] = detected
        override = item.get('translationPolicyOverride')
        item['translationPolicy'] = override if override in ('translate', 'skip_reference') else ('skip_reference' if detected else 'translate')
        if item['translationPolicy'] == 'skip_reference':
            item['skipReason'] = 'manual' if override else ('bibliography-style' if bibliography_style else 'reference-section')
            # Old translations/drafts/history are retained, never silently erased.
            if not item.get('zh') and not item.get('draftZh') and item.get('en') == item.get('originalEn'):
                item.update(status='ready', units=[], targetUnits=[], groups=[], originalUnits=[])
        else:
            item.pop('skipReason', None)
    return paragraphs


def is_skipped_reference(item):
    return item.get('translationPolicy') == 'skip_reference'
