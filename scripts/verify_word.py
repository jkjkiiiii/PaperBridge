"""Native Microsoft Word read-only opening and PDF-render checks on task-owned copies."""
from pathlib import Path
from hashlib import sha256
import argparse
import json
import sys
from io import BytesIO
from zipfile import ZipFile
import win32com.client
import pymupdf
from lxml import etree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.documents import extract,export_docx,package_hashes,NS

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'.data'/'verification';OUT.mkdir(parents=True,exist_ok=True)
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('source',nargs='?',type=Path,default=ROOT/'examples'/'attention'/'attention-demo.docx')
parser.add_argument('--find',help='Optional text replacement for a format-preservation check')
parser.add_argument('--replace',default='')
args=parser.parse_args()
SOURCE=args.source.resolve()
source=SOURCE.read_bytes();source_hash=sha256(source).hexdigest();paragraphs=extract(source)
if args.find:
    item=next((p for p in paragraphs if args.find in p['en']),None)
    if item is None:raise SystemExit('Search text was not found')
    item['en']=item['en'].replace(args.find,args.replace,1)
edited=export_docx(source,paragraphs);target=OUT/'format_test_only.docx';target.write_bytes(edited)
original_copy=OUT/'original_copy.docx';original_copy.write_bytes(source)
hashes=package_hashes(source);newhashes=package_hashes(edited)
assert all(newhashes[k]==v for k,v in hashes.items() if k!='word/document.xml')
def props(data):
    with ZipFile(BytesIO(data)) as z:root=E.fromstring(z.read('word/document.xml'))
    return [E.tostring(x,method='c14n') for x in root.xpath('//w:rPr|//w:pPr',namespaces=NS)]
assert props(source)==props(edited)
app=win32com.client.DispatchEx('Word.Application');app.Visible=False;app.DisplayAlerts=0
records=[]
try:
    for path in [original_copy,target]:
        document=app.Documents.Open(FileName=str(path),ReadOnly=True,AddToRecentFiles=False,Visible=False,OpenAndRepair=False)
        try:
            pages=document.ComputeStatistics(2)
            pdf=path.with_suffix('.pdf');document.ExportAsFixedFormat(OutputFileName=str(pdf),ExportFormat=17,OpenAfterExport=False)
            records.append({'file':path.name,'sha256':sha256(path.read_bytes()).hexdigest(),'openedWithoutRepair':True,'pages':pages,'pdf':pdf.name})
        finally:document.Close(SaveChanges=0)
finally:app.Quit(SaveChanges=0)
for record in records:
    pdf=pymupdf.open(OUT/record['pdf']);pdf[0].get_pixmap(matrix=pymupdf.Matrix(1.2,1.2)).save(OUT/(Path(record['file']).stem+'_page1.png'))
assert sha256(SOURCE.read_bytes()).hexdigest()==source_hash
(OUT/'word_checks.json').write_text(json.dumps({'sourceHash':source_hash,'sourceUnchanged':True,'unmodifiedPartsEqual':True,'paragraphAndRunPropertiesEqual':True,'records':records},ensure_ascii=False,indent=2),'utf-8')
print(json.dumps({'filesOpened':len(records),'sourceUnchanged':True,'formatPropertiesEqual':True}),flush=True)
