# policy-qa

LlamaIndex ReAct agent that answers staff questions about internal policy.
Policy documents are plain files in `data/chinh_sach`; they are embedded into a
`VectorStoreIndex` at start-up. Two small helper tools read the fee table or do
date arithmetic. Nothing is written anywhere.

Run: `python main.py`

Tracing: `mlflow.llama_index.autolog()` is switched on in `main.py`.
