# Backlog (items removed from plan v1 and extras found during the build)

| Item | Returns when |
|---|---|
| Docker Compose dev stack (Postgres, MLflow server) | A Linux/Mac dev machine with Docker is the main dev target |
| Lakebase for mutable state | The workspace exposes Lakebase and the owner has rights to create an instance |
| Databricks Workflows jobs | The workspace allows job workloads for this user |
| Model Serving pyfunc host for the gateway | Endpoint creation rights exist and spike B shows the App adds too much latency |
| React/Vite console | A richer UI is needed and Node is available where the build runs |
| Presidio as default masker | spaCy model wheels are on Nexus; until then `presidio` is an optional extra |
| MLflow as primary trace path | MLflow ≥ 3.14 confirmed in the workspace with CREATE TABLE in a schema |
| HSM/KMS notary key, bank WORM anchor | Bank key custody and storage decisions |
| SIEM / ITSM / pager live adapters | Bank endpoint owners named |
| YAML → Cedar policy compiler (D11) | H1 2027 when policies need formal analysis |
| gitleaks binary for repo scrubbing | Bank supplies an approved binary; regex scrubber until then |
