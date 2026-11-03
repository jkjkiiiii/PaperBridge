"""Convert the user-requested arXiv TeX source to a private full DOCX experiment.

Requires pypandoc_binary, python-docx, PyMuPDF and Pillow in the local environment.
All downloaded paper content remains under ignored .data/attention-full.
"""
from pathlib import Path
from io import BytesIO
from collections import Counter
import argparse, hashlib, json, os, re, subprocess, tarfile
from copy import deepcopy
import httpx
import pypandoc
import pymupdf
from PIL import Image
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT=Path(__file__).resolve().parents[1]
def walk(value):
    if isinstance(value,dict):
        yield value
        for v in value.values():yield from walk(v)
    elif isinstance(value,list):
        for v in value:yield from walk(v)
def string(value):
    return ''.join(v['c'] if v.get('t')=='Str' else ' ' if v.get('t') in ('Space','SoftBreak','LineBreak') else '' for v in walk(value))
def inlines(text):return [{'t':'Str','c':text}]
def prefix_caption(caption,text):
    blocks=caption[1]
    if blocks and blocks[0]['t'] in ('Plain','Para'):
        blocks[0]['c']=inlines(text)+[{'t':'Space'}]+blocks[0]['c']
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--work-dir',type=Path,default=ROOT/'.data/attention-full');ap.add_argument('--download',action='store_true');args=ap.parse_args()
    work=args.work_dir.resolve();src=work/'source';work.mkdir(parents=True,exist_ok=True)
    if args.download or not (work/'source.tar.gz').exists():
        with httpx.Client(proxy=os.environ.get('HTTPS_PROXY'),trust_env=False,timeout=90,follow_redirects=True) as c:
            for filename,url in [('source.tar.gz','https://arxiv.org/src/1706.03762'),('original.pdf','https://arxiv.org/pdf/1706.03762')]:
                r=c.get(url);r.raise_for_status();(work/filename).write_bytes(r.content)
    if not (src/'ms.tex').exists():
        with tarfile.open(work/'source.tar.gz','r:*') as archive:
            for member in archive.getmembers():
                if not (src/member.name).resolve().is_relative_to(src.resolve()) or member.issym() or member.islnk():raise ValueError('Unsafe archive member')
            archive.extractall(src,filter='data')
    pandoc=pypandoc.get_pandoc_path()
    subprocess.run([pandoc,'ms.tex','-f','latex','-t','json','-o',str(work/'raw.json')],cwd=src,check=True)
    ast=json.loads((work/'raw.json').read_text('utf-8'));original_counts=Counter(x.get('t') for x in walk(ast))
    keys=re.findall(r'\\bibitem(?:\[[^]]*\])?\{([^}]+)\}',(src/'ms.tex').read_text('utf-8'))
    refs={key:str(i+1) for i,key in enumerate(keys)}
    # Preserve inline numeric references without requiring an absent external .bib.
    def transform(value):
        if isinstance(value,dict):
            if value.get('t')=='Cite':
                ids=[item['citationId'] for item in value['c'][0]]
                if any(key not in refs for key in ids):raise ValueError('Unknown citation')
                return {'t':'Str','c':'['+', '.join(refs[key] for key in ids)+']'}
            return {k:transform(v) for k,v in value.items()}
        if isinstance(value,list):return [transform(v) for v in value]
        return value
    ast=transform(ast)
    converted=[]
    for node in walk(ast):
        if node.get('t')=='Image':
            filename=node['c'][-1][0];path=src/filename
            if path.suffix.lower()=='.pdf':
                target=path.with_suffix('.png')
                with pymupdf.open(path) as pdf:
                    assert len(pdf)==1
                    pdf[0].get_pixmap(matrix=pymupdf.Matrix(2,2),alpha=False).save(target)
                node['c'][-1][0]=str(target.relative_to(src)).replace('\\','/')
                converted.append(filename)
            path=src/node['c'][-1][0]
            with Image.open(path) as image:width,height=image.size
            cap=6.3 if '/vis/' in '/'+node['c'][-1][0] else 3.0
            cap=min(cap,8.0*width/height)
            node['c'][0][2]=[['width',f'{cap}in']]
    figure_no=table_no=0
    for node in list(walk(ast)):
        if node.get('t')=='Figure':
            figure_no+=1;prefix_caption(node['c'][1],f'Figure {figure_no}:')
            if node['c'][0][0]=='fig:multi-head-att':
                paths=[src/n['c'][-1][0] for n in walk(node['c'][2]) if n.get('t')=='Image']
                images=[Image.open(p).convert('RGB') for p in paths]
                heights=1200;resized=[im.resize((round(im.width*heights/im.height),heights)) for im in images]
                canvas=Image.new('RGB',(sum(im.width for im in resized)+80,heights),'white');x=0
                for im in resized:canvas.paste(im,(x,0));x+=im.width+80
                combined=src/'Figures/attention-pair.png';canvas.save(combined)
                node['c'][2]=[{'t':'Para','c':[{'t':'Image','c':[['',[],[['width','5.7in']]],[],['Figures/attention-pair.png','']]}]}]
        if node.get('t')=='Table':table_no+=1;prefix_caption(node['c'][1],f'Table {table_no}:')
    blocks=[];references_count=0
    for block in ast['blocks']:
        if block['t']=='Div' and 'thebibliography' in block['c'][0][1]:
            paras=block['c'][1]
            if string(paras[0]).strip()=='10':paras=paras[1:]
            assert len(paras)==len(keys),(len(paras),len(keys))
            blocks.append({'t':'Header','c':[1,['references',['unnumbered'],[]],inlines('References')]})
            for i,para in enumerate(paras):
                para['c']=inlines(f'[{i+1}]')+[{'t':'Space'}]+para['c'];references_count+=1
            block={'t':'Div','c':[['',[],[['custom-style','Bibliography']]],paras]}
        blocks.append(block)
    ast['blocks']=blocks
    # Keep metadata notes and every source author; Pandoc retains document footnotes.
    outfile=work/'attention-is-all-you-need-full.docx';(work/'prepared.json').write_text(json.dumps(ast,ensure_ascii=False),'utf-8')
    result=subprocess.run([pandoc,str(work/'prepared.json'),'-f','json','-t','docx','--standalone','--number-sections','-o',str(outfile)],cwd=src,capture_output=True,text=True)
    (work/'pandoc-warnings.txt').write_text(result.stderr,'utf-8');result.check_returncode()
    doc=Document(outfile)
    title = next(p for p in doc.paragraphs if p.style.name=='Title')
    title.alignment=WD_ALIGN_PARAGRAPH.CENTER
    for run in title.runs:run.font.name='Times New Roman';run.font.size=Pt(18)
    author = next(p for p in doc.paragraphs if p.style.name=='Author')
    footnotes=author._p.xpath('.//w:footnoteReference')
    authors=[('Ashish Vaswani','Google Brain','avaswani@google.com',0),('Noam Shazeer','Google Brain','noam@google.com',None),('Niki Parmar','Google Research','nikip@google.com',None),('Jakob Uszkoreit','Google Research','usz@google.com',None),('Llion Jones','Google Research','llion@google.com',None),('Aidan N. Gomez','University of Toronto','aidan@cs.toronto.edu',1),('Lukasz Kaiser','Google Brain','lukaszkaiser@google.com',None),('Illia Polosukhin','','illia.polosukhin@gmail.com',2)]
    author_table=doc.add_table(rows=3,cols=3);author_table.autofit=False
    title._p.addnext(author_table._tbl)
    for i,(name,affiliation,email,note) in enumerate(authors):
        cell=author_table.cell(i//3,i%3);cell.width=Inches(2.12)
        para=cell.paragraphs[0];para.alignment=WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.space_after=Pt(4);para.paragraph_format.line_spacing=1
        r=para.add_run(name);r.bold=True
        if note is not None:
            ref=OxmlElement('w:r');ref.append(deepcopy(footnotes[note]));para._p.append(ref)
        elif i>0:
            r=para.add_run('1');r.font.superscript=True
        if affiliation:para.add_run('\n'+affiliation)
        para.add_run('\n'+email)
        for run in para.runs:run.font.name='Times New Roman';run.font.size=Pt(9)
    author._p.getparent().remove(author._p)
    permission=next(p for p in doc.paragraphs if p.text.startswith('Provided proper attribution'))
    title._p.addprevious(permission._p)
    permission.paragraph_format.space_after=Pt(8)
    for section in doc.sections:
        section.page_width=Inches(8.5);section.page_height=Inches(11)
        section.top_margin=Inches(0.8);section.bottom_margin=Inches(0.8);section.left_margin=Inches(1);section.right_margin=Inches(1)
        footer=section.footer.paragraphs[0];footer.alignment=WD_ALIGN_PARAGRAPH.CENTER
        field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
    normal=doc.styles['Normal'];normal.font.name='Times New Roman';normal.font.size=Pt(10)
    normal.paragraph_format.space_after=Pt(6);normal.paragraph_format.line_spacing=1.05
    for name in ['Body Text','First Paragraph','Compact']:
        if name in doc.styles:doc.styles[name].font.name='Times New Roman';doc.styles[name].font.size=Pt(10)
    for name in ['Title','Heading 1','Heading 2','Heading 3','Heading 4']:
        if name in doc.styles:
            style=doc.styles[name];style.font.name='Times New Roman';style.font.color.rgb=None;style.font.bold=True;style.font.size=Pt(18 if name=='Title' else 11 if name=='Heading 1' else 10)
    for name in ['Caption','Table Caption','Image Caption','Bibliography','Footnote Text']:
        if name in doc.styles:doc.styles[name].font.name='Times New Roman';doc.styles[name].font.size=Pt(9)
    for table in doc.tables:
        table.autofit=True
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.paragraph_format.space_after=Pt(3)
                    for run in p.runs:run.font.size=Pt(8)
    doc.core_properties.author='Vaswani et al.';doc.core_properties.last_modified_by='PaperBridge conversion'
    doc.core_properties.title='Attention Is All You Need';doc.core_properties.comments='Private TeX-to-DOCX reconstruction; source arXiv:1706.03762v7. Word pagination differs from TeX.'
    doc.save(outfile)
    from zipfile import ZipFile
    from lxml import etree
    with ZipFile(outfile) as z:
        xml=etree.fromstring(z.read('word/document.xml'));ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main','m':'http://schemas.openxmlformats.org/officeDocument/2006/math'}
        metrics={'paragraphs':len(xml.xpath('//w:body//w:p',namespaces=ns)),'tables':len(xml.xpath('//w:tbl',namespaces=ns)),'bodyMathObjects':len(xml.xpath('//m:oMath',namespaces=ns)),'mathObjectsIncludingFootnotes':sum(len(etree.fromstring(z.read(n)).xpath('//m:oMath',namespaces=ns)) for n in z.namelist() if n.startswith('word/') and n.endswith('.xml')),'embeddedMedia':len([n for n in z.namelist() if n.startswith('word/media/')]),'referenceEntries':references_count,'sourceFigures':figure_no,'sourceTables':table_no,'sourceMathNodes':original_counts['Math']}
    metrics.update(sourceUrl='https://arxiv.org/src/1706.03762',sourceSha256=hashlib.sha256((work/'source.tar.gz').read_bytes()).hexdigest(),wordSha256=hashlib.sha256(outfile.read_bytes()).hexdigest(),pdfFiguresRasterized=converted,pandocWarnings=result.stderr,limitations=['Word pagination and font metrics differ from the source TeX; this is a content-preserving editable reconstruction, not pixel-identical PDF embedding.','Five original PDF figure panels were rasterized at 144 DPI; two attention-diagram PNGs were composed into a single side-by-side image.'])
    (work/'conversion-manifest.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'output':str(outfile),'metrics':metrics},ensure_ascii=True))
if __name__=='__main__':main()
