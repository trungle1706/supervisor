# Console UX5 (CONSOLE_UX5)

`CONSOLE_UX5=1` turns on the console redesign foundation. Default off; off = the console as before.

## What the flag does
- `<html class="ux5">` and `static/ux5.css` (linked after `console.css`). Every rule sits under `.ux5`.
- `t(key)` reads the `i18n_ux5_*` overrides first (`translator(lang, ux5=True)`). Templates read `ux5`.
- Restyle: ink links (underline on hover), red only for `.btn.primary` and the current nav item, 1 px panels,
  6-step type (32/24/18/15/14/12), tabular figures, no uppercase labels, chips with dot + word, segmented
  sidebar (v3), the dev-identity notice as a chip with a tooltip. Dark mode has its own `--u5-*` values.
- Not changed: signed transparency reports (`transparency/*`) keep the plain translator.

## Text overrides
Add `console/i18n_ux5_<page>.py` exporting `UX5: dict[str, tuple[str, str]]` and list it in
`console/i18n_ux5.py` (`MODULES`, one line). An override never invents a key (a test checks it) and has
non-empty en and vi. To remove text, use `{% if not ux5 %}` in the template instead.

## Macros (`{% import "_ux5.html" as u5 with context %}`; call them only when `ux5` is true)
| Macro | Use |
|---|---|
| `page_head(title, purpose, about=None, actions=None)` | Page title, one-line purpose, (i) tooltip and "About this page" |
| `disclaimer(text)` | One chip with tooltip per page ("Advisory only") |
| `status_chip(kind, label)` | ok / warn / bad / info / na, dot + word |
| `tick_strip(counts)` | One 3 px mark per item; `counts = [(status, n)]`; capped at 60, then "+N more" |
| `tick_legend(statuses)` | One legend line per table |
| `view_all(shown, total, href)` | "5 of 21 shown . View all" under a summary |
| `pager(page, pages, base_href)` | Prev/next for a 25-row table |
| `fold(n, text, cols=1)` | One line for n identical rows (`cols>1` gives a `<tr>`) |
| `technical(rows)` | Admin-only "Technical details": env flags, paths, ids |

Python helpers in `console/ux5.py`: `top(rows, n)`, `page_slice(rows, page, size=25)` ->
`(rows, page, pages)`, `fold_identical(rows, key)`. Tick colors: gap #B3261E 18 px, partial #D9A441 12 px,
bank process #1F5F8B 8 px, met #2F6B4F 6 px.

## Text budget (from the design rules)
1. Purpose: one sentence, 15 words or fewer; the rest goes into "About this page".
2. Buttons are verbs; no sentence under a button (use a tooltip).
3. Explanations over 40 words collapse behind "Why" or "How this is computed".
4. A disclaimer appears once per page, as a chip.
5. Line length 72 characters; text columns 40 characters or more.
6. Env flags, file paths, work-package ids go in `technical(rows)` for admins.
7. Summaries show 5 to 10 rows then "View all"; tables page at 25 with a sticky header.
8. Group repeated rows; fold identical rows; empty states give the next step.
9. Red is a signal: primary action and current page only. Status = dot + word.
10. Sentence case; mono only for ids and code.
