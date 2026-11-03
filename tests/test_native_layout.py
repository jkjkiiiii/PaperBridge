from pathlib import Path
import pytest
import pymupdf
from server.native_layout import native_layout, raster_page

def make_pdf(path):
    doc=pymupdf.open();page=doc.new_page()
    page.insert_text((40,50),'A unique scientific sentence.')
    page.insert_text((40,80),'123 123')
    page.insert_text((40,110),'Repeated paragraph text.')
    page.insert_text((40,140),'Repeated paragraph text.')
    doc.save(path);doc.close()

def test_unique_geometry_and_ambiguous_downgrade(tmp_path):
    pdf=tmp_path/'source.pdf';make_pdf(pdf)
    paragraphs=[{'id':str(i),'en':t,'originalEn':t} for i,t in enumerate(['A unique scientific sentence.','123','Repeated paragraph text.','Unknown paragraph text.'])]
    result=native_layout(pdf,paragraphs,tmp_path/'cache',3)
    assert result['revision']==3
    assert [r['paragraphId'] for r in result['pages'][0]['regions']]==['0']
    assert result['unmapped']==['1','2','3']
    rect=result['pages'][0]['regions'][0]['rects'][0]
    assert 39<=rect[0]<=41 and 35<rect[1]<50 and rect[2]>100
    assert raster_page(tmp_path/'cache',result['key'],0).read_bytes().startswith(b'\x89PNG')
    with pytest.raises(ValueError): raster_page(tmp_path/'cache','../source',0)
    with pytest.raises(ValueError): raster_page(tmp_path/'cache',result['key'],99)

def test_duplicate_source_and_protected_paragraphs_not_mapped(tmp_path):
    pdf=tmp_path/'source.pdf';make_pdf(pdf)
    text='A unique scientific sentence.'
    result=native_layout(pdf,[{'id':'a','en':text},{'id':'b','en':text},{'id':'c','en':'⟦P000⟧'}],tmp_path/'cache',0)
    assert result['pages'][0]['regions']==[]
    assert result['unmapped']==['a','b','c']

def test_native_api_snapshot_and_raster(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    import server.app as api
    pdf=tmp_path/'sample.pdf';make_pdf(pdf)
    project={'revision':7,'paragraphs':[{'id':'p1','en':'A unique scientific sentence.','originalEn':'A unique scientific sentence.'}]}
    monkeypatch.setattr(api,'DATA',tmp_path)
    monkeypatch.setattr(api,'store',SimpleNamespace(get=lambda pid:project,source=lambda p:b'original',export=lambda p:b'current'))
    monkeypatch.setattr(api,'render_preview',lambda data,cache:pdf)
    monkeypatch.setattr(api,'export_docx',lambda source,paragraphs:b'current')
    with TestClient(api.app) as client:
        response=client.get('/api/projects/demo/native-layout')
        assert response.status_code==200
        data=response.json();assert data['revision']==7
        png=client.get(data['pages'][0]['imageUrl'])
        assert png.status_code==200 and png.content.startswith(b'\x89PNG')
        assert client.get('/api/projects/demo/native-layout?language=fr').status_code==422
        assert client.get('/api/projects/demo/native-layout?language=zh&original=true').status_code==422
        assert client.get('/api/native-page/not-a-hash/0.png').status_code==404


def test_only_xml_verified_bookmarks_are_invisible(tmp_path):
    from server.documents import split_units, zero_width_bookmark_tokens, tag
    from docx import Document
    from lxml import etree as E
    from io import BytesIO
    d=Document();p=d.add_paragraph('A unique scientific sentence.')
    E.SubElement(p._p,tag('bookmarkStart')).set(tag('id'),'0')
    E.SubElement(p._p,tag('bookmarkEnd')).set(tag('id'),'0')
    E.SubElement(p._p,tag('drawing'))
    b=BytesIO();d.save(b)
    safe=zero_width_bookmark_tokens(b.getvalue())['p00001']
    assert safe==['⟦P000⟧','⟦P001⟧']
    pdf=tmp_path/'source.pdf';make_pdf(pdf)
    raw='A unique ⟦P000⟧scientific⟦P001⟧ sentence.'
    item={'id':'p1','en':raw,'units':split_units(raw,'u'),'zeroWidthBookmarkTokens':safe}
    result=native_layout(pdf,[item],tmp_path/'cache',0)
    assert result['unmapped']==[]
    assert len(result['pages'][0]['regions'][0]['units'])==1
    item['en'] += '⟦P002⟧'
    assert native_layout(pdf,[item],tmp_path/'cache',0)['unmapped']==['p1']
