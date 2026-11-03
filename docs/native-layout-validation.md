# Native Word layout validation — 2026-11-04

## Problem and implementation

The complete Attention Is All You Need editable reconstruction includes formulas, drawings, tabs, repeated numeric table cells and cross-page paragraphs. Global exact paragraph text lookup excluded protected objects and ambiguous short strings, leaving many visible paragraphs without interaction regions.

Native page requests now add stable paragraph and editable-run bookmarks to a disposable DOCX copy. Microsoft Word resolves these to PDF destinations. Text geometry must match within the destination page/position constraints; table matching is additionally constrained by cell width. Verified text ranges receive text overlays; unresolved formula/image/short-text content receives an explicitly marked native paragraph point. Empty paragraphs have no invisible hit target. Source documents and normal DOCX exports are not modified.

The UI keeps paragraph hit regions under sentence regions, aligns hover to corresponding sentence rectangles and provides an explicit structural fallback instead of changing both panes automatically.

## Full-paper regression

One local existing full-paper retranslation was checked in both languages, with normal and diff display. It contains 575 logical paragraphs, including 188 empty paragraphs and 387 nonempty paragraphs.

| Measurement | English | Chinese |
|---|---:|---:|
| Previously located paragraphs | 105 | 97 |
| Located nonempty paragraphs after change | 387 | 387 |
| Paragraphs with verified text rectangles | 281 | 241 |
| Paragraphs with native position markers only | 106 | 146 |
| Located sentence IDs | 372 | 318 |
| Pages | 15 | 14 |
| Pixel-identical pages versus prior clean rendering | 15/15 | 14/14 |

Coverage includes native position markers; it does not mean every paragraph supports precise sentence highlighting. The pixel comparison checks layout preservation for this sample, not translation quality or all possible Word documents. Source DOCX and project state hashes remained unchanged. Full-document normal and diff modes yielded the same coverage for this unedited English sample. First-time generation of new anchored snapshots still requires Word; cached layouts are reused.

Automated regressions cover repeated numeric cells, repeated text across pages, stale sentence offsets, protected-object markers and bookmark-name collisions. Real Word PDF checks are local validation; CI runs the synthetic geometry and package-preservation tests without requiring Microsoft Word.
