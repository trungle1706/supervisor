# Card and statement assistant (LangGraph supervisor)

A supervisor graph routes a customer request to one of two worker agents:

- `card_agent`: explains card limits and spending (read-only tools)
- `statement_agent`: exports a monthly statement as a CSV file

The supervisor never moves money and never decides credit. MLflow tracing is on.

## Files

- `graph.py`: the supervisor graph and routing
- `workers.py`: the two ReAct worker agents
- `card_tools.py`: card tools
- `statement_tools.py`: statement tools

## Run

```cmd
set SUPERVISOR_MODEL=claude-3-5-sonnet-20241022
python graph.py
```
