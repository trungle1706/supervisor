import sys

from graph import build_graph
from tracing import setup_tracing


def main(application_id: str) -> None:
    tracer = setup_tracing()
    app = build_graph()
    with tracer.start_as_current_span("triage_run"):
        result = app.invoke(
            {
                "messages": [("user", f"Triage application {application_id}.")],
                "application_id": application_id,
                "steps": 0,
            }
        )
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "APP-0001")
