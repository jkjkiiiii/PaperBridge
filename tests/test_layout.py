from io import BytesIO
from docx import Document
from server.documents import extract, extract_layout
from server.state import Store
from server.state import preserve_numeric_cell
from copy import deepcopy


def sample():
    doc = Document()
    doc.add_paragraph('Before')
    table = doc.add_table(rows=3, cols=3)
    table.cell(0, 0).merge(table.cell(0, 1)).text = 'Wide heading'
    table.cell(1, 0).merge(table.cell(2, 0)).text = 'Tall heading'
    table.cell(1, 1).text = '1.0'
    table.cell(2, 1).text = '1.0'
    nested = table.cell(2, 2).add_table(rows=1, cols=1)
    nested.cell(0, 0).text = 'Nested'
    doc.add_paragraph('After')
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


def paragraph_ids(blocks):
    for node in blocks:
        if node['type'] == 'paragraph':
            yield node['id']
        else:
            for row in node['rows']:
                for cell in row['cells']:
                    yield from paragraph_ids(cell['blocks'])


def test_layout_preserves_all_ids_and_merged_nested_cells():
    data = sample()
    layout = extract_layout(data)
    ids = list(paragraph_ids(layout))
    assert sorted(ids) == sorted(p['id'] for p in extract(data))
    assert len(set(ids)) == len(ids)
    table = layout[1]
    assert table['rows'][0]['cells'][0]['colSpan'] == 2
    assert table['rows'][1]['cells'][0]['rowSpan'] == 2
    assert len(table['rows'][2]['cells']) == 2
    assert any(b['type'] == 'table' for b in table['rows'][2]['cells'][1]['blocks'])


def test_existing_project_lazy_layout_preserves_edits(tmp_path):
    store = Store(tmp_path)
    project = store.create(sample(), 'test.docx')
    project.pop('layout')
    project['paragraphs'][0]['zh'] = '已有译文'
    project['paragraphs'][0]['status'] = 'ready'
    store.save(project)
    loaded = store.get(project['id'])
    assert loaded['layout'][1]['type'] == 'table'
    assert loaded['paragraphs'][0]['zh'] == '已有译文'
    store.draft(loaded, loaded['paragraphs'][0]['id'], '新草稿', 0)
    assert store.get(project['id'])['layout'] == loaded['layout']


def test_numeric_table_identity_and_conservative_migration(tmp_path):
    store = Store(tmp_path)
    project = store.create(sample(), 'numeric.docx')
    cell = next(p for p in project['paragraphs'] if p['en'] == '1.0')
    assert cell['zh'] == cell['draftZh'] == '1.0'
    assert cell['status'] == 'ready' and cell['groups'][0]['kind'] == '1:1'
    old = deepcopy(cell)
    old.pop('numericIdentity')
    old.update(originalEn='11/14/9', en='11/14/9', zh='日期', draftZh='日期')
    from server.documents import split_units
    old['units'] = split_units(old['en'], old['id'] + '_')
    snapshot = deepcopy(old)
    snapshot.update(status='untranslated', zh='', draftZh='')
    old['history'] = [snapshot]
    assert preserve_numeric_cell(old)
    assert old['zh'] == '11/14/9'
    changed = deepcopy(old)
    changed.update(zh='人为编辑', draftZh='人为编辑')
    assert not preserve_numeric_cell(changed, [{'paragraphId':changed['id'], 'type':'edit_chinese'}])
    assert changed['zh'] == '人为编辑'
    changed['draftZh'] = '未提交编辑'
    assert not preserve_numeric_cell(changed)
