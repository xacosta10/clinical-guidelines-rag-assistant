"""
Embeds every chunk in chunks.json and stores it in a local Chroma
vector database, ready for similarity search.

Usage:
    pip install sentence-transformers chromadb
    python3 build_vector_store.py

Reads chunks.json and writes a persistent vector store into the
chroma_db/ folder. Safe to re-run, it clears and rebuilds the
collection each time so you never end up with stale duplicates.
"""

import json
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

CHROMA_PATH = "chroma_db"
COLLECTION_NAME = "clinical_guidelines"
# Small, free, local model. No API key, no cost, runs on CPU fine
# at this data size.
EMBEDDING_MODEL = "all-MiniLM-L6-v2"


def load_chunks(chunks_file="chunks.json"):
    with open(chunks_file, "r", encoding="utf-8") as f:
        return json.load(f)


def build_metadata(chunk):
    """Build a Chroma-safe metadata dict for either chunk type.
    Chroma metadata values must be str/int/float/bool (no None), so
    every field gets a safe default."""
    source_type = chunk.get("source_type", "unknown")

    if source_type == "patient_record":
        return {
            "source_type": source_type,
            "patient_name": chunk.get("patient_name", ""),
            "source_file": chunk.get("source_file", ""),
            "section": chunk.get("section", ""),
        }
    else:  # medline_topic
        return {
            "source_type": source_type,
            "topic_title": chunk.get("topic_title", ""),
            "matched_condition": chunk.get("matched_condition", ""),
            "snomed_code": chunk.get("snomed_code", ""),
            "source_file": chunk.get("source_file", ""),
            "link": chunk.get("link", ""),
        }


def build_vector_store(chunks_file="chunks.json"):
    chunks = load_chunks(chunks_file)
    if not chunks:
        print(f"No chunks found in {chunks_file}. Run chunk_documents.py first.")
        return

    print(f"Loading embedding model ({EMBEDDING_MODEL})...")
    model = SentenceTransformer(EMBEDDING_MODEL)

    print(f"Embedding {len(chunks)} chunks...")
    texts = [c["text"] for c in chunks]
    embeddings = model.encode(texts, show_progress_bar=True).tolist()

    client = chromadb.PersistentClient(path=CHROMA_PATH)

    # Drop any existing collection so re-running this script doesn't
    # pile up duplicate entries from a previous run.
    existing = [c.name for c in client.list_collections()]
    if COLLECTION_NAME in existing:
        client.delete_collection(COLLECTION_NAME)

    collection = client.create_collection(COLLECTION_NAME)

    collection.add(
        ids=[str(c["chunk_id"]) for c in chunks],
        embeddings=embeddings,
        documents=texts,
        metadatas=[build_metadata(c) for c in chunks]
    )

    print(f"Stored {collection.count()} chunks in '{COLLECTION_NAME}' at {CHROMA_PATH}/")


if __name__ == "__main__":
    build_vector_store()
