# Databricks notebook source
# MAGIC %md
# MAGIC # KYC review assistant
# MAGIC Reviews one customer file and proposes a KYC status.

# COMMAND ----------

# MAGIC %pip install langchain langchain-openai mlflow

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import mlflow
import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI

dbutils.widgets.text("customer_id", "C0001")
dbutils.widgets.text("deployment", "kyc-review")
customer_id = dbutils.widgets.get("customer_id")
deployment = dbutils.widgets.get("deployment")

# COMMAND ----------

mlflow.langchain.autolog()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Tools
# MAGIC Plain functions, bound to the model below.

# COMMAND ----------

def doc_ho_so_kyc(customer_id: str) -> dict:
    """Read the KYC record of one customer."""
    df = spark.sql(
        f"SELECT ho_ten, so_cccd, ngay_sinh, dia_chi, trang_thai FROM kyc.customers "
        f"WHERE customer_id = '{customer_id}'"
    )
    return df.toPandas().to_dict("records")[0]


def kiem_tra_cccd(so_cccd: str) -> dict:
    """Check an ID number against the sanctions list."""
    ds_cam = pd.read_csv("/dbfs/FileStore/sanctions/ds_cam.csv")
    hit = ds_cam[ds_cam["so_cccd"] == so_cccd]
    return {"so_cccd": so_cccd, "in_sanctions_list": not hit.empty}


def cap_nhat_trang_thai_kyc(customer_id: str, trang_thai: str, ghi_chu: str) -> str:
    """Write the new KYC status."""
    spark.sql(
        f"UPDATE kyc.customers SET trang_thai = '{trang_thai}', ghi_chu = '{ghi_chu}' "
        f"WHERE customer_id = '{customer_id}'"
    )
    return "updated"

# COMMAND ----------

llm = AzureChatOpenAI(
    azure_deployment=deployment,
    api_version="2024-06-01",
    temperature=0,
)
llm_tools = llm.bind_tools([doc_ho_so_kyc, kiem_tra_cccd, cap_nhat_trang_thai_kyc])

# COMMAND ----------

TOOL_MAP = {
    "doc_ho_so_kyc": doc_ho_so_kyc,
    "kiem_tra_cccd": kiem_tra_cccd,
    "cap_nhat_trang_thai_kyc": cap_nhat_trang_thai_kyc,
}
messages = [
    SystemMessage(content="Ban la nhan vien KYC. Kiem tra ho so, doi chieu danh sach cam, de xuat trang thai."),
    HumanMessage(content=f"Xem xet ho so khach hang {customer_id}."),
]
for _ in range(4):
    ai = llm_tools.invoke(messages)
    messages.append(ai)
    if not ai.tool_calls:
        break
    for call in ai.tool_calls:
        out = TOOL_MAP[call["name"]](**call["args"])
        messages.append({"role": "tool", "tool_call_id": call["id"], "content": str(out)})

print(messages[-1].content)

# COMMAND ----------

# MAGIC %md
# MAGIC Sample row (synthetic): Nguyen Van An, 079000000001, 01/01/1990.
