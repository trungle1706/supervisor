# Licence log

Rule (CLAUDE.md): MIT or Apache-2.0 for copied code. Any other licence is an optional
extra behind a flag, off by default, and is logged here.

| Package | Licence | Extra / flag | Default | Used by | Note |
|---|---|---|---|---|---|
| fpdf2 (>= 2.7) | LGPL-3.0-only | `pdf` (`uv sync --extra pdf`) | off | `supervisor.evidence.casefile.render_pdf` (WP6) | Imported lazily. Pure Python; pulls Pillow (MIT-CMU), fontTools (MIT), defusedxml (PSF). Without the extra, or without a local Unicode TTF (`CASEFILE_PDF_FONT`), the case file is written as HTML and the notice says so. No fonts are downloaded or vendored. |
