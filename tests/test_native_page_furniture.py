import pymupdf
from server.native_layout import geometry


def fixture(tmp_path, extra_body=False, duplicate=False):
    path = tmp_path / 'furniture.pdf'
    doc = pymupdf.open()
    for index in range(4 if duplicate else 2):
        page = doc.new_page()
        page.insert_text((40, 25), 'Repeated running header')
        text = 'A paragraph begins before the page break' if index % 2 == 0 else 'and continues after the page break.'
        page.insert_text((40, 200), text)
        if extra_body and index == 0:
            page.insert_text((40, 220), 'DO NOT SKIP THIS BODY TEXT')
        page.insert_text((290, 815), str(index + 1))
    doc.save(path); doc.close()
    return path


def test_cross_page_furniture_removed_without_highlighting_header(tmp_path):
    text = 'A paragraph begins before the page break and continues after the page break.'
    unit = {'id': 's1', 'start': 0, 'end': len(text), 'text': text}
    pages, unmapped = geometry(fixture(tmp_path), [{'id': 'p1', 'en': text, 'units': [unit]}])
    assert not unmapped
    for page in pages:
        region = page['regions'][0]
        assert region['status'] == 'cross-page-text'
        assert region['units'][0]['id'] == 's1'
        assert all(150 < r[1] < r[3] < 240 for r in region['rects'])


def test_does_not_skip_body_or_pick_duplicate_cross_page_match(tmp_path):
    paragraph = {'id': 'p1', 'en': 'A paragraph begins before the page break and continues after the page break.'}
    for options in ({'extra_body': True}, {'duplicate': True}):
        pages, unmapped = geometry(fixture(tmp_path, **options), [paragraph])
        assert unmapped == ['p1']
        assert not any(p['regions'] for p in pages)
