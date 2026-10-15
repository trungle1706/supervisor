# notebook_kyc_review

Databricks notebook (exported as .py) for the KYC back office. An Azure OpenAI model reviews a
customer file, checks the ID number against the internal sanctions list, and updates the KYC status.

Import `kyc_review.py` into a workspace as a notebook. The widgets `customer_id` and
`deployment` are set by the job.
