import asyncio
from copy import deepcopy
from io import BytesIO
import pytest
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from fastapi.testclient import TestClient
from server.documents import extract, build_chinese_preview, split_units
from server.reference_policy import detect_references
from server.state import Store, StateError
from server.retranslation import RetranslationJobs
from server.app import translation_candidate, context_for
from test_retranslation import FakeClient


def reference_doc():
    d=Document()
    d.add_heading('A scientific paper', 1)
    d.add_paragraph('References are cited throughout this body [1].')
    d.add_heading('References', 1)
    d.add_paragraph('[1] Example Author. A cited work. 2017.')
    d.add_paragraph('[2] Another Author. A second work. 2020.')
    d.add_heading('Appendix A. Extra experiments', 1)
    d.add_paragraph('Appendix body should still be translated.')
    b=BytesIO();d.save(b);return b.getvalue()


def test_detect_reference_section_and_stop_at_appendix():
    paragraphs=extract(reference_doc())
    assert [p['index'] for p in paragraphs if p['translationPolicy']=='skip_reference']==[2,3,4]
    assert paragraphs[1]['translationPolicy']=='translate'
    assert paragraphs[-1]['translationPolicy']=='translate'
    assert all(not p['units'] and not p.get('groups') for p in paragraphs[2:5])
    assert context_for({'paragraphs':paragraphs},paragraphs[5])['previous']==''


def test_bibliography_style_and_numbered_heading():
    d=Document();d.styles.add_style('Bibliography',WD_STYLE_TYPE.PARAGRAPH)
    d.add_paragraph('A reference entry with a title.',style='Bibliography')
    d.add_heading('8 References',1);d.add_paragraph('[1] A work.')
    d.add_heading('Acknowledgements',1);d.add_paragraph('We thank our colleagues.')
    b=BytesIO();d.save(b);p=extract(b.getvalue())
    assert [x['translationPolicy'] for x in p]==['skip_reference']*3+['translate']*2


def test_existing_translation_and_history_not_destroyed(tmp_path):
    store=Store(tmp_path/'projects');p=store.create(reference_doc(),'paper.docx')
    ref=p['paragraphs'][3]
    ref.update(zh='旧译文',draftZh='旧译文',groups=[{'old':True}],history=[{'preserved':True}],status='ready')
    store.save(p)
    after=store.get(p['id'])['paragraphs'][3]
    assert after['translationPolicy']=='skip_reference'
    for key in ('en','zh','draftZh','history','groups'):assert after[key]==ref[key]
    # Native Chinese pages use the reference English, even for legacy translations.
    assert build_chinese_preview(store.source(p),store.get(p['id'])['paragraphs'])==store.source(p)
    with pytest.raises(StateError):store.draft(p,ref['id'],'新译文',ref['revision'])


def test_full_retranslation_never_calls_reference_sections(tmp_path):
    store=Store(tmp_path/'projects');source=store.create(reference_doc(),'paper.docx')
    client=FakeClient(tmp_path);calls=[]
    original=client.generate
    async def generate(task,payload,settings,cache):
        assert payload.get('translationPolicy')!='skip_reference'
        text=''.join(x['text'] for x in payload['source_units'])
        assert '[1] Example Author' not in text and '[2] Another Author' not in text
        calls.append(payload['paragraph_id'])
        return await original(task,payload,settings,cache)
    client.generate=generate
    jobs=RetranslationJobs();new=jobs.create(store,client,source)
    asyncio.run(jobs.run(store,client,new['id'],translation_candidate,context_for))
    finished=store.get(new['id'])
    assert finished['retranslation']['status']=='completed'
    assert finished['retranslation']['total']==4
    assert finished['retranslation']['skipped']==3
    assert len(calls)==4
    for ref in finished['paragraphs'][2:5]:assert not ref['zh'] and not ref['groups']
    assert store.export(finished)==store.source(source)


def test_api_reference_guard_and_manual_override(tmp_path,monkeypatch):
    import server.app as api
    from server.llm import ModelClient
    store=Store(tmp_path/'projects');p=store.create(reference_doc(),'paper.docx');ref=p['paragraphs'][3]
    monkeypatch.setattr(api,'DATA',tmp_path);monkeypatch.setattr(api,'store',store);monkeypatch.setattr(api,'client',ModelClient(tmp_path))
    with TestClient(api.app) as c:
        url=f'/api/projects/{p["id"]}/paragraphs/{ref["id"]}'
        for task in ['translate_align','repair_alignment','rewrite_en']:
            assert c.post(url+'/model',json={'task':task}).status_code==422
        assert c.post(url+'/mapping',json={'revision':0,'links':[]}).status_code==422
        r=c.post(url+'/action',json={'action':'translation_policy','policy':'translate'})
        assert r.status_code==200
        updated=store.get(p['id'])['paragraphs'][3]
        assert updated['translationPolicy']=='translate' and updated['status']=='untranslated' and updated['units']


def test_router_defense_skips_without_model_or_service(tmp_path):
    from server.translation_router import TranslationRouter
    from server.llm import ModelError
    class NeverClient:
        def read_settings(self):raise AssertionError('must not inspect or call LLM')
    with pytest.raises(ModelError,match='参考文献'):
        asyncio.run(TranslationRouter(NeverClient(),tmp_path).generate('translate_align',{'translationPolicy':'skip_reference'}))


def test_retranslation_retains_explicit_policy_corrections(tmp_path):
    store=Store(tmp_path/'projects');p=store.create(reference_doc(),'paper.docx')
    p['paragraphs'][3]['translationPolicyOverride']='translate'
    p['paragraphs'][1]['translationPolicyOverride']='skip_reference'
    detect_references(p['paragraphs'])
    new=RetranslationJobs().create(store,FakeClient(tmp_path),p)
    assert new['paragraphs'][3]['translationPolicy']=='translate'
    assert new['paragraphs'][3]['status']=='untranslated' and new['paragraphs'][3]['units']
    assert new['paragraphs'][1]['translationPolicy']=='skip_reference'
