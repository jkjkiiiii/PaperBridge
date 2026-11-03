from copy import deepcopy
from io import BytesIO
from docx import Document
from server.documents import extract,load_package,NS,export_docx
from server.diff_preview import build_diff_preview,display_diffs


def fixture():
    doc=Document();p=doc.add_paragraph();p.add_run('I love ').bold=True;p.add_run('you. We live here.')
    doc.add_paragraph('Deleted paragraph.')
    out=BytesIO();doc.save(out)
    data=out.getvalue();ps=extract(data)
    for p in ps:p.update(initialZh='',zh='')
    return data,ps


def test_visual_diff_is_disposable_and_retains_deleted_paragraph():
    data,ps=fixture();ps[0]['en']='I love her. We live here.';ps[1]['deleted']=True
    saved=deepcopy(ps);normal=export_docx(data,ps)
    diff,geometry,changed=build_diff_preview(data,ps,'en')
    assert ps==saved and export_docx(data,ps)==normal
    assert changed==['p00001','p00002']
    assert [p['en'] for p in extract(diff)]==['I love youher. We live here.','Deleted paragraph.']
    assert all(not p['deleted'] for p in geometry)
    assert geometry[0]['units']==[]
    _,root=load_package(diff)
    red=root.xpath('//w:r[w:rPr/w:color[@w:val="C00000"]]/w:t/text()',namespaces=NS)
    green=root.xpath('//w:r[w:rPr/w:color[@w:val="008000"]]/w:t/text()',namespaces=NS)
    assert ''.join(red)=='youDeleted paragraph.' and ''.join(green)=='her'
    assert root.xpath('//w:r[w:t="I love "]/w:rPr/w:b',namespaces=NS)


def test_insert_and_chinese_baseline():
    data,ps=fixture();ps[0].update(initialZh='我爱你。',zh='我爱她。')
    ps[1].update(initialZh='第二段。',zh='第二段。')
    inserted=deepcopy(ps[1]);inserted.update(id='new1',inserted=True,inheritFrom=ps[1]['id'],originalEn='',en='New paragraph.',zh='新增段落。',initialZh='')
    ps.append(inserted)
    diff,geometry,changed=build_diff_preview(data,ps,'zh')
    assert [p['en'] for p in extract(diff)]==['我爱你她。','第二段。','新增段落。']
    assert changed==['p00001','new1']
    assert geometry[1]['en']=='第二段。'


def test_english_word_and_inflection_policy_matches_structure_view():
    parts=display_diffs([('work','worked'),('cat','car')],'en')
    assert [(p['value'],bool(p.get('added')),bool(p.get('removed'))) for p in parts[0]]==[('work',False,False),('ed',True,False)]
    assert parts[1]==[{'value':'cat','removed':True},{'value':'car','added':True}]
