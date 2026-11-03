# Changelog

## Unreleased

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
