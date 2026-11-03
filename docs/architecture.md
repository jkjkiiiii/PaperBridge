# Architecture

```mermaid
flowchart LR
  Word[Original DOCX] --> Package[ZIP/XML text and structure index]
  Package --> State[Versioned project state]
  State --> Router[Translation router]
  Router --> MT[Dedicated translation service]
  MT --> Model[LLM alignment of fixed texts]
  Router --> Model
  State --> Rewrite[LLM local rewrite]
  Rewrite --> Validate
  Model --> Validate[Schema and allowed-edit validation]
  Validate --> State
  State --> Patch[Minimal DOCX text patches]
  Patch --> Export[New English DOCX + JSON]
  State --> Preview[Disposable English / Chinese copies]
  Preview --> Native[Microsoft Word PDF rendering]
  Native --> Pages[Cached pages and conservative text geometry]
  Pages --> UI[React bilingual interface]
  UI --> State
```

## Document source and edits

`server/documents.py` indexes paragraph/run text and document structure. Original package bytes are retained. Export applies bounded changes to a copy rather than rebuilding the document from HTML or PDF. Images, equations, fields and other protected content cannot be edited as plain text.

`server/state.py` owns stable IDs, committed bilingual text, Chinese drafts, mappings, history and final effective patches. A successful rewrite commits English and mapping changes together. Late responses cannot replace a newer editing revision.

## Model boundary

`server/llm.py` builds task-specific requests and validates structured results. `server/provider_catalog.py` describes provider defaults and authentication. Keys stay in the local secret file, outside public project exports. Full retranslation creates an independent version with a pinned model configuration.

## Views

The structure view renders paragraphs and complete tables. The native view uses Word-produced PDF pages plus position overlays. It does not implement Word's layout engine. Geometry is conservative: ambiguous text remains visible but receives no guessed sentence location. Unmatched paragraphs remain editable through a labelled floating editor.

PDFs, page PNGs, geometry and browser snapshots are cached. Dirty projects can still display committed content; export remains blocked until unresolved edits are handled.

## Validation boundaries

Normal tests cover deterministic document, state, API and protocol behavior. Native Word rendering is optional and local. A real-model demo verifies a selected workflow, not general translation accuracy. Cloud adapter tests use mocked responses unless explicit user credentials are configured.

## Translation boundary

Dedicated MT engines implement a common text-list adapter; LLM protocols remain separate. Credentials live in an independent ignored secret store. Paragraph translation, fixed-text LLM mapping and constrained English rewrite have distinct responsibilities. Full retranslation pins both public translation settings and LLM settings; failed mapping explicitly degrades to a coarse paragraph group. See [translation services](translation-services.md).
