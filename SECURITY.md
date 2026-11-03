# Security and privacy

PaperBridge runs on localhost. Manuscripts, drafts, caches and credentials are stored under `.data/`. Calls to a configured model service contain document text and context; using a local model keeps those calls local.

The application is intended for a trusted single-user desktop. Do not expose its HTTP port directly to the internet. The native preview worker opens task-owned copies in a dedicated Word instance with macros and external-link updates disabled.

## Reporting a vulnerability

Do not post credentials, private documents or exploitable details in a public issue. If the repository has GitHub private vulnerability reporting enabled, use its **Security → Report a vulnerability** page. Otherwise, open an issue requesting a private contact without describing the exploit, then share a minimal synthetic reproduction through an agreed private channel.

No security audit or multi-user deployment hardening is claimed. A normal bug report should include sanitized logs and a public or synthetic document.
