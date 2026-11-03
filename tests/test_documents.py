from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
import random
import pytest
from docx import Document
from docx.shared import RGBColor, Pt
from lxml import etree as E
from server.documents import extract, export_docx, package_hashes, DocumentError, split_units, NS, tag

def fixture_doc():
    d=Document()
    d.add_heading('Bilingual editing test',0)
    p=d.add_paragraph(); p.add_run('I love '); p.add_run('you').bold=True; p.add_run('. We live in Beijing.')
    p=d.add_paragraph('The concentration is '); r=p.add_run('10'); r.font.color.rgb=RGBColor(0x90,0x20,0x20);r.font.size=Pt(11)
    p.add_run(' mol L');p.add_run('−1').font.superscript=True;p.add_run('.')
    d.add_paragraph('First sentence. Second sentence. Third sentence.')
    d.add_paragraph('Dr. Smith et al. measured 1.5 mg. The result was stable.')
    t=d.add_table(rows=1,cols=2);t.cell(0,0).text='Table content.';t.cell(0,1).text='Unchanged cell.'
    p=d.add_paragraph('An inline equation: ')
    m='http://schemas.openxmlformats.org/officeDocument/2006/math'
    math=E.SubElement(p._p,'{'+m+'}oMath');run=E.SubElement(math,'{'+m+'}r');E.SubElement(run,'{'+m+'}t').text='x=1'
    p.add_run(' remains fixed.')
    d.sections[0].header.paragraphs[0].text='Read-only header'
    b=BytesIO();d.save(b);return b.getvalue()

def texts(data):return [p['en'] for p in extract(data)]

def test_exact_noop_and_styles():
    data=fixture_doc();ps=extract(data)
    assert export_docx(data,ps)==data
    ps[1]['en']=ps[1]['en'].replace('you','her')
    output=export_docx(data,ps)
    assert texts(output)[1]=='I love her. We live in Beijing.'
    before=package_hashes(data);after=package_hashes(output)
    assert {k:v for k,v in before.items() if k!='word/document.xml'}=={k:v for k,v in after.items() if k!='word/document.xml'}
    def props(b):
        with ZipFile(BytesIO(b)) as z:root=E.fromstring(z.read('word/document.xml'))
        return [E.tostring(p,method='c14n') for p in root.xpath('//w:rPr|//w:pPr',namespaces=NS)]
    assert props(data)==props(output)

@pytest.mark.parametrize('new',[
    'First sentence. Third sentence.',
    'First sentence. An inserted sentence. Second sentence. Third sentence.',
    'Changed first. Second sentence. Changed last.',
    '',
    'Entirely different wording with emoji 🧬.',
])
def test_sentence_edits(new):
    data=fixture_doc();ps=extract(data);ps[3]['en']=new
    assert texts(export_docx(data,ps))[3]==new

def test_random_multirun_text_patch():
    rng=random.Random(12)
    for _ in range(150):
        d=Document();p=d.add_paragraph()
        old=''.join(rng.choice('abcd ') for _ in range(50))
        for i in range(0,50,3):p.add_run(old[i:i+3])
        b=BytesIO();d.save(b);data=b.getvalue();ps=extract(data)
        new=old
        for _ in range(3):
            a=rng.randrange(len(new)+1);b=rng.randrange(a,len(new)+1);new=new[:a]+''.join(rng.choice('xyz 🧬') for _ in range(rng.randrange(12)))+new[b:]
        ps[0]['en']=new
        assert texts(export_docx(data,ps))[0]==new

def test_protection_and_table():
    data=fixture_doc();ps=extract(data);protected=next(p for p in ps if p['protected']);protected['en']=protected['en'].replace('remains fixed','is preserved')
    assert texts(export_docx(data,ps))[-1].endswith('is preserved.')
    protected['en']=protected['en'].replace(protected['protected'][0],'')
    with pytest.raises(DocumentError):export_docx(data,ps)
    ps=extract(data);cell=next(p for p in ps if p['container']=='table');cell['en']='Edited table content.'
    assert 'Edited table content.' in texts(export_docx(data,ps))

def test_mixed_styles_need_policy():
    d=Document();p=d.add_paragraph();p.add_run('AB').bold=True;p.add_run('CD').italic=True
    b=BytesIO();d.save(b);data=b.getvalue();ps=extract(data);ps[0]['en']='XY'
    with pytest.raises(DocumentError,match='继承'):export_docx(data,ps)
    for policy in ['left','right']:
        ps[0]['stylePolicy']=policy;assert texts(export_docx(data,ps))==['XY']

def test_insert_delete_paragraph():
    data=fixture_doc();ps=extract(data);n=deepcopy(ps[3]);n.update(id='newp',inserted=True,inheritFrom=ps[3]['id'],originalEn='',en='New paragraph.',protected=[])
    ps.insert(4,n);ps[4+1]['deleted']=True
    out=texts(export_docx(data,ps));assert out[4]=='New paragraph.';assert not any('Dr. Smith' in x for x in out)

def test_split_preserves_abbreviations_and_unicode():
    t='Dr. Smith et al. measured 1.5 mg. The result 🧬 was stable.'
    u=split_units(t,'x');assert len(u)==2;assert ''.join(x['text'] for x in u)==t
    assert all(t[x['start']:x['end']]==x['text'] for x in u)
