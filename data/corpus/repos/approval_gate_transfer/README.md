# Transfer assistant with maker-checker

A small custom agent loop (no framework) for branch staff. It answers balance questions
and prepares transfers. A transfer is only sent after a second officer approves it in the
approval service (maker-checker).

## Layout

- `agent.py`: the loop; calls the internal OpenAI-compatible model server
- `tools.py`: balance and transfer tools, and the approval step
- `telemetry.py`: OpenTelemetry setup

## Run

```cmd
pip install -r requirements.txt
python agent.py
```
