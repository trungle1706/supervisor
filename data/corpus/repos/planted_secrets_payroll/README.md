# Payroll advice agent

Internal chatbot for HR staff. It answers questions about salary slips and can pay a
salary advance to the employee's registered account.

## Run locally

Copy the sample settings, then start the agent:

```bash
export OPENAI_MODEL=gpt-4o-mini
SMTP_PASSWORD=EXAMPLE-smtp-9999
python agent.py "Cho toi xem phieu luong thang 9 cua NV001"
```

## Files

- `agent.py`: chat loop with tool calls
- `tools.py`: database and bank tools
- `settings.py`: python settings
- `config.yaml`: deploy settings
