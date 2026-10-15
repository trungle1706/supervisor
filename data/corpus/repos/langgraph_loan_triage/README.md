# loan-triage-graph

LangGraph agent that triages retail loan applications for the credit team.
The model reads an application, looks at the bureau score and records a
pre-approval decision (approve, decline or refer).

Run: `python main.py APP-0001`

Tracing: OpenTelemetry spans are exported by `tracing.py` (OTLP over HTTP).
