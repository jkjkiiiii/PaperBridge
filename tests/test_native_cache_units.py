from copy import deepcopy
import pymupdf
import server.native_layout as module
from server.documents import split_units


def test_sentence_rects_and_cache_invalidation(tmp_path, monkeypatch):
    text = 'First scientific sentence. Second scientific sentence.'
    pdf = tmp_path/'input.pdf'
    doc = pymupdf.open(); page = doc.new_page(); page.insert_text((40,50),text); doc.save(pdf); doc.close()
    paragraphs = [{'id':'p1','en':text,'units':split_units(text,'p1_')}]
    cache = tmp_path/'cache'
    first = module.native_layout(pdf,paragraphs,cache,1)
    units = first['pages'][0]['regions'][0]['units']
    assert len(units)==2
    assert units[0]['rects'][0][2] <= units[1]['rects'][0][0]
    original = module.geometry
    def fail(*args,**kwargs): raise AssertionError('cache hit parsed PDF')
    monkeypatch.setattr(module,'geometry',fail)
    second = module.native_layout(pdf,paragraphs,cache,2)
    assert second['cacheHit'] and second['revision']==2
    monkeypatch.setattr(module,'geometry',original)
    changed=deepcopy(paragraphs);changed[0]['units'][0]['id']='new-id'
    third=module.native_layout(pdf,changed,cache,3)
    assert not third['cacheHit'] and third['geometryKey']!=first['geometryKey']
    assert third['pages'][0]['regions'][0]['units'][0]['id']=='new-id'
    path=module.raster_page(cache,first['key'],0)
    monkeypatch.setattr(module.pymupdf,'open',fail)
    assert module.raster_page(cache,first['key'],0)==path


def test_bad_unit_offsets_disable_sentence_overlay(tmp_path):
    text='A scientific paragraph with uncertain units.'
    pdf=tmp_path/'input.pdf';doc=pymupdf.open();page=doc.new_page();page.insert_text((40,50),text);doc.save(pdf);doc.close()
    p={'id':'p','en':text,'units':[{'id':'bad','start':0,'end':5,'text':'wrong'}]}
    result=module.native_layout(pdf,[p],tmp_path/'cache',0)
    assert result['pages'][0]['regions'][0]['units']==[]
