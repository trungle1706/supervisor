"""Nightly complaint summariser (synthetic MLflow pyfunc artifact): a fixed job calls a model once."""

import mlflow.pyfunc
from openai import OpenAI

MODEL = "databricks-meta-llama-3-3-70b-instruct"


def run_batch_job(rows: list[str]) -> list[str]:
    client = OpenAI()
    out = []
    for text in rows:
        reply = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": text}]
        )
        out.append(reply.choices[0].message.content)
    return out


class Summariser(mlflow.pyfunc.PythonModel):
    def predict(self, context, model_input):
        return run_batch_job(list(model_input["text"]))
