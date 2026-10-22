# Document and URL intake: validation report (WP-D1)

Harness `document-intake-eval-1`, preset `balanced`, mode `real`, commit `wp-d1`, date 2026-10-22. Thresholds are ILLUSTRATIVE until the bank sets them. Reproduce: `python -m supervisor.detectors.intake_eval` (or the harness, which includes these rows). PDF items need the optional extra `documents` (`pypdf`).

**Overall: GO**

Adversarial rows: a GO marked `indicative` passed on the point value only; its Wilson lower bound is below the threshold, so the row is not proof. Read the interval.

Expert rubrics: SOC analyst reading a verdict (typed recall, fragment exactness, false positives, latency) and data protection officer (no raw sensitive string in any finding, fragment, entity or transformed payload: `leak_items` must be 0).

## document_injection_vi@document-intake-eval-1: GO

| split | n | pos | tp | fn | fp | recall bp (95% CI) | precision bp (95% CI) | typed recall bp | fragment exact bp | leaks | p95 us |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dev | 60 | 40 | 40 | 0 | 0 | 10000 [9123, 10000] | 10000 [9123, 10000] | 10000 | 10000 | 0 | 3120 |
| heldout | 60 | 40 | 40 | 0 | 0 | 10000 [9123, 10000] | 10000 [9123, 10000] | 10000 | 10000 | 0 | 2919 |
| adversarial | 20 | 16 | 13 | 3 | 0 | 8125 [5699, 9341] | 10000 [7718, 10000] | 8125 | 10000 | 0 | 1856 |

Failure taxonomy (counts):

- adversarial: `missed:base64` 1, `missed:leetspeak` 1, `missed:split-across-documents` 1, `not_executed:content_uninspectable` 2

| metric | value | threshold | verdict |
|---|---|---|---|
| recall_bp.dev | 10000 | 8000 | GO |
| precision_bp.dev | 10000 | 9000 | GO |
| typed_recall_bp.dev | 10000 | 7500 | GO |
| leak_items.dev | 0 | 0 | GO |
| fragment_exact_bp.dev | 10000 | 9000 | GO |
| p95_us.dev | 3120 | 50000 | GO |
| recall_bp.heldout | 10000 | 8000 | GO |
| precision_bp.heldout | 10000 | 9000 | GO |
| typed_recall_bp.heldout | 10000 | 7500 | GO |
| leak_items.heldout | 0 | 0 | GO |
| fragment_exact_bp.heldout | 10000 | 9000 | GO |
| p95_us.heldout | 2919 | 50000 | GO |
| heldout_gap_bp | 0 | 1500 | GO |
| adversarial_recall_bp | 8125 | 4000 | GO |
| adversarial_leak_items | 0 | 0 | GO |

## document_pii_vi@document-intake-eval-1: GO

| split | n | pos | tp | fn | fp | recall bp (95% CI) | precision bp (95% CI) | typed recall bp | fragment exact bp | leaks | p95 us |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dev | 60 | 40 | 40 | 0 | 1 | 10000 [9123, 10000] | 9756 [8740, 9957] | 10000 | 10000 | 0 | 2474 |
| heldout | 60 | 40 | 40 | 0 | 4 | 10000 [9123, 10000] | 9090 [7884, 9641] | 10000 | 10000 | 0 | 2241 |

Failure taxonomy (counts):

- dev: `false_positive:benign` 1
- heldout: `false_positive:benign` 4

| metric | value | threshold | verdict |
|---|---|---|---|
| recall_bp.dev | 10000 | 9000 | GO |
| precision_bp.dev | 9756 | 9000 | GO |
| typed_recall_bp.dev | 10000 | 8500 | GO |
| leak_items.dev | 0 | 0 | GO |
| fragment_exact_bp.dev | 10000 | 9900 | GO |
| p95_us.dev | 2474 | 50000 | GO |
| recall_bp.heldout | 10000 | 9000 | GO |
| precision_bp.heldout | 9090 | 9000 | GO |
| typed_recall_bp.heldout | 10000 | 8500 | GO |
| leak_items.heldout | 0 | 0 | GO |
| fragment_exact_bp.heldout | 10000 | 9900 | GO |
| p95_us.heldout | 2241 | 50000 | GO |
| heldout_gap_bp | 0 | 1500 | GO |

## url_ssrf@document-intake-eval-1: GO

| split | n | pos | tp | fn | fp | recall bp (95% CI) | precision bp (95% CI) | typed recall bp | fragment exact bp | leaks | p95 us |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dev | 60 | 40 | 40 | 0 | 0 | 10000 [9123, 10000] | 10000 [9123, 10000] | 10000 | - | 0 | 165 |
| heldout | 60 | 40 | 40 | 0 | 0 | 10000 [9123, 10000] | 10000 [9123, 10000] | 10000 | - | 0 | 179 |
| adversarial | 15 | 9 | 9 | 0 | 0 | 10000 [7008, 10000] | 10000 [7008, 10000] | 10000 | - | 0 | 790 |

Failure taxonomy (counts):


| metric | value | threshold | verdict |
|---|---|---|---|
| recall_bp.dev | 10000 | 10000 | GO |
| precision_bp.dev | 10000 | 9500 | GO |
| typed_recall_bp.dev | 10000 | 9500 | GO |
| leak_items.dev | 0 | 0 | GO |
| p95_us.dev | 165 | 5000 | GO |
| recall_bp.heldout | 10000 | 10000 | GO |
| precision_bp.heldout | 10000 | 9500 | GO |
| typed_recall_bp.heldout | 10000 | 9500 | GO |
| leak_items.heldout | 0 | 0 | GO |
| p95_us.heldout | 179 | 5000 | GO |
| heldout_gap_bp | 0 | 500 | GO |
| adversarial_recall_bp | 10000 | 8000 | GO (indicative) |
| adversarial_leak_items | 0 | 0 | GO |

## How to read the rows

* `document_injection_vi`: 60 dev, 60 held-out and 20 hand-written probes. A hidden or visible
  instruction in a Vietnamese document of seven kinds (TXT, Markdown, JSON with `\u` escapes, CSV,
  HTML, DOCX, PDF) must give the expected `injection.*` code on the text the intake extracted.
  Positives alternate between a place a reader does not see (HTML comment, `display:none`, a
  `w:vanish` run, white text in a PDF) and the body. Probes add header and title text, a file
  labelled with the wrong type, and the known gaps below.
* `document_pii_vi`: the synthetic texts of `data/eval/pii_vn` wrapped in the same seven kinds,
  sent to a pii_export tool. `dlp_vn` must give the expected `pii.*` code; no raw value may appear
  in a finding, a fragment or the masked document of the transformed payload (`leak_items`).
  The false positives come from the vn_regex masker, which reads an upper-case phrase such as
  `LY DO TU CHOI` as a name; they are the masker's known weakness, not the intake's.
* `url_ssrf`: the fetch adapter with a fake resolver and a fake transport. A positive is a URL
  that must not be fetched: a private, loopback, link-local, metadata, shared or reserved address
  (also in the odd spellings a resolver accepts), a name that resolves to one, a scheme other than
  HTTPS, credentials, another port, a redirect to another host, or a domain that is not listed.
  `leak_items` counts requests that reached a forbidden address or host (must be 0).

Known gaps (named in the adversarial taxonomy, not hidden): an instruction split over two
documents, encoded in base64, or written in leetspeak is not found (the same limits as
`injection_regex` on text); an image carries no text (no OCR), so it is reported as
`document.uninspectable` and fails closed on a money, credit or pii_export tool instead.
