from server.native_layout import native_layout
import pymupdf

def test_cross_page_paragraph_has_page_local_rectangles(tmp_path):
    pdf=tmp_path/'split.pdf'
    doc=pymupdf.open()
    doc.new_page().insert_text((40,50),'This paragraph starts here')
    doc.new_page().insert_text((50,60),'and ends on the next page.')
    doc.save(pdf);doc.close()
    text='This paragraph starts here and ends on the next page.'
    result=native_layout(pdf,[{'id':'p1','en':text}],tmp_path/'cache',9)
    assert not result['unmapped']
    assert len(result['pages'])==2
    assert [page['regions'][0]['paragraphId'] for page in result['pages']]==['p1','p1']
    for page in result['pages']:
        for rect in page['regions'][0]['rects']:
            assert 0<=rect[0]<rect[2]<=page['width']
            assert 0<=rect[1]<rect[3]<=page['height']

def test_original_ignores_insertions_current_ignores_deletions(tmp_path):
    pdf=tmp_path/'state.pdf';doc=pymupdf.open()
    doc.new_page().insert_text((40,50),'Original unique paragraph.')
    doc.save(pdf);doc.close()
    paragraphs=[{'id':'old','originalEn':'Original unique paragraph.','en':'Changed paragraph.', 'deleted':True},
                {'id':'new','originalEn':'','en':'Original unique paragraph.', 'inserted':True}]
    old=native_layout(pdf,paragraphs,tmp_path/'cache',1,original=True)
    new=native_layout(pdf,paragraphs,tmp_path/'cache',2)
    assert old['pages'][0]['regions'][0]['paragraphId']=='old'
    assert new['pages'][0]['regions'][0]['paragraphId']=='new'
    assert old['key']==new['key']
    assert old['revision']!=new['revision']
