from io import BytesIO
from copy import deepcopy
import pymupdf
from docx import Document
from lxml import etree as E
from server.documents import extract,load_package,tag,NS
from server.native_anchors import prepare_native_anchors
from server.native_layout import native_layout


def test_disposable_anchors_preserve_existing_bookmarks_and_text():
    doc=Document();p=doc.add_paragraph('Repeated ');p.add_run('123')
    start=E.Element(tag('bookmarkStart'));start.set(tag('name'),'UserBookmark');start.set(tag('id'),'99');p._p.insert(0,start)
    end=E.SubElement(p._p,tag('bookmarkEnd'));end.set(tag('id'),'99')
    out=BytesIO();doc.save(out);data=out.getvalue();paragraphs=extract(data);saved=deepcopy(paragraphs)
    anchored,metadata=prepare_native_anchors(data,paragraphs)
    assert paragraphs==saved
    _,before=load_package(data);_,after=load_package(anchored)
    assert before.xpath('//w:t/text()',namespaces=NS)==after.xpath('//w:t/text()',namespaces=NS)
    assert after.xpath('//w:bookmarkStart[@w:name="UserBookmark"]/@w:id',namespaces=NS)==['99']
    names=after.xpath('//w:bookmarkStart/@w:name',namespaces=NS)
    assert len(set(names))==len(names)
    assert metadata[0]['nativeAnchors']['text']==paragraphs[0]['en']


def test_native_points_disambiguate_identical_numeric_cells(tmp_path):
    pdf=tmp_path/'sample.pdf';doc=pymupdf.open();page=doc.new_page()
    page.insert_text((40,60),'123');page.insert_text((200,60),'123')
    doc.set_toc([[1,'a',1,{'kind':1,'page':0,'to':pymupdf.Point(40,48)}],
                 [1,'b',1,{'kind':1,'page':0,'to':pymupdf.Point(200,48)}]])
    doc.save(pdf);doc.close()
    paragraphs=[]
    for name in ['a','b']:
        paragraphs.append({'id':name,'en':'123','units':[{'id':name+'s','text':'123','start':0,'end':3}],
            'nativeAnchors':{'paragraph':name,'text':'123','inTable':True,'cellWidth':60,'runs':[{'name':name,'text':'123','start':0,'end':3}]}})
    result=native_layout(pdf,paragraphs,tmp_path/'cache',0)
    regions=result['pages'][0]['regions'];assert result['unmapped']==[]
    assert len(regions)==2 and all(r['status']=='word-text' for r in regions)
    assert regions[0]['rects'][0][0]==40 and regions[1]['rects'][0][0]==200
    assert regions[0]['units'][0]['id']=='as' and regions[1]['units'][0]['id']=='bs'


def test_missing_object_text_is_only_an_explicit_anchor(tmp_path):
    pdf=tmp_path/'sample.pdf';doc=pymupdf.open();doc.new_page()
    doc.set_toc([[1,'object',1,{'kind':1,'page':0,'to':pymupdf.Point(40,80)}]])
    doc.save(pdf);doc.close()
    p={'id':'p1','en':'⟦P000⟧','nativeAnchors':{'paragraph':'object','text':'⟦P000⟧','runs':[]}}
    result=native_layout(pdf,[p],tmp_path/'cache',0)
    region=result['pages'][0]['regions'][0]
    assert region['status']=='word-anchor' and region['units']==[]
    assert region['rects']==[[40,80,48,88]]


def test_bookmark_prefix_collision_is_avoided(monkeypatch):
    from types import SimpleNamespace
    import server.native_anchors as module
    monkeypatch.setattr(module,'sha256',lambda data:SimpleNamespace(hexdigest=lambda:'deadbeef'+'0'*56))
    doc=Document();p=doc.add_paragraph('Native test text.')
    mark=E.Element(tag('bookmarkStart'));mark.set(tag('name'),'PBdeadbeefP00000');mark.set(tag('id'),'9');p._p.insert(0,mark)
    end=E.SubElement(p._p,tag('bookmarkEnd'));end.set(tag('id'),'9')
    b=BytesIO();doc.save(b);data=b.getvalue()
    output,metadata=prepare_native_anchors(data,extract(data))
    assert metadata[0]['nativeAnchors']['paragraph'].startswith('PBdeadbeefX')
    _,root=load_package(output)
    assert root.xpath('//w:bookmarkStart[@w:name="PBdeadbeefP00000"]',namespaces=NS)


def test_repeated_short_text_on_different_pages_and_stale_units(tmp_path):
    pdf=tmp_path/'pages.pdf';doc=pymupdf.open()
    for _ in range(2):doc.new_page().insert_text((40,60),'Short')
    doc.set_toc([[1,'first',1,{'kind':1,'page':0,'to':pymupdf.Point(40,48)}],
                 [1,'second',2,{'kind':1,'page':1,'to':pymupdf.Point(40,48)}]])
    doc.save(pdf);doc.close()
    ps=[]
    for name in ['first','second']:
        ps.append({'id':name,'en':'Short','units':[{'id':'u','start':1,'end':6,'text':'Short'}],
                   'nativeAnchors':{'paragraph':name,'text':'Short','runs':[{'name':name,'text':'Short','start':0,'end':5}]}})
    result=native_layout(pdf,ps,tmp_path/'cache',0)
    assert result['unmapped']==[]
    assert result['pages'][0]['regions'][0]['paragraphId']=='first'
    assert result['pages'][1]['regions'][0]['paragraphId']=='second'
    assert all(not r['units'] for page in result['pages'] for r in page['regions'])


def test_repacking_does_not_change_native_bookmark_identity():
    from zipfile import ZipFile,ZipInfo
    doc=Document();doc.add_paragraph('Stable bookmark text.');stream=BytesIO();doc.save(stream)
    data=stream.getvalue();ps=extract(data);other=BytesIO()
    with ZipFile(BytesIO(data)) as before,ZipFile(other,'w') as after:
        for name in before.namelist():after.writestr(ZipInfo(name,(2020,1,1,0,0,0)),before.read(name))
    a,ma=prepare_native_anchors(data,ps);b,mb=prepare_native_anchors(other.getvalue(),ps)
    assert ma[0]['nativeAnchors']==mb[0]['nativeAnchors']
