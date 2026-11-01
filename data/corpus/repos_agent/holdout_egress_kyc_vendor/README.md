# holdout_egress_kyc_vendor

KYC onboarding assistant (LangChain with a Databricks model endpoint). It sends the identity
document data of a new customer to an outside verification vendor and, after a reviewer in the
review queue agrees, stores the KYC result.

Run: `python agent.py`
