"""Credit memo drafting agent (synthetic MLflow pyfunc artifact)."""

import mlflow.pyfunc
from openai import OpenAI

MODEL = "databricks-meta-llama-3-3-70b-instruct"


def get_applicant_profile(customer_id: str) -> dict:
    row = spark.sql("SELECT customer_id, full_name, monthly_income_minor FROM main.lending.loan_applications")
    return row.first().asDict()


def get_bureau_score(application_id: str) -> dict:
    return spark.sql("SELECT score FROM main.lending.bureau_scores").first().asDict()


def save_memo_draft(application_id: str, memo_text: str) -> str:
    spark.sql("INSERT INTO main.lending.memo_drafts VALUES ('x', 'y')")
    return "saved"


TOOLS = {
    "get_applicant_profile": get_applicant_profile,
    "get_bureau_score": get_bureau_score,
    "save_memo_draft": save_memo_draft,
}


class CreditMemoAgent(mlflow.pyfunc.ChatModel):
    def predict(self, context, messages, params=None):
        client = OpenAI()
        return client.chat.completions.create(model=MODEL, messages=messages)
