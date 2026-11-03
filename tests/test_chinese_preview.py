from copy import deepcopy
from io import BytesIO
from docx import Document
from lxml import etree as E
import pytest
from server.documents import extract, build_chinese_preview, package_hashes, DocumentError


def test_translation_preview_preserves_objects_and_source():
    d = Document()
    p = d.add_paragraph('Before ')
    m = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
    math = E.SubElement(p._p, '{'+m+'}oMath')
    r = E.SubElement(math, '{'+m+'}r')
    E.SubElement(r, '{'+m+'}t').text = 'x=1'
    p.add_run(' after.')
    d.add_table(rows=1, cols=2).cell(0, 0).text = '12/34'
    stream = BytesIO(); d.save(stream); source = stream.getvalue()
    items = extract(source)
    items[0].update(zh='前文 ⟦P000⟧ 后文。', draftZh='前文 ⟦P000⟧ 后文。', status='ready')
    before = deepcopy(items)
    result = build_chinese_preview(source, items)
    assert items == before
    assert extract(result)[0]['en'] == '前文 ⟦P000⟧ 后文。'
    a, b = package_hashes(source), package_hashes(result)
    assert all(b[k] == v for k, v in a.items() if k != 'word/document.xml')
    items[0]['draftZh'] = '未保存'
    with pytest.raises(DocumentError): build_chinese_preview(source, items)
