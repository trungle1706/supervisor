# D31 - Transparency report per agent, three variants, signed into the chain

Status: Accepted (WP31, 2026-10-20). Bank decisions listed under "Open".

## Context

The facts an inspector, a customer or the bank asks for exist in many places: the registry, the inventory graph, the compliance matrix, the cards, assurance results, the judge validation, masking and monitor settings, the risk register, the evidence chain and the case list. Saidot (item 7 in `saidot/COMPARISON.md`) generates a PDF per system from its inventory. Its report is a statement the owner fills in; ours should be a read of facts, say where facts are missing, and be verifiable.

## Decision

1. **A builder over read-only facts.** `ReportBuilder` calls small read methods (`Facts`) and the read services of other packages (inventory summary, risk `agent_summary`, matrix, judge card). It holds no query. A section whose source fails says `source_error` (the class name, not the message) and the report is still made.
2. **Plain JSON data model.** Integers, ids, hashes and masked text; a float is refused. Free text is masked or dropped; with no masker it is dropped.
3. **Three variants with explicit allow-lists.** A field not listed is not copied. The customer variant shows generic wording per agent class and no id of any kind. A second check refuses a report whose customer or regulator version contains an agent id, rule or obligation id, hash, owner field or a person name read again from the raw sources; the same check runs on the rendered text of both languages.
4. **"What this report does not show" is a section, computed.** Flags off, no data, mock judge, ILLUSTRATIVE thresholds, a chain not checked or failing, an obligation id cited but missing, cut lists. Nothing is implied by silence.
5. **Versioned by content.** A new version only when the content hash changes; the hash leaves out time, version and the chain head (which moves with every record, including the report's own).
6. **Signed by hash.** One `transparency_report` chain record per variant and version in the agent lane: content hash, sha256 of the JSON and of each rendered file, section counts and the diff to the previous version (changed section ids). One append-only table row per variant, language and version. Files are never overwritten; reads check the stored file against its row.
7. **Reuse of the case-file path.** HTML takes the case-file page's style block from its template (no new CSS); PDF uses `find_font`, `RenderResult` and `fpdf2` as the case file does and falls back to HTML with a notice. Both are written from the same display blocks, in Vietnamese and English, with labels in the console i18n tables.
8. **Hook for WP30.** `register("controls", fn)` plus `allowlist.set_spec`; until then the section says "not built".
9. **Roles and flags.** `transparency.view` for every role, `transparency.generate` for reviewer and admin; generate writes two audit rows. Flags `TRANSPARENCY_ENABLED` and `CONSOLE_TRANSPARENCY_ENABLED`, off. The job regenerates running agents daily and is listed in the scheduler only when the flag is on.

## Alternatives rejected

| Alternative | Why not |
|---|---|
| One report with fields hidden by CSS or by the template | A hidden field is still in the file. Projection happens on the data |
| Mask names in the regulator version | The masker misses names (BACKLOG); omission is the only safe rule |
| Store the report text in the chain | R2: no text in the chain. Hashes only |
| New HTML template with new CSS | Two places to keep in step; the case file already has the bank-reviewed look |
| A new version on every run | Churn: the chain head and the time change every run |
| Run the chain check in the page request | Cost; the job and generate run it, the console shows the stored result |

## Consequences

* A report says "preview" until a person or the job signs it.
* A lost file on the App is visible (404) and can be rebuilt; the old hash stays in the chain.
* The customer text is generic; naming the product is a decision for the owner.
* Extension: WP30 adds `controls`; a new section needs a collector, a block function, labels and allow-list entries.

## Open

1. May the customer version name the product? 2. Which roles may generate or hand on the customer version? 3. Should the regulator version show owner team or only a role? 4. Real band thresholds (ILLUSTRATIVE until then).
