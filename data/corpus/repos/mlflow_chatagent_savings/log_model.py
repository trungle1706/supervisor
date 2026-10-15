"""Log the agent to Unity Catalog (no tracing is enabled here)."""
import mlflow
from mlflow.models.resources import DatabricksServingEndpoint

mlflow.set_registry_uri("databricks-uc")

with mlflow.start_run():
    info = mlflow.pyfunc.log_model(
        artifact_path="agent",
        python_model="agent.py",
        resources=[DatabricksServingEndpoint(endpoint_name="databricks-claude-3-7-sonnet")],
        registered_model_name="main.agents.savings_agent",
    )
print(info.model_uri)
