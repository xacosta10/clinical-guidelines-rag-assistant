"""
The full RAG loop: takes a plain-language question, retrieves the most
relevant chunks from the Chroma vector store (same as test_retrieval.py),
then hands those chunks to Claude and asks it to write an actual answer,
grounded only in what was retrieved and citing which source(s) it used.

Usage:
    pip install anthropic python-dotenv
    python3 rag_qa.py

Requires a .env file in the project root containing:
    ANTHROPIC_API_KEY=your-key-here
"""

import os

import chromadb
from anthropic import Anthropic
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

CHROMA_PATH = "chroma_db"
COLLECTION_NAME = "clinical_guidelines"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
TOP_K = 5

# Haiku is Anthropic's fastest, cheapest model. Plenty for this task,
# since the real work (finding the right information) is already done
# by retrieval before Claude ever sees the question.
CLAUDE_MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = """You are a clinical information assistant for a portfolio \
project. You answer questions using ONLY the numbered source excerpts you \
are given below, never your own outside medical knowledge.

Rules:
- Every sentence that states a fact must end with a citation like [1] or [2] \
pointing to the source excerpt(s) it came from.
- If the excerpts don't contain enough information to answer, say so plainly \
instead of guessing.
- Be concise and direct. This is a demo tool, not a real clinical system.
"""


def format_source_line(meta):
    """Human-readable label for one retrieved chunk, matching the labels
    used in test_retrieval.py."""
    if meta.get("source_type") == "medline_topic":
        return f"MedlinePlus — {meta.get('topic_title', 'Untitled')}"
    else:
        return f"{meta.get('patient_name', 'Unknown Patient')} — {meta.get('section', 'Untitled Section')}"


def retrieve(question, collection, model, top_k=TOP_K):
    """Embed the question and pull back the top_k closest chunks."""
    query_embedding = model.encode([question]).tolist()
    results = collection.query(query_embeddings=query_embedding, n_results=top_k)

    chunks = []
    for i in range(len(results["ids"][0])):
        chunks.append({
            "text": results["documents"][0][i],
            "meta": results["metadatas"][0][i],
            "distance": results["distances"][0][i],
        })
    return chunks


def build_context_block(chunks):
    """Turn retrieved chunks into a numbered block of text Claude can
    cite back to, e.g. '[1]', '[2]'."""
    lines = []
    for i, chunk in enumerate(chunks, start=1):
        label = format_source_line(chunk["meta"])
        lines.append(f"[{i}] Source: {label}\n{chunk['text']}")
    return "\n\n".join(lines)


def ask_claude(client, question, context_block):
    user_message = (
        f"Source excerpts:\n\n{context_block}\n\n"
        f"Question: {question}"
    )

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    # response.content is a list of blocks; for a plain text reply
    # there's just one block of type "text".
    return "".join(block.text for block in response.content if block.type == "text")


def run():
    load_dotenv()  # reads ANTHROPIC_API_KEY out of .env into the environment

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("No ANTHROPIC_API_KEY found. Make sure you have a .env file "
              "in this folder containing:\n\nANTHROPIC_API_KEY=your-key-here\n")
        return

    print(f"Loading embedding model ({EMBEDDING_MODEL})...")
    embed_model = SentenceTransformer(EMBEDDING_MODEL)

    client_db = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client_db.get_collection(COLLECTION_NAME)

    claude = Anthropic()  # picks up ANTHROPIC_API_KEY from the environment automatically

    print(f"Ready. {collection.count()} chunks loaded. Type a question, or 'quit' to exit.\n")

    while True:
        question = input("Question: ").strip()
        if question.lower() in ("quit", "exit", ""):
            break

        chunks = retrieve(question, collection, embed_model)
        context_block = build_context_block(chunks)

        print("\nThinking...\n")
        answer = ask_claude(claude, question, context_block)

        print(answer)
        print("\nSources used:")
        for i, chunk in enumerate(chunks, start=1):
            print(f"  [{i}] {format_source_line(chunk['meta'])} (distance: {chunk['distance']:.3f})")
        print()


if __name__ == "__main__":
    run()
