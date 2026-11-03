from copy import deepcopy
import pytest
from server.state import Store, validate_links, StateError, impact
from server.app import translation_candidate, rewrite_candidate
from server.documents import split_units
from test_documents import fixture_doc

def ready(tmp_path):
    store=Store(tmp_path);p=store.create(fixture_doc(),'sample.docx');item=p['paragraphs'][1]
    ids=[x['id'] for x in item['units']]
    data={'target_units':[{'id':'z1','text':'我爱你。','source_ids':[ids[0]]},{'id':'z2','text':'我们住在北京。','source_ids':[ids[1]]}],'unresolved':[]}
    new=translation_candidate(item,data);p['paragraphs'][1]=new;store.save(p);return store,p,new

def test_mapping_minimal_components():
    s=[{'id':'e1'},{'id':'e2'}];t=[{'id':'z1'},{'id':'z2'}]
    independent=[{'source_ids':['e1'],'target_ids':['z1']},{'source_ids':['e2'],'target_ids':['z2']}]
    assert len(validate_links(s,t,independent))==2
    crossed=[{'source_ids':['e1','e2'],'target_ids':['z1']},{'source_ids':['e1','e2'],'target_ids':['z2']}]
    assert validate_links(s,t,crossed)[0]['kind']=='2:2'
    with pytest.raises(StateError):validate_links(s,t,independent[:1])

def test_word_rewrite_and_lock(tmp_path):
    store,p,item=ready(tmp_path);store.draft(p,item['id'],'我爱她。我们住在北京。',item['revision']);item=p['paragraphs'][1]
    allowed,anchors=impact(item);assert allowed==[item['units'][0]['id']]
    target=split_units(item['draftZh'],'z');units=deepcopy(item['units']);units[0]['text']='I love her. '
    data={'english_units':units,'links':[{'source_ids':[u['id']],'target_ids':[v['id']]} for u,v in zip(units,target)],'unresolved':[]}
    new=rewrite_candidate(item,data,target,allowed,anchors);assert new['en']=='I love her. We live in Beijing.';assert new['zh']==new['draftZh']
    data['english_units'][1]['text']='We moved to London.'
    with pytest.raises(StateError,match='范围外'):rewrite_candidate(item,data,target,allowed,anchors)

def test_undo_versions_and_export_pending(tmp_path):
    store,p,item=ready(tmp_path);id_=item['id'];store.draft(p,id_,'我爱她。我们住在北京。',0)
    with pytest.raises(StateError,match='待回写'):store.export(p)
    store.undo(p,id_);assert item['draftZh']=='我爱你。我们住在北京。';assert item['revision']==2
    store.undo(p,id_,True);assert item['draftZh']=='我爱她。我们住在北京。';assert item['status']=='pending'
    with pytest.raises(StateError,match='版本'):store.draft(p,id_,'new',0)

def test_partial_many_many_requires_scope(tmp_path):
    store,p,item=ready(tmp_path);s=[u['id'] for u in item['units']];z=[u['id'] for u in item['targetUnits']]
    item['groups']=validate_links(item['units'],item['targetUnits'],[{'source_ids':s,'target_ids':z}]);item['draftZh']='我爱她。我们住在北京。'
    with pytest.raises(StateError,match='多对多'):impact(item)
    assert impact(item,[s[0]])[0]==[s[0]]

def test_no_change_updates_mapping(tmp_path):
    store,p,item=ready(tmp_path);item['draftZh']='我爱你！我们住在北京。';target=split_units(item['draftZh'],'newz')
    allowed,anchors=impact(item)
    new=rewrite_candidate(item,{'english_units':item['units'],'links':[{'source_ids':[u['id']],'target_ids':[v['id']]} for u,v in zip(item['units'],target)],'unresolved':[]},target,allowed,anchors)
    assert new['en']==item['en'];assert new['targetUnits'][0]['text']=='我爱你！';assert new['zh']==item['draftZh']

def test_deleted_sentence_cannot_be_rebound(tmp_path):
    store,p,item=ready(tmp_path);item['draftZh']='我们住在北京。';target=split_units(item['draftZh'],'z');allowed,anchors=impact(item)
    bad={'english_units':item['units'],'links':[{'source_ids':[u['id'] for u in item['units']],'target_ids':[target[0]['id']]}],'unresolved':[]}
    with pytest.raises(StateError,match='完整删除'):rewrite_candidate(item,bad,target,allowed,anchors)
    good={'english_units':item['units'][1:],'links':[{'source_ids':[item['units'][1]['id']],'target_ids':[target[0]['id']]}],'unresolved':[]}
    result=rewrite_candidate(item,good,target,allowed,anchors);assert result['en']=='We live in Beijing.'
