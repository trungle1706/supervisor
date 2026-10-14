# Licence log

Rule (CLAUDE.md): MIT or Apache-2.0 for copied code. Any other licence is an optional
extra behind a flag, off by default, and is logged here.

| Package | Licence | Extra / flag | Default | Used by | Note |
|---|---|---|---|---|---|
| fpdf2 (>= 2.7) | LGPL-3.0-only | `pdf` (`uv sync --extra pdf`) | off | `supervisor.evidence.casefile.render_pdf` (WP6) | Imported lazily. Pure Python; pulls Pillow (MIT-CMU), fontTools (MIT), defusedxml (PSF). Without the extra, or without a local Unicode TTF (`CASEFILE_PDF_FONT`), the case file is written as HTML and the notice says so. No fonts are downloaded or vendored. |

## Vendored static assets

| Asset | Version | Licence | Path | SHA-256 | Note |
|---|---|---|---|---|---|
| htmx (`htmx.min.js`) | 1.9.12 | 0BSD (Zero-Clause BSD; BSD family, no attribution clause) | `src/supervisor/console/static/htmx.min.js` (+ `htmx.LICENSE.txt`) | `449317ade7881e949510db614991e195c3a099c4c791c24dacec55f9f4a2a452` | WP8 reviewer console. Downloaded once on 2026-10-14 from `unpkg.com/htmx.org@1.9.12/dist/htmx.min.js`, committed; the app never fetches it. Licence SHA-256 `d3d2456f76414f2456104660ebd65aff1c04cd7966b942bdabd63f3cdb316a38`. Served from `/console/static/`. A test checks the hash and that templates reference no `http(s)://` assets. |

`console.css` and `console.js` are hand-written for this repo (no framework, system fonts only).
