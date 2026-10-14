# Test fixtures: synthetic data only

Everything in this folder is **synthetic**. No value belongs to a real person, account or card.

- `pii_labelled.jsonl`: 400 labelled texts (Vietnamese and English) for the PII masking
  recall test (WP4). One JSON object per line: `id`, `language` (`vi`/`en`), `text`,
  `spans` (list of `{start, end, type, text}`; `start`/`end` are Python string offsets,
  end exclusive). Entity types: `PERSON`, `CCCD`, `CMND`, `PHONE`, `EMAIL`, `TAX_CODE`,
  `BANK_ACCOUNT`, `CARD_NUMBER`, `ADDRESS`. Some lines have no spans (hard negatives:
  amounts, dates, transaction references, hotlines).

Identifiers follow real formats so that maskers can be tested: CCCD has 12 digits with a
valid province prefix, card numbers pass Luhn, tax codes carry a valid check digit, e-mail
addresses use the reserved `example.*` domains.

Regenerate (deterministic, seed 20261014):

```
python -m supervisor.data.synthetic --write-fixtures
```

A test checks that the committed file equals the generator output.
