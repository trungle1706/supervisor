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

### Fonts (WP12)

Plus Jakarta Sans (body text) and JetBrains Mono (ids, hashes, code). Both are **OFL-1.1**
(SIL Open Font License 1.1): free to use, embed and redistribute with the software; the
licence text ships next to the files; the fonts may not be sold on their own. The OFL is not
MIT/Apache, but these are static font files (not code) and the design rules require them
(`docs/design/README.md`); they are logged here as the CLAUDE.md licence rule asks.

Downloaded once on 2026-10-15 from the Google Fonts CSS API (variable `wght` axis, subsets
latin, latin-ext and vietnamese) and committed; the app never fetches fonts.
CSS request: `https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400..700&family=JetBrains+Mono:wght@400..600&display=swap`.
Licence texts from `https://raw.githubusercontent.com/google/fonts/main/ofl/plusjakartasans/OFL.txt`
and `.../ofl/jetbrainsmono/OFL.txt`. Served from `/console/static/fonts/` (whitelisted names).

| File (`src/supervisor/console/static/fonts/`) | Family, version | Source URL | SHA-256 |
|---|---|---|---|
| `plus-jakarta-sans-latin.woff2` | Plus Jakarta Sans, Google Fonts v12 | `https://fonts.gstatic.com/s/plusjakartasans/v12/LDIoaomQNQcsA88c7O9yZ4KMCoOg4Ko20yw.woff2` | `153fc85b70298beeb1d61a5f723331649e7f23bb77302a66e61cb3e2fbdb5e79` |
| `plus-jakarta-sans-latin-ext.woff2` | Plus Jakarta Sans, Google Fonts v12 | `https://fonts.gstatic.com/s/plusjakartasans/v12/LDIoaomQNQcsA88c7O9yZ4KMCoOg4Ko40yyygA.woff2` | `38e3b8fd8045048eb311d90170a4429ed2c8f405852dc3d91b5af8452758703f` |
| `plus-jakarta-sans-vietnamese.woff2` | Plus Jakarta Sans, Google Fonts v12 | `https://fonts.gstatic.com/s/plusjakartasans/v12/LDIoaomQNQcsA88c7O9yZ4KMCoOg4Ko50yyygA.woff2` | `b275d1258601dda240fc6a1d4a6cad56e691d898f5cdf1b0e4fd6ca0022d8e40` |
| `jetbrains-mono-latin.woff2` | JetBrains Mono, Google Fonts v24 | `https://fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPxDcwg.woff2` | `83c005d49d8a6a50474c73a5a36ac0468076e9c4a29da7bdb14995d80560a5be` |
| `jetbrains-mono-latin-ext.woff2` | JetBrains Mono, Google Fonts v24 | `https://fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPx7cwhsk.woff2` | `db5ff4db83e580426280e9337a58dc57d3a83784a1b03ad80914651594441d52` |
| `jetbrains-mono-vietnamese.woff2` | JetBrains Mono, Google Fonts v24 | `https://fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPx_cwhsk.woff2` | `c89b9cc0bc6262bd4f8d8494b6961601f3aefa829d08c2e3635f4d501d3a47c2` |
| `OFL-PlusJakartaSans.txt` | licence text (Copyright 2020 The Plus Jakarta Sans Project Authors) | google/fonts `ofl/plusjakartasans/OFL.txt` | - |
| `OFL-JetBrainsMono.txt` | licence text (Copyright 2020 The JetBrains Mono Project Authors) | google/fonts `ofl/jetbrainsmono/OFL.txt` | - |

`console.css` and `console.js` are hand-written for this repo (no framework).

### Assurance eval packs (WP17)

No third-party dataset, sample or code is vendored. Every pack ships its own synthetic
Vietnamese data (`data/assurance/synthetic/`) and own code written from the papers'
descriptions. Importers read bank-supplied local copies only (`ASSURANCE_DATA_DIR/<pack_id>/`);
the bank checks each dataset's licence before it copies it in. Licences read on 2026-10-15:
TruthfulQA Apache-2.0, SimpleQA (openai/simple-evals) MIT, HaluEval MIT, BBQ CC-BY-4.0,
WinoBias MIT, BOLD / CrowS-Pairs / StereoSet CC-BY-SA-4.0 (importer only, never vendored),
OSV data per source (PyPI Advisory Database CC-BY-4.0), MITRE ATLAS data Apache-2.0,
CycloneDX specification Apache-2.0. References only (no code copied): RAGAS Apache-2.0,
SelfCheckGPT MIT, Fairlearn MIT, garak Apache-2.0, AgentDojo MIT, InjecAgent MIT,
HarmBench MIT, AgentHarm MIT with a use clause. Per-pack URLs: `docs/assurance.md`.
