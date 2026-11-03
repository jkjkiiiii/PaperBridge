# Contributing

PaperBridge is a local document editing tool. Changes should preserve original DOCX files and keep text, sentence mappings and export patches consistent.

## Development

Use Python 3.12 and Node.js 22. On Windows run `setup.ps1`, then `run.ps1`. For frontend development run `npm run dev` from `web/` alongside the backend. Native page rendering requires a local Microsoft Word installation; deterministic tests mock that boundary.

```powershell
python -m pytest -q
cd web
npm ci
npm run build
```

Test fixtures must be synthetic or explicitly redistributable. Model-backed tests require an explicitly configured local service and are separate from normal CI. Do not make CI contact paid model APIs.

## Pull requests

Keep changes focused and explain the user-visible result. For document changes, verify untouched text and package parts, protected objects, mixed runs and representative tables. For model adapters, test the request contract, incomplete responses and timeout behavior. Mock protocol tests establish engineering compatibility, not translation accuracy.

Run relevant tests and the frontend build. Include a screenshot when changing the interface. Remove private filenames, project lists, URLs and credentials from screenshots.

## Project data

`.data/`, `artifacts/` and local reports are ignored. Never commit project JSON, model caches, credentials or private manuscripts. Public screenshots live in `docs/assets/`; reproducible public examples live in `examples/`.
