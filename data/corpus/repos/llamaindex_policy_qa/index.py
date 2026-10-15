"""Builds the vector index over the local policy files."""
from llama_index.core import SimpleDirectoryReader, VectorStoreIndex

POLICY_DIR = "data/chinh_sach"


def build_query_engine():
    documents = SimpleDirectoryReader("data/chinh_sach").load_data()
    index = VectorStoreIndex.from_documents(documents)
    return index.as_query_engine(similarity_top_k=4)
