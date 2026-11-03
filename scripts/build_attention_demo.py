"""Build the attributed, one-page public PaperBridge demonstration document.

Uses python-docx from the project's requirements; no network or credentials.
The excerpt is not an official DOCX or a reproduction of the paper's layout.
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parents[1]
EXCERPTS = [
    'The dominant sequence transduction models are based on complex recurrent or convolutional neural networks in an encoder-decoder configuration.',
    'The paper introduces the Transformer, a sequence model that relies entirely on attention instead of recurrent or convolutional layers.',
    'The authors evaluate two translation tasks and report favorable quality, greater parallelism, and shorter training than the comparison systems.',
]


def build(output: Path):
    doc = Document()
    section = doc.sections[0]
    section.page_width = Inches(8.27)
    section.page_height = Inches(11.69)
    section.top_margin = section.bottom_margin = Inches(.7)
    section.left_margin = section.right_margin = Inches(.8)
    normal = doc.styles['Normal']
    normal.font.name = 'Times New Roman'
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(9)
    normal.paragraph_format.line_spacing = 1.12
    for name in ('Title', 'Heading 1'):
        doc.styles[name].font.name = 'Calibri'
        doc.styles[name].font.color.rgb = RGBColor.from_string('245F52')
    title = doc.add_paragraph('Attention Is All You Need', 'Title')
    title.paragraph_format.space_after = Pt(5)
    p = doc.add_paragraph('PAPERBRIDGE  /  BILINGUAL EDITING DEMO')
    p.runs[0].font.name = 'Calibri'
    p.runs[0].font.size = Pt(9)
    p.runs[0].font.color.rgb = RGBColor.from_string('718078')
    doc.add_paragraph('Vaswani et al. · 2017 · arXiv:1706.03762')
    doc.add_paragraph('Abstract · quotation and adapted summary', 'Heading 1')
    for text in EXCERPTS:
        doc.add_paragraph(text)
    doc.add_paragraph('Editing sandbox · original demo text', 'Heading 1')
    doc.add_paragraph('This document demonstrates bilingual editing. The original document remains unchanged. The exported copy contains the approved text edits.')
    table = doc.add_table(rows=1, cols=2)
    table.style = 'Light Shading Accent 1'
    table.autofit = False
    table.columns[0].width = Inches(1.5)
    table.columns[1].width = Inches(5.17)
    table.rows[0].cells[0].width = Inches(1.5)
    table.rows[0].cells[1].width = Inches(5.17)
    table_width = table._tbl.tblPr.find(qn('w:tblW'))
    table_width.set(qn('w:type'), 'dxa')
    table_width.set(qn('w:w'), '9605')
    for cell, text in zip(table.rows[0].cells, ('Step', 'Demo action')):
        cell.text = text
        cell.paragraphs[0].runs[0].bold = True
    for label, action in [('01 · Translate', 'Generate Chinese text and sentence mappings.'), ('02 · Edit', 'Revise wording, remove a sentence, and insert a sentence.'), ('03 · Export', 'Save an edited English DOCX copy and a JSON change log.')]:
        cells = table.add_row().cells
        cells[0].text, cells[1].text = label, action
        cells[0].width, cells[1].width = Inches(1.5), Inches(5.17)
    p = doc.add_paragraph('Source: https://arxiv.org/abs/1706.03762 · First abstract sentence quoted; the following two paragraphs are adapted summaries. Sandbox and table are original demo material. Edits are illustrative, not paper corrections.')
    for run in p.runs:
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor.from_string('718078')
    props = doc.core_properties
    props.title = 'Attention Is All You Need — PaperBridge demo excerpt'
    props.subject = 'Attributed paper excerpt and synthetic editing sandbox'
    props.author = 'PaperBridge contributors'
    props.last_modified_by = 'PaperBridge contributors'
    props.created = props.modified = datetime(2026, 1, 1, tzinfo=timezone.utc)
    props.comments = 'Generated with scripts/build_attention_demo.py. Not an official paper DOCX.'
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'examples'/'attention'/'attention-demo.docx')
    print(build(parser.parse_args().output))
