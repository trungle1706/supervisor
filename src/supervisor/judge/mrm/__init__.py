"""Model-risk management pack for the tiered judge (WP19, docs/judge-mrm.md).

Modules: ``identity`` (what is validated), ``card`` (model card), ``validation``
(validation report + GO / NO-GO + ``model_validation`` row), ``inputs``
(``JudgeValidationInput``: pluggable assurance pack results), ``control`` (change
control: validation gate + re-validation triggers), ``agreement`` (judge-vs-human).

Nothing in this package can block or pause an agent. It reads verdicts and sign-offs,
writes reports, evidence records and validation rows, and raises cases through the
case service.
"""
