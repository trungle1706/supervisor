# egress_enrichment_agent

Sales-support assistant for relationship managers. It looks up a company at an external
data vendor (by tax code) and can notify a partner system about a customer.

Config is in `config.yaml`. The vendor key comes from the Databricks secret scope `enrich`.

Run: `python agent.py "Tra cuu cong ty ma so thue 0100000001"`
