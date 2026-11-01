"""Reads the vendor key from the Databricks secret scope. Nothing is stored in the repo."""


def vendor_key() -> str:
    return dbutils.secrets.get(scope="enrich", key="vendor-api-key")  # noqa: F821
