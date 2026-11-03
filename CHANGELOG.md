# Changelog

## Unreleased

- Show recorded translation provenance and planned translation/mapping services before full-document retranslation; display version-specific provenance and reject stale confirmation plans when source/settings change.


- Replace whole-paragraph PDF text lookup with stable Word-exported paragraph/run bookmarks in disposable previews; distinguish text overlays from native position markers for formulas/images and ambiguous text.
- Verify the full Attention retranslation: all 387 nonempty paragraphs have native locations in both languages; empty paragraphs remain noninteractive. Native bookmarks preserve all 15 English and 14 Chinese page rasters pixel-for-pixel in this sample.
- Align hover navigation to matching sentence rectangles, preserve paragraph hit areas, and avoid forcing both panes into structural mode when only one side lacks a location.


- Add changed-paragraph navigation for English/Chinese edits, drafts and inserted/deleted paragraphs, with bidirectional jumps.
- Add bilingual paragraph search with Ctrl+F, highlighted snippets and Enter / Shift+Enter navigation, including structural fallback for unmapped page regions.
- Cache complete native-layout responses with bounded content-aware invalidation; serve existing PDF caches without waiting for cold Word jobs and publish newly rendered PDFs atomically.


### Word preview and documentation — 2026-11-04

- Add red-deletion/green-insertion diff to English and Chinese native Word previews, using the same word-first English policy as structural editing.
- Keep diff previews and caches separate from clean DOCX exports; show inserted/deleted paragraphs and use paragraph-level coordinates for changed text.
- Recover paragraph and sentence coordinates around verified zero-width Word bookmarks, including existing projects; preserve protected objects in exports.
- Increase sentence correspondence color contrast and add stronger hover/selection outlines.
- Refresh README with native diff screenshots, behavior limits, service configuration and promotion resources.
- Add eight 9:16 promotion cards in 1080×1920 and 2160×3840, editable layout sources, attributed demo captures and revised Chinese social copy.
- Validate with 130 backend tests, 4 frontend tests and a production frontend build.


- Recognize ASCII sentence punctuation immediately before Chinese while preserving abbreviations and decimals.
- Distinguish valid merged/split sentence mappings from unresolved ambiguity; retain quality notes and fallback diagnostics.
- Re-segment committed translations during alignment repair without retranslating or changing text.
- Document the full-paper Attention experiment: 98,982 DeepSeek tokens and user-confirmed approximate ¥0.12 consumption, with separately metered two-paragraph repair.

- Centralize initial translation, sentence mapping and English rewrite selection in task assignments.
- Add queued MT request-rate, character and text-item limits, distinct from concurrency.

- Separate machine-translation service selection from general LLM configuration.
- Add signed Volcengine TranslateText, DeepL, Azure Translator and self-hosted LibreTranslate adapters.
- Align fixed machine translations using the selected general LLM, with an explicit paragraph-level fallback.
- Pin both translation and LLM settings for full-document retranslation, with isolated local credentials.
- Add a dedicated DeepSeek provider tab and documented API defaults.

## [0.1.0] — 2026-11-03

First public source release of **PaperBridge**.

### Added

- DOCX import with English–Chinese aligned translation and local project storage.
- Chinese text editing with constrained English rewrites, sentence mappings and undo/redo.
- Word-rendered bilingual page view, in-place editing overlays and structural editing view.
- Mouse-directed bilateral alignment and word-first English diff highlights.
- Replayable JSON change logs and clean English DOCX export using original-package patches.
- Independent full-document retranslation versions with progress, pause and resume.
- Provider-specific configuration for local models, OpenAI, Anthropic, Gemini and Kimi Open Platform.
- Attributed Attention Is All You Need demo, screenshots, replayable translation/edits and exported DOCX.
- MIT license, contributor/security guidance, issue templates and CI.

See [release notes](docs/releases/v0.1.0.md) for setup and current limits.
