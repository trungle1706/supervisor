"""Guardian factory (WP-G1 of phase 12, flag GUARDIAN_FACTORY, docs/guardian-factory.md).

A guardian definition is a typed, validated description of one detector: a regex, a keyword
list, a classifier reference, a judge prompt or a small policy. This package holds the schema
(``definition``), the limits (``caps``), the store, the plain-words author, the pattern library
and the adapter that turns a ``live`` definition into a detector of the existing contract.
"""
