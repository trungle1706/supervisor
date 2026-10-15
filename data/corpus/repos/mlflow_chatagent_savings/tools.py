"""Savings tools. `spark` is the notebook / cluster session."""
from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()


def tra_cuu_lai_suat(term_months: int) -> list:
    """Look up savings rates for a term."""
    df = spark.table("main.products.savings_rates")
    rows = df.filter(df.term_months == term_months).collect()
    return [r.asDict() for r in rows]


def mo_tiet_kiem(customer_id: str, so_tai_khoan: str, amount: int, term_months: int) -> dict:
    """Open a term deposit funded from the customer's own account."""
    spark.sql(
        f"INSERT INTO main.savings.term_deposits "
        f"(customer_id, so_tai_khoan, amount, term_months) "
        f"VALUES ('{customer_id}', '{so_tai_khoan}', {int(amount)}, {int(term_months)})"
    )
    return {"status": "opened", "customer_id": customer_id, "term_months": term_months}


TOOL_SPECS = {
    "tra_cuu_lai_suat": {
        "fn": tra_cuu_lai_suat,
        "spec": {
            "type": "function",
            "function": {
                "name": "tra_cuu_lai_suat",
                "description": "Savings interest rates by term in months.",
                "parameters": {
                    "type": "object",
                    "properties": {"term_months": {"type": "integer"}},
                    "required": ["term_months"],
                },
            },
        },
    },
    "mo_tiet_kiem": {
        "fn": mo_tiet_kiem,
        "spec": {
            "type": "function",
            "function": {
                "name": "mo_tiet_kiem",
                "description": "Open a term deposit from the customer's own account.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "string"},
                        "so_tai_khoan": {"type": "string"},
                        "amount": {"type": "integer"},
                        "term_months": {"type": "integer"},
                    },
                    "required": ["customer_id", "so_tai_khoan", "amount", "term_months"],
                },
            },
        },
    },
}
