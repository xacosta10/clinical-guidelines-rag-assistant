"""
Lets you type a plain-language question and see which chunks the
vector store thinks are most relevant. This is how you manually
check retrieval quality before wiring in an LLM.

Usage:
    python3 test_retrieval.py
"""

import chromadb
from sentence_transformers import SentenceTransformer

CHROMA_PATH = "chroma_db"
COLLECTION_NAME = "clinical_guidelines"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
TOP_K = 3


def format_source_line(meta):
    """Build a human-readable source label depending on chunk type."""
    if meta.get("source_type") == "medline_topic":
        return f"MedlinePlus — {meta.get('topic_title', 'Untitled')} (condition: {meta.get('matched_condition', '?')})"
    else:
        return f"{meta.get('patient_name', 'Unknown Patient')} — {meta.get('section', 'Untitled Section')}"


def run():
    print(f"Loading embedding model ({EMBEDDING_MODEL})...")
    model = SentenceTransformer(EMBEDDING_MODEL)

    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_collection(COLLECTION_NAME)

    print(f"Ready. {collection.count()} chunks loaded. Type a question, or 'quit' to exit.\n")

    while True:
        question = input("Question: ").strip()
        if question.lower() in ("quit", "exit", ""):
            break

        query_embedding = model.encode([question]).tolist()
        results = collection.query(query_embeddings=query_embedding, n_results=TOP_K)

        print()
        for i in range(len(results["ids"][0])):
            meta = results["metadatas"][0][i]
            text = results["documents"][0][i]
            distance = results["distances"][0][i]
            print(f"[{i+1}] {format_source_line(meta)} (distance: {distance:.3f})")
            print(f"    {text[:200]}{'...' if len(text) > 200 else ''}")
            print()


if __name__ == "__main__":
    run()
