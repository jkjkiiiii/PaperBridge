# Third-party notices

MIT covers this project’s original code, not third-party packages or the source paper. Consult each installed distribution for its complete license and notices.

| Component | License reported by installed package | Role |
| --- | --- | --- |
| PyMuPDF | AGPL-3.0 or Artifex Commercial License | PDF page images and coordinates |
| React / Vite | MIT | Web interface and build |
| TypeScript | Apache-2.0 | Frontend compiler |
| FastAPI / python-docx / jsonschema | MIT | API, demo generation, validation |
| httpx / lxml | BSD-3-Clause | HTTP and XML |

PyMuPDF’s dual license has independent obligations for a combined deployment or distribution; the project’s MIT license does not override those terms. This table is a guide, not a replacement for the dependency licenses.

The demo includes one short quotation from [Vaswani et al. (2017)](https://arxiv.org/abs/1706.03762). Its authors retain the source paper’s rights. Original paraphrases and the editing sandbox are labelled in the example. The paper is not redistributed in full.

The provider registry design was informed by [OneClaw](https://github.com/oneclaw/oneclaw) and official API documentation. OneClaw source downloads used for research stay outside the public repository; no source files were copied into this implementation. See [research notes](docs/provider-adaptation.md).
